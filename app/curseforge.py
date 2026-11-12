"""CurseForge Minecraft mod lookup, required dependencies, and verified downloads.

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
            "User-Agent": "ModpackAIStudio/0.3",
        })

    def get(self, url, params=None):
        for attempt in range(4):
            try:
                r = self.s.get(url, params=params, timeout=(10, 45))
                if r.status_code == 429:
                    delay = min(int(r.headers.get("Retry-After", "3")), 30)
                    self.log(f"CurseForge rate limited; waiting {delay}s")
                    time.sleep(delay)
                    continue
                r.raise_for_status()
                payload = r.json()
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
            "pageSize": 10,
            "sortField": 2,
            "sortOrder": "desc",
        }
        hits = self.get(f"{API}/mods/search", params) or []
        if not hits:
            return None
        hit = hits[0]
        return {"slug": str(hit["id"]), "name": hit.get("name", query)}

    def resolve(self, identifier, mc, loader):
        try:
            mod_id = int(identifier)
        except (TypeError, ValueError):
            hit = self.search(str(identifier), mc, loader)
            if not hit:
                self.log(f"No CurseForge project found: {identifier}")
                return None
            mod_id = int(hit["slug"])

        params = {
            "gameVersion": mc,
            "modLoaderType": LOADER_TYPES[loader],
            "pageSize": 50,
        }
        files = self.get(f"{API}/mods/{mod_id}/files", params) or []
        files = [f for f in files if f.get("isAvailable", True)]
        files.sort(key=lambda f: f.get("fileDate", ""), reverse=True)
        for f in files:
            if f.get("releaseType") not in (1, 2):
                continue
            filename = f.get("fileName", "")
            if not filename.lower().endswith(".jar"):
                continue
            download_url = f.get("downloadUrl")
            if not download_url:
                try:
                    download_url = self.get(f"{API}/mods/{mod_id}/files/{f['id']}/download-url")
                except requests.RequestException:
                    continue
            if not download_url:
                continue
            deps = [
                {"project_id": str(d["modId"]), "dependency_type": "required"}
                for d in f.get("dependencies", [])
                if d.get("relationType") == 3 and d.get("modId")
            ]
            hashes = {}
            for h in f.get("hashes", []):
                if h.get("algo") == 1:
                    hashes["sha1"] = h.get("value")
                elif h.get("algo") == 2:
                    hashes["md5"] = h.get("value")
            return {
                "project_id": str(mod_id),
                "version_id": str(f["id"]),
                "version_number": f.get("displayName") or filename,
                "name": filename,
                "url": download_url,
                "hashes": hashes,
                "dependencies": deps,
                "project": str(mod_id),
            }
        self.log(f"No compatible CurseForge JAR: project {mod_id} ({mc}/{loader})")
        return None

    def download(self, mod, dest):
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        name = Path(mod["name"]).name
        if not name.lower().endswith(".jar") or name in (".", ".."):
            raise ValueError(f"Unsafe filename: {name}")
        r = self.s.get(mod["url"], timeout=(15, 180))
        r.raise_for_status()
        content = r.content
        for algo in ("sha1", "md5"):
            expected = mod.get("hashes", {}).get(algo)
            if expected and hashlib.new(algo, content).hexdigest().lower() != expected.lower():
                raise RuntimeError(f"{algo} mismatch: {name}")
        path = dest / name
        if path.exists():
            if hashlib.sha1(path.read_bytes()).digest() == hashlib.sha1(content).digest():
                return path
            raise FileExistsError(f"{name} exists with different contents; refusing overwrite.")
        tmp = path.with_name(path.name + ".part")
        try:
            tmp.write_bytes(content)
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()
        self.log(f"Downloaded {name} ({len(content) // 1024} KB)")
        return path
