from pathlib import Path
import json, shutil, datetime, re
from .llm import LLMClient
from .modrinth import Modrinth
from .curseforge import CurseForge
from .quests import build_chapter, validate_campaign
from .prompts import VERSION_SYSTEM, modpack_system, QUEST_SYSTEM

class ModpackPipeline:
    def __init__(self,cfg,log,progress=None):
        self.c,self.log=cfg,log
        self.progress_cb=progress or (lambda value,maximum,message: None)
    def progress(self,value,maximum,message):
        self.progress_cb(value,maximum,message)
        self.llm=LLMClient(cfg["provider"],cfg.get("api_key",""),cfg["model"],log,cfg.get("ollama_url","http://localhost:11434"))
        self.api = (CurseForge(log, cfg.get("curseforge_key", ""))
                    if cfg.get("catalog") == "CurseForge" else Modrinth(log))
    def minecraft_dir(self):
        root=Path(self.c["instance"]).expanduser().resolve()
        # Prism stores game files in instance/minecraft, even before mods/config exist.
        for p in (root/"minecraft",root/".minecraft",root):
            if p.is_dir() and (p.name in ("minecraft",".minecraft") or (p/"mods").exists() or (p/"config").exists()): return p
        raise ValueError("Could not identify the Minecraft directory in this Prism instance.")
    def select_minecraft_version(self, concept, fallback):
        """Ask the AI for a target release, then validate it against known released versions."""
        # A version explicitly named by the user is a hard constraint.
        explicit = re.search(r"(?<!\d)(1\.\d{1,2}(?:\.\d{1,2})?)(?!\d)", concept)
        versions=Modrinth(self.log).game_versions()
        if explicit:
            selected=explicit.group(1)
            if selected not in versions:
                raise ValueError(f"Prompt explicitly requests Minecraft {selected}, but Modrinth does not list it as a release.")
            reason="Explicitly requested in the modpack prompt; automatic selection did not override it."
            self.log(f"Using explicitly requested Minecraft version {selected}.")
            return selected, reason
        self.log("AI: choosing a Minecraft release based on your modpack description…")
        system=VERSION_SYSTEM
        raw=self.llm.text(system,
            "Modpack concept and requirements:\n"+concept+
            "\nChoose the best Minecraft Java release for this specific pack. Return JSON only.")
        choice=self.llm.json_from(raw)
        if not isinstance(choice,dict): raise ValueError("AI version selection was not a JSON object.")
        selected=str(choice.get("minecraft_version","")).strip()
        if not selected: raise ValueError("AI did not return minecraft_version.")
        # Use the official release list exposed by Modrinth's public version tags.
        if selected not in versions:
            raise ValueError(f"AI selected Minecraft {selected}, but it is not a recognized release version. "
                             "No files were downloaded. Disable automatic selection and choose a version manually.")
        reason=str(choice.get("reason","No reason supplied.")).strip()
        self.log(f"AI selected Minecraft {selected}. Reason: {reason}")
        return selected, reason
    def run(self):
        self.progress(0,100,"Preparing your modpack…")
        mc,loader,concept=self.c["version"],self.c["loader"],self.c["prompt"]
        auto_version=bool(self.c.get("auto_version",False))
        if auto_version:
            self.progress(3,100,"Choosing a Minecraft release…")
            mc,version_reason=self.select_minecraft_version(concept,mc)
        else:
            version_reason="Selected manually by the user."
        catalog = self.c.get("catalog", "Modrinth")
        self.progress(10,100,f"Designing the modpack for Minecraft {mc}…")
        self.log(f"1/4 · Designing the modpack for {catalog} on Minecraft {mc}…")
        system=modpack_system(catalog)
        user_brief=(f"FIXED TARGET\\nMinecraft Java: {mc}\\nModloader: {loader}\\nCatalog: {catalog}\\n\\n"
                    f"USER'S MODPACK BRIEF (preserve its constraints):\\n{concept}\\n\\n"
                    "Design a cohesive candidate list. Return the required JSON only.")
        raw=self.llm.text(system,user_brief)
        data=self.llm.json_from(raw); proposed=data.get("mods") if isinstance(data,dict) else data
        if not isinstance(proposed,list) or not proposed: raise ValueError("AI did not return a non-empty mods array.")
        proposed=proposed[:25]; self.log(f"AI proposed {len(proposed)} projects.")
        self.progress(25,100,"Checking project compatibility and dependencies…")
        self.log(f"2/4 · Checking {catalog} compatibility and dependencies…")
        queue=[]; resolved={}; seen=set()
        for entry in proposed:
            if not isinstance(entry,dict): continue
            name=str(entry.get("name") or "").strip()
            # Never trust model-generated slugs or IDs. Search the selected catalog by
            # human-readable name, then resolve the authoritative project ID.
            if name: queue.append(("",name))
        while queue:
            ident,fallback_name=queue.pop(0)
            if ident and ident in seen: continue
            if ident: seen.add(ident)
            try:
                item=self.api.resolve(ident,mc,loader) if ident else None
            except Exception as exc:
                status=getattr(getattr(exc,"response",None),"status_code",None)
                if status==404 and fallback_name:
                    self.log(f"Unknown project identifier '{ident}'. Searching the catalog for '{fallback_name}'…")
                    item=None
                else:
                    self.log(f"Could not resolve {ident or fallback_name}: {exc}"); continue
            if not item and fallback_name:
                try:
                    hits=self.api.search(fallback_name,mc,loader)
                    if catalog=="Modrinth":
                        # Never trust the first search hit. Require an exact normalized
                        # project-title match, then verify a real compatible JAR.
                        normalize=lambda value: re.sub(r"[^a-z0-9]","",str(value or "").lower())
                        wanted=normalize(fallback_name)
                        exact=[h for h in hits if normalize(h.get("title"))==wanted]
                        if not exact:
                            self.log(f"No exact Modrinth project-name match for '{fallback_name}'; skipping rather than installing an unrelated result.")
                        for hit in exact:
                            replacement_id=hit.get("slug") or hit.get("project_id")
                            if not replacement_id or replacement_id==ident: continue
                            self.log(f"Exact Modrinth title match for '{fallback_name}': {hit.get('title')} ({replacement_id})")
                            item=self.api.resolve(replacement_id,mc,loader)
                            if item: break
                    else:
                        hit=hits[0] if isinstance(hits,list) and hits else hits
                        replacement_id=(hit or {}).get("slug") or (hit or {}).get("project_id")
                        if replacement_id and replacement_id!=ident:
                            item=self.api.resolve(replacement_id,mc,loader)
                except Exception as exc:
                    self.log(f"Could not find a verified compatible match for '{fallback_name}': {exc}")
            if not item: continue
            resolved[item["project_id"]]=item
            for dep in item["dependencies"]:
                if dep.get("dependency_type")=="required":
                    depid=dep.get("project_id")
                    if depid and depid not in resolved and depid not in seen: queue.append((depid,""))
        if not resolved: raise RuntimeError(f"No compatible {catalog} files found for Minecraft {mc}/{loader}.")
        self.log(f"Found {len(resolved)} compatible projects including required dependencies.")
        self.progress(50,100,f"{len(resolved)} compatible projects verified. Preparing installation…")
        mcdir=self.minecraft_dir(); modsdir=mcdir/"mods"; modsdir.mkdir(parents=True,exist_ok=True)
        self.log("3/4 · Installing verified JAR files…")
        if self.c.get("backup") and any(modsdir.iterdir()):
            backup=modsdir.with_name("mods.backup-"+datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
            shutil.copytree(modsdir,backup); self.log(f"Backup created: {backup}")
        installed=[]; failed=[]
        total_downloads=len(resolved)
        for download_index,item in enumerate(resolved.values(),1):
            self.progress(50+int(35*(download_index-1)/max(total_downloads,1)),100,
                          f"Installing mod {download_index} of {total_downloads}: {item['name']}")
            try:
                path=self.api.download(item,modsdir)
                installed.append({"name":item["name"],"project_id":item["project_id"],"version_id":item["version_id"],"file":path.name})
            except Exception as exc:
                failed.append({"file":item["name"],"error":str(exc)}); self.log(f"Download failed: {item['name']}: {exc}")
        manifest={"app":"Modpack AI Studio","minecraft":mc,"minecraft_version_selection":"ai" if auto_version else "manual",
            "minecraft_version_reason":version_reason,"loader":loader,"catalog":catalog,"concept":concept,
            "created":datetime.datetime.now(datetime.timezone.utc).isoformat(),"installed":installed,"failed":failed}
        (mcdir/"modpack-ai-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
        self.log(f"Installed {len(installed)} files; {len(failed)} failed. Manifest saved.")
        self.progress(88,100,"Mod installation finished.")
        if self.c.get("quests"):
            self.progress(0,0,"Ollama is generating your three-chapter quest campaign…")
            self.log("4/4 · Designing a three-chapter quest campaign…")
            self.log("Quest generation can take a while on a local model. Waiting for the AI response…")
            names=", ".join(x["name"] for x in installed)
            rawq=self.llm.text(QUEST_SYSTEM,f"Concept: {concept}\\nMinecraft {mc} {loader}. Installed mods: {names}")
            campaign=validate_campaign(self.llm.json_from(rawq))
            out=mcdir/"config"/"ftbquests"/"quests"/"chapters"; out.mkdir(parents=True,exist_ok=True)
            for i,ch in enumerate(campaign["chapters"],1):
                (out/f"ai_chapter_{i}.snbt").write_text(build_chapter(ch,i),encoding="utf-8")
                self.log(f"Quest draft written: ai_chapter_{i}.snbt")
            self.log("FTB Quests output is a draft; validate against the installed FTB Quests version in-game.")
        self.progress(100,100,"Complete. Review the manifest and test the Prism instance.")
        self.log("Done. Review the manifest and test the Prism instance.")
