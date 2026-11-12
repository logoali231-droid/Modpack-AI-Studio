"""Modrinth API lookup, game-version metadata, dependency metadata, downloads, and integrity checks."""
import hashlib, time
from pathlib import Path
from urllib.parse import quote
import requests

API="https://api.modrinth.com/v2"
class Modrinth:
    def __init__(self,log):
        self.log=log; self.s=requests.Session()
        self.s.headers.update({"User-Agent":"ModpackAIStudio/0.3 (desktop; user initiated)"})
    def get(self,url,params=None):
        for attempt in range(4):
            try:
                r=self.s.get(url,params=params,timeout=(10,45))
                if r.status_code==429:
                    delay=min(int(r.headers.get("Retry-After","3")),30); self.log(f"Rate limited; waiting {delay}s"); time.sleep(delay); continue
                r.raise_for_status(); return r.json()
            except (requests.Timeout,requests.ConnectionError):
                if attempt==3: raise
                time.sleep(1.5*(attempt+1))
        raise RuntimeError("Modrinth rate limit persisted after retries.")
    def game_versions(self):
        """Return official release versions known to Modrinth, newest first."""
        versions=self.get(f"{API}/tag/game_version")
        return [v["version"] for v in versions if v.get("version_type")=="release" and v.get("version")]
    def resolve(self,identifier,mc,loader):
        versions=self.get(f"{API}/project/{quote(str(identifier),safe='')}/version",
            {"game_versions":f'["{mc}"]',"loaders":f'["{loader}"]'})
        versions.sort(key=lambda x:x.get("date_published",""),reverse=True)
        for v in versions:
            files=v.get("files") or []; primary=next((f for f in files if f.get("primary")),files[0] if files else None)
            if primary and primary.get("url") and primary.get("filename","").endswith(".jar"):
                return {"project_id":v.get("project_id"),"version_id":v["id"],"version_number":v.get("version_number"),
                    "name":primary["filename"],"url":primary["url"],"hashes":primary.get("hashes",{}),
                    "dependencies":v.get("dependencies",[]),"project":identifier}
        self.log(f"No compatible {mc}/{loader} JAR: {identifier}"); return None
    def search(self,query,mc,loader):
        """Return candidate projects; callers must verify the title and compatible JAR."""
        data=self.get(f"{API}/search",{"query":query,"facets":f'[["versions:{mc}"],["categories:{loader}"]]','limit':20})
        return data.get("hits",[])
    def download(self,mod,dest):
        dest=Path(dest); dest.mkdir(parents=True,exist_ok=True); name=Path(mod["name"]).name
        if not name.endswith(".jar") or name in (".",".."): raise ValueError(f"Unsafe filename: {name}")
        path=dest/name; r=self.s.get(mod["url"],timeout=(15,180)); r.raise_for_status(); content=r.content
        for algo in ("sha1","sha512"):
            expected=mod.get("hashes",{}).get(algo)
            if expected and hashlib.new(algo,content).hexdigest().lower()!=expected.lower(): raise RuntimeError(f"{algo} mismatch: {name}")
        if path.exists():
            if hashlib.sha1(path.read_bytes()).digest()==hashlib.sha1(content).digest(): return path
            raise FileExistsError(f"{name} exists with different contents; refusing overwrite.")
        tmp=path.with_name(path.name+".part")
        try: tmp.write_bytes(content); tmp.replace(path)
        finally:
            if tmp.exists(): tmp.unlink()
        self.log(f"Downloaded {name} ({len(content)//1024} KB)"); return path
