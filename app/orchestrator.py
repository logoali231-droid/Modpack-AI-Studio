from pathlib import Path
import json, shutil, datetime
from .llm import LLMClient
from .modrinth import Modrinth
from .curseforge import CurseForge
from .quests import build_chapter, validate_campaign

class ModpackPipeline:
    def __init__(self,cfg,log):
        self.c,self.log=cfg,log
        self.llm=LLMClient(cfg["provider"],cfg.get("api_key",""),cfg["model"],log,cfg.get("ollama_url","http://localhost:11434"))
        self.api = (CurseForge(log, cfg.get("curseforge_key", ""))
                    if cfg.get("catalog") == "CurseForge" else Modrinth(log))
    def minecraft_dir(self):
        root=Path(self.c["instance"]).expanduser().resolve()
        for p in (root/".minecraft",root/"minecraft",root):
            if p.is_dir() and (p.name==".minecraft" or (p/"mods").exists() or (p/"config").exists()): return p
        raise ValueError("Could not identify the Minecraft directory in this Prism instance.")
    def run(self):
        mc,loader,concept=self.c["version"],self.c["loader"],self.c["prompt"]
        catalog = self.c.get("catalog", "Modrinth")
        self.log(f"1/4 · Designing the modpack for {catalog}…")
        if catalog == "CurseForge":
            identity = '"name":"exact CurseForge project name"'
        else:
            identity = '"name":"...","slug":"exact Modrinth project slug"'
        system=(f'You are a careful Minecraft modpack architect. Return ONLY JSON: {{"mods":[{{{identity},"reason":"..."}}]}}. '
          'Suggest 15-20 projects if the ecosystem supports it. Never fabricate project names or identifiers. Prefer real, maintained projects compatible with the exact game version and loader. Avoid duplicate functionality and obvious conflicts.')
        raw=self.llm.text(system,f"Minecraft: {mc}\nLoader: {loader}\nCatalog: {catalog}\nConcept: {concept}\nReturn a curated list.")
        data=self.llm.json_from(raw); proposed=data.get("mods") if isinstance(data,dict) else data
        if not isinstance(proposed,list) or not proposed: raise ValueError("AI did not return a non-empty mods array.")
        proposed=proposed[:25]; self.log(f"AI proposed {len(proposed)} projects.")
        self.log(f"2/4 · Checking {catalog} compatibility and dependencies…")
        queue=[]; resolved={}; seen=set()
        for entry in proposed:
            if not isinstance(entry,dict): continue
            ident = (entry.get("slug") or "").strip() if catalog == "Modrinth" else ""
            if entry.get("name") and (catalog == "CurseForge" or not ident):
                hit=self.api.search(entry["name"],mc,loader)
                if hit: ident=hit.get("slug") or hit.get("project_id")
            if ident: queue.append(ident)
        while queue:
            ident=queue.pop(0)
            if ident in seen: continue
            seen.add(ident)
            try: item=self.api.resolve(ident,mc,loader)
            except Exception as exc: self.log(f"Could not resolve {ident}: {exc}"); continue
            if not item: continue
            resolved[item["project_id"]]=item
            for dep in item["dependencies"]:
                if dep.get("dependency_type")=="required":
                    depid=dep.get("project_id")
                    if depid and depid not in resolved and depid not in seen: queue.append(depid)
        if not resolved: raise RuntimeError(f"No compatible {catalog} files found for this Minecraft version/loader.")
        self.log(f"Found {len(resolved)} compatible projects including required dependencies.")
        mcdir=self.minecraft_dir(); modsdir=mcdir/"mods"; modsdir.mkdir(parents=True,exist_ok=True)
        self.log("3/4 · Installing verified JAR files…")
        if self.c.get("backup") and any(modsdir.iterdir()):
            backup=modsdir.with_name("mods.backup-"+datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
            shutil.copytree(modsdir,backup); self.log(f"Backup created: {backup}")
        installed=[]; failed=[]
        for item in resolved.values():
            try:
                path=self.api.download(item,modsdir)
                installed.append({"name":item["name"],"project_id":item["project_id"],"version_id":item["version_id"],"file":path.name})
            except Exception as exc:
                failed.append({"file":item["name"],"error":str(exc)}); self.log(f"Download failed: {item['name']}: {exc}")
        manifest={"app":"Modpack AI Studio","minecraft":mc,"loader":loader,"catalog":catalog,"concept":concept,
            "created":datetime.datetime.now(datetime.timezone.utc).isoformat(),"installed":installed,"failed":failed}
        (mcdir/"modpack-ai-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
        self.log(f"Installed {len(installed)} files; {len(failed)} failed. Manifest saved.")
        if self.c.get("quests"):
            self.log("4/4 · Designing a three-chapter quest campaign…")
            names=", ".join(x["name"] for x in installed)
            qsystem=('Return ONLY JSON matching {"chapters":[{"title":"...","description":"...","quests":[{"title":"...","description":"...","tasks":[{"item":"minecraft:iron_ingot","count":4}],"reward":{"item":"minecraft:bread","count":2}}]}]}. '
                'Exactly 3 chapters, 3-6 quests per chapter. Use plausible item IDs. Do not return SNBT.')
            rawq=self.llm.text(qsystem,f"Concept: {concept}\nMinecraft {mc} {loader}. Installed mod files: {names}")
            campaign=validate_campaign(self.llm.json_from(rawq))
            out=mcdir/"config"/"ftbquests"/"quests"/"chapters"; out.mkdir(parents=True,exist_ok=True)
            for i,ch in enumerate(campaign["chapters"],1):
                (out/f"ai_chapter_{i}.snbt").write_text(build_chapter(ch,i),encoding="utf-8")
                self.log(f"Quest draft written: ai_chapter_{i}.snbt")
            self.log("FTB Quests output is a draft; validate against the installed FTB Quests version in-game.")
        self.log("Done. Review the manifest and test the Prism instance.")
