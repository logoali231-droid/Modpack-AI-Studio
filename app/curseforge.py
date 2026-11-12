"""CurseForge Minecraft mod lookup, candidate discovery, dependencies, and verified downloads.

CurseForge's official API requires a user-supplied API key. The app never
ships a shared key. API details: https://docs.curseforge.com/
"""
import hashlib
import time
from pathlib import Path

import requests

API = "https://api.curseforge.com/v1"
GAME_ID = 432
MINECRAFT_MOD_CLASS = 6
LOADER_TYPES = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}


class CurseForge:
    def __init__(self, log, api_key):
        if not api_key:
            raise ValueError("CurseForge requires your own API key.")
        self.log = log
        self.s = requests.Session()
        self.s.headers.update({
            "Accept": "application/json",
            "x-api-key": api_key,
            "User-Agent": "ModpackAIStudio/0.4",
        })

    def get(self, url, params=None):
        for attempt in range(4):
            try:
                response = self.s.get(url, params=params, timeout=(10, 45))
                if response.status_code == 429:
                    delay = min(int(response.headers.get("Retry-After", "3")), 30)
                    self.log(f"CurseForge rate limited; waiting {delay}s")
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                payload = response.json()
                return payload.get("data", payload)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("CurseForge rate limit persisted after retries.")

    def search(self, query, mc, loader):
        params = {
            "gameId": GAME_ID,
            "classId": MINECRAFT_MOD_CLASS,
            "searchFilter": query,
            "gameVersion": mc,
            "modLoaderType": LOADER_TYPES[loader],
            "pageSize": 20,
            "sortField": 2,
            "sortOrder": "desc",
        }
        hits = self.get(f"{API}/mods/search", params) or []
        return [
            {
                "project_id": str(hit["id"]),
                "slug": str(hit["id"]),
                "name": hit.get("name", query),
                "description": hit.get("summary", ""),
                "categories": [
                    category.get("name", "") for category in hit.get("categories", [])
                    if category.get("name")
                ],
                "downloads": hit.get("downloadCount", 0),
            }
            for hit in hits if hit.get("id")
        ]

    def resolve(self, identifier, mc, loader):
        try:
            mod_id = int(identifier)
        except (TypeError, ValueError):
            candidates = self.search(str(identifier), mc, loader)
            if not candidates:
                self.log(f"No CurseForge project found: {identifier}")
                return None
            mod_id = int(candidates[0]["project_id"])

        params = {
            "gameVersion": mc,
            "modLoaderType": LOADER_TYPES[loader],
            "pageSize": 50,
        }
        files = self.get(f"{API}/mods/{mod_id}/files", params) or []
        files = [file for file in files if file.get("isAvailable", True)]
        files.sort(key=lambda file: file.get("fileDate", ""), reverse=True)
        for file in files:
            if file.get("releaseType") not in (1, 2):
                continue
            filename = file.get("fileName", "")
            if not filename.lower().endswith(".jar"):
                continue
            download_url = file.get("downloadUrl")
            if not download_url:
                try:
                    download_url = self.get(f"{API}/mods/{mod_id}/files/{file['id']}/download-url")
                except requests.RequestException:
                    continue
            if not download_url:
                continue
            dependencies = [
                {"project_id": str(dep["modId"]), "dependency_type": "required"}
                for dep in file.get("dependencies", [])
                if dep.get("relationType") == 3 and dep.get("modId")
            ]
            hashes = {}
            for item in file.get("hashes", []):
                if item.get("algo") == 1:
                    hashes["sha1"] = item.get("value")
                elif item.get("algo") == 2:
                    hashes["md5"] = item.get("value")
            return {
                "project_id": str(mod_id),
                "version_id": str(file["id"]),
                "version_number": file.get("displayName") or filename,
                "name": filename,
                "url": download_url,
                "hashes": hashes,
                "dependencies": dependencies,
                "project": str(mod_id),
            }
        self.log(f"No compatible CurseForge JAR: project {mod_id} ({mc}/{loader})")
        return None

    def details(self, identifier):
        """Fetch the full CurseForge description and project metadata."""
        mod_id = int(identifier)
        project = self.get(f"{API}/mods/{mod_id}")
        if not isinstance(project, dict):
            raise ValueError(f"Unexpected CurseForge project response for {identifier}")
        try:
            description = self.get(f"{API}/mods/{mod_id}/description")
        except requests.RequestException as exc:
            self.log(f"Could not fetch full CurseForge description for {mod_id}: {exc}")
            description = ""
        if isinstance(description, dict):
            description = description.get("description", "")
        authors = [
            author.get("name", "") for author in project.get("authors", [])
            if author.get("name")
        ]
        versions = project.get("latestFilesIndexes", []) or []
        game_versions = sorted({
            str(version.get("gameVersion")) for version in versions if version.get("gameVersion")
        })
        loaders = sorted({
            {1: "forge", 4: "fabric", 5: "quilt", 6: "neoforge"}.get(version.get("modLoader"), "")
            for version in versions if version.get("modLoader")
        } - {""})
        links = project.get("links") or {}
        return {
            "source": "curseforge",
            "project_id": str(project.get("id") or identifier),
            "slug": project.get("slug", ""),
            "name": project.get("name") or str(identifier),
            "summary": project.get("summary", ""),
            "description": str(description or ""),
            "authors": authors,
            "categories": [
                category.get("name", "") for category in project.get("categories", [])
                if category.get("name")
            ],
            "game_versions": game_versions,
            "loaders": loaders,
            "downloads": project.get("downloadCount", 0),
            "icon_url": (project.get("logo") or {}).get("url", ""),
            "website": links.get("websiteUrl") or links.get("sourceUrl") or "",
            "license": "",
            "date_modified": project.get("dateModified", ""),
        }

    def download(self, mod, dest):
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        name = Path(mod["name"]).name
        if not name.lower().endswith(".jar") or name in (".", ".."):
            raise ValueError(f"Unsafe filename: {name}")
        response = self.s.get(mod["url"], timeout=(15, 180))
        response.raise_for_status()
        content = response.content
        for algorithm in ("sha1", "md5"):
            expected = mod.get("hashes", {}).get(algorithm)
            if expected and hashlib.new(algorithm, content).hexdigest().lower() != expected.lower():
                raise RuntimeError(f"{algorithm} mismatch: {name}")
        path = dest / name
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
