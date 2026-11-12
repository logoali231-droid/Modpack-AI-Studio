"""Modrinth API lookup, candidate discovery, dependency metadata, and verified downloads."""
import hashlib
import time
from pathlib import Path
from urllib.parse import quote

import requests

API = "https://api.modrinth.com/v2"


class Modrinth:
    def __init__(self, log):
        self.log = log
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "ModpackAIStudio/0.4 (desktop; user initiated)"})

    def get(self, url, params=None):
        for attempt in range(4):
            try:
                response = self.s.get(url, params=params, timeout=(10, 45))
                if response.status_code == 429:
                    delay = min(int(response.headers.get("Retry-After", "3")), 30)
                    self.log(f"Rate limited; waiting {delay}s")
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("Modrinth rate limit persisted after retries.")

    def game_versions(self):
        versions = self.get(f"{API}/tag/game_version")
        return [
            version["version"] for version in versions
            if version.get("version_type") == "release" and version.get("version")
        ]

    def resolve(self, identifier, mc, loader):
        versions = self.get(
            f"{API}/project/{quote(str(identifier), safe='')}/version",
            {"game_versions": f'["{mc}"]', "loaders": f'["{loader}"]'},
        )
        versions.sort(key=lambda value: value.get("date_published", ""), reverse=True)
        for version in versions:
            files = version.get("files") or []
            jars = [
                file for file in files
                if file.get("url") and file.get("filename", "").lower().endswith(".jar")
            ]
            primary = next((file for file in jars if file.get("primary")), None)
            selected = primary or (jars[0] if jars else None)
            if selected:
                return {
                    "project_id": version.get("project_id"),
                    "version_id": version["id"],
                    "version_number": version.get("version_number"),
                    "name": selected["filename"],
                    "url": selected["url"],
                    "hashes": selected.get("hashes", {}),
                    "dependencies": version.get("dependencies", []),
                    "project": identifier,
                }
        self.log(f"No compatible {mc}/{loader} JAR: {identifier}")
        return None

    def search(self, query, mc, loader):
        """Return normalized catalog candidates; resolve() remains the compatibility authority."""
        params = {
            "query": query,
            "facets": f'[["versions:{mc}"],["categories:{loader}"]]',
            "limit": 20,
            "index": "relevance",
        }
        data = self.get(f"{API}/search", params)
        candidates = []
        for hit in data.get("hits", []):
            project_id = hit.get("project_id")
            if not project_id:
                continue
            candidates.append({
                "project_id": str(project_id),
                "slug": hit.get("slug"),
                "name": hit.get("title") or hit.get("slug") or str(project_id),
                "description": hit.get("description", ""),
                "categories": hit.get("categories", []),
                "downloads": hit.get("downloads", 0),
            })
        return candidates

    def details(self, identifier):
        """Fetch the full public project description and metadata for the local index."""
        project = self.get(f"{API}/project/{quote(str(identifier), safe='')}")
        if not isinstance(project, dict):
            raise ValueError(f"Unexpected Modrinth project response for {identifier}")
        return {
            "source": "modrinth",
            "project_id": str(project.get("id") or identifier),
            "slug": project.get("slug", ""),
            "name": project.get("title") or project.get("slug") or str(identifier),
            "summary": project.get("description", ""),
            "description": project.get("body", ""),
            "authors": [],
            "categories": project.get("categories", []),
            "game_versions": project.get("game_versions", []),
            "loaders": project.get("loaders", []),
            "downloads": project.get("downloads", 0),
            "icon_url": project.get("icon_url", ""),
            "website": project.get("source_url") or project.get("wiki_url") or "",
            "license": (project.get("license") or {}).get("name", ""),
            "date_modified": project.get("updated", ""),
        }

    def download(self, mod, dest):
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        name = Path(mod["name"]).name
        if not name.lower().endswith(".jar") or name in (".", ".."):
            raise ValueError(f"Unsafe filename: {name}")
        path = dest / name
        response = self.s.get(mod["url"], timeout=(15, 180))
        response.raise_for_status()
        content = response.content
        for algorithm in ("sha1", "sha512"):
            expected = mod.get("hashes", {}).get(algorithm)
            if expected and hashlib.new(algorithm, content).hexdigest().lower() != expected.lower():
                raise RuntimeError(f"{algorithm} mismatch: {name}")
        if path.exists():
            if hashlib.sha1(path.read_bytes()).digest() == hashlib.sha1(content).digest():
                return path
            raise FileExistsError(f"{name} exists with different contents; refusing overwrite.")
        temporary = path.with_name(path.name + ".part")
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
        self.log(f"Downloaded {name} ({len(content) // 1024} KB)")
        return path
