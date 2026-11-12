from pathlib import Path
import json, shutil, datetime, re

from .llm import LLMClient
from .modrinth import Modrinth
from .curseforge import CurseForge
from .quests import build_datapack, pack_format_for, validate_campaign
from .prompts import VERSION_SYSTEM, modpack_system, SELECTION_SYSTEM, QUEST_SYSTEM


class ModpackPipeline:
    def __init__(self, cfg, log, progress=None):
        self.c, self.log = cfg, log
        self.progress_cb = progress or (lambda value, maximum, message: None)
        self.llm = LLMClient(
            cfg["provider"], cfg.get("api_key", ""), cfg["model"], log,
            cfg.get("ollama_url", "http://localhost:11434")
        )
        self.api = (
            CurseForge(log, cfg.get("curseforge_key", ""))
            if cfg.get("catalog") == "CurseForge" else Modrinth(log)
        )

    def progress(self, value, maximum, message):
        self.progress_cb(value, maximum, message)

    def minecraft_dir(self):
        root = Path(self.c["instance"]).expanduser().resolve()
        # Prism stores game files in instance/minecraft, even before mods/config exist.
        for path in (root / "minecraft", root / ".minecraft", root):
            if path.is_dir() and (
                path.name in ("minecraft", ".minecraft")
                or (path / "mods").exists() or (path / "config").exists()
            ):
                return path
        raise ValueError("Could not identify the Minecraft directory in this Prism instance.")

    def prism_minecraft_version(self):
        """Read the actual Minecraft version from Prism metadata, never infer it from the folder name."""
        root = Path(self.c["instance"]).expanduser().resolve()
        metadata = root / "mmc-pack.json"
        if not metadata.is_file():
            raise ValueError(
                "This folder has no mmc-pack.json. Select the Prism instance root folder, "
                "not its minecraft subfolder."
            )
        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read Prism instance metadata: {exc}") from exc
        for component in data.get("components", []):
            if component.get("uid") == "net.minecraft":
                version = str(component.get("version", "")).strip()
                if version:
                    return version
        raise ValueError("Prism metadata does not contain a net.minecraft component/version.")

    def select_minecraft_version(self, concept, fallback):
        """Ask the AI for a target release, then validate it against known released versions."""
        explicit = re.search(r"(?<!\d)(1\.\d{1,2}(?:\.\d{1,2})?)(?!\d)", concept)
        versions = Modrinth(self.log).game_versions()
        if explicit:
            selected = explicit.group(1)
            if selected not in versions:
                raise ValueError(
                    f"Prompt explicitly requests Minecraft {selected}, "
                    "but Modrinth does not list it as a release."
                )
            reason = "Explicitly requested in the modpack prompt; automatic selection did not override it."
            self.log(f"Using explicitly requested Minecraft version {selected}.")
            return selected, reason

        self.log("AI: choosing a Minecraft release based on your modpack description…")
        raw = self.llm.text(
            VERSION_SYSTEM,
            "Modpack concept and requirements:\n" + concept
            + "\nChoose the best Minecraft Java release for this specific pack. Return JSON only."
        )
        choice = self.llm.json_from(raw)
        if not isinstance(choice, dict):
            raise ValueError("AI version selection was not a JSON object.")
        selected = str(choice.get("minecraft_version", "")).strip()
        if not selected:
            raise ValueError("AI did not return minecraft_version.")
        if selected not in versions:
            raise ValueError(
                f"AI selected Minecraft {selected}, but it is not a recognized release version. "
                "No files were downloaded. Disable automatic selection and choose a version manually."
            )
        reason = str(choice.get("reason", "No reason supplied.")).strip()
        self.log(f"AI selected Minecraft {selected}. Reason: {reason}")
        return selected, reason

    def prepare_version(self):
        """Phase 1: choose and validate the target release without requiring a Prism instance."""
        concept = str(self.c.get("prompt", "")).strip()
        if not concept:
            raise ValueError("Describe the modpack before choosing a Minecraft version.")
        fallback = str(self.c.get("version", "")).strip()
        if self.c.get("auto_version", True):
            self.progress(5, 100, "AI is choosing the Minecraft release…")
            version, reason = self.select_minecraft_version(concept, fallback)
        else:
            version = fallback
            if not version:
                raise ValueError("Enter a Minecraft version or enable AI selection.")
            known = Modrinth(self.log).game_versions()
            if version not in known:
                raise ValueError(f"Minecraft {version} is not listed as a released version.")
            reason = "Selected manually by the user."
        self.log(f"Target locked for the next step: Minecraft {version} ({self.c.get('loader', 'forge')}).")
        self.progress(100, 100, f"Version selected: Minecraft {version}. Waiting for your Prism instance.")
        return version, reason

    def discover_candidates(self, requirements, mc, loader):
        """Search the catalog, then retain only projects with a real compatible JAR."""
        queries = []
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            terms = requirement.get("search_terms", [])
            if isinstance(terms, str):
                terms = [terms]
            for term in terms:
                term = str(term).strip()
                if term and term.lower() not in {query.lower() for query in queries}:
                    queries.append(term)

        queries = queries[:12]
        if not queries:
            raise RuntimeError("The AI requirements plan did not contain usable catalog search terms.")

        candidate_meta = {}
        for index, query in enumerate(queries, 1):
            self.progress(
                25 + int(12 * (index - 1) / max(len(queries), 1)), 100,
                f"Searching {self.c.get('catalog', 'Modrinth')}: {query}"
            )
            self.log(f"Catalog search {index}/{len(queries)}: {query}")
            try:
                hits = self.api.search(query, mc, loader) or []
            except Exception as exc:
                self.log(f"Catalog search failed for '{query}': {exc}")
                continue

            # Keep a small, diverse pool. The AI will curate only after each project
            # has been resolved against the exact Minecraft release and loader.
            for hit in hits[:8]:
                project_id = str(hit.get("project_id") or hit.get("slug") or "").strip()
                if not project_id or project_id in candidate_meta:
                    continue
                candidate_meta[project_id] = {
                    "project_id": project_id,
                    "name": str(hit.get("name") or project_id),
                    "description": str(hit.get("description") or "")[:350],
                    "categories": hit.get("categories") or [],
                    "downloads": hit.get("downloads", 0),
                }
                if len(candidate_meta) >= 36:
                    break
            if len(candidate_meta) >= 36:
                break

        if not candidate_meta:
            raise RuntimeError(
                f"The {self.c.get('catalog', 'catalog')} search returned no candidates "
                f"for Minecraft {mc}/{loader}."
            )

        verified = {}
        total = len(candidate_meta)
        for index, (project_id, metadata) in enumerate(candidate_meta.items(), 1):
            self.progress(
                37 + int(11 * (index - 1) / max(total, 1)), 100,
                f"Verifying candidate {index} of {total}: {metadata['name']}"
            )
            try:
                item = self.api.resolve(project_id, mc, loader)
            except Exception as exc:
                self.log(f"Candidate rejected: {metadata['name']} ({project_id}): {exc}")
                continue
            if not item or not item.get("project_id") or not item.get("url"):
                continue
            metadata["project_id"] = str(item["project_id"])
            verified[metadata["project_id"]] = {"metadata": metadata, "item": item}
            self.log(f"Verified candidate: {metadata['name']} ({metadata['project_id']})")

        return verified

    def select_candidates(self, verified, concept, mc, loader, catalog):
        """Ask the model to select from verified IDs only; never accept invented IDs."""
        if not verified:
            raise RuntimeError(
                f"No compatible {catalog} JARs found for Minecraft {mc}/{loader}. "
                "The catalog search found no projects with downloadable files."
            )

        candidates = [
            {
                "project_id": project_id,
                "name": entry["metadata"]["name"],
                "description": entry["metadata"]["description"],
                "categories": entry["metadata"]["categories"],
                "downloads": entry["metadata"]["downloads"],
            }
            for project_id, entry in verified.items()
        ]
        self.log(f"{len(candidates)} real projects have compatible files. Asking the AI to curate them.")
        self.progress(49, 100, f"Curating {len(candidates)} verified catalog candidates…")
        selection_input = (
            f"FIXED TARGET\nMinecraft Java: {mc}\nModloader: {loader}\nCatalog: {catalog}\n\n"
            f"USER'S MODPACK BRIEF:\n{concept}\n\n"
            "VERIFIED CANDIDATES (select only these exact project_id values):\n"
            + json.dumps(candidates, ensure_ascii=False)
        )
        raw = self.llm.text(SELECTION_SYSTEM, selection_input)
        data = self.llm.json_from(raw)
        selections = data.get("selections") if isinstance(data, dict) else None
        if not isinstance(selections, list):
            raise ValueError("AI did not return a selections array for the verified catalog candidates.")

        selected = {}
        for selection in selections:
            if not isinstance(selection, dict):
                continue
            project_id = str(selection.get("project_id", "")).strip()
            if project_id not in verified:
                if project_id:
                    self.log(f"Rejected AI selection with unknown project ID: {project_id}")
                continue
            selected[project_id] = verified[project_id]["item"]

        if not selected:
            raise RuntimeError(
                "The AI did not select any of the verified catalog candidates. "
                "No mods were downloaded."
            )
        self.log(f"AI selected {len(selected)} verified projects.")
        return selected

    def run(self):
        self.progress(0, 100, "Preparing your modpack…")
        mc, loader, concept = self.c["version"], self.c["loader"], self.c["prompt"]
        auto_version = bool(self.c.get("auto_version", False))
        if self.c.get("version_preselected"):
            version_reason = str(self.c.get("version_reason", "Selected in the preparation step."))
            auto_version = self.c.get("version_selection", "manual") == "ai"
        elif auto_version:
            self.progress(3, 100, "Choosing a Minecraft release…")
            mc, version_reason = self.select_minecraft_version(concept, mc)
        else:
            version_reason = "Selected manually by the user."

        # A Prism instance is tied to one Minecraft release. Refuse mismatches
        # before searching, backing up, creating folders, or downloading files.
        prism_mc = self.prism_minecraft_version()
        if prism_mc != mc:
            raise ValueError(
                f"Version mismatch: this Prism instance is Minecraft {prism_mc}, "
                f"but the modpack target is Minecraft {mc}. No files were installed. "
                "Choose a Prism instance for the target version, or set the target "
                f"version to {prism_mc}."
            )
        self.log(f"Prism instance verified: Minecraft {prism_mc}.")

        # Validate the optional world destination before any mod files are changed.
        world_value = str(self.c.get("world_path", "")).strip()
        if self.c.get("quests"):
            # Fail before mod discovery/download if this release has no verified
            # native-advancement datapack schema adapter yet.
            pack_format_for(mc)
        if self.c.get("quests") and world_value:
            world_root = Path(world_value).expanduser().resolve()
            if not world_root.is_dir() or not (world_root / "level.dat").is_file():
                raise ValueError(
                    "The selected Minecraft world folder is invalid. Choose the world folder "
                    "that contains level.dat, or leave the field empty to create a datapack ZIP."
                )

        catalog = self.c.get("catalog", "Modrinth")
        self.progress(10, 100, f"Planning gameplay requirements for Minecraft {mc}…")
        self.log(f"1/4 · Planning gameplay requirements for {catalog} on Minecraft {mc}…")
        plan_input = (
            f"FIXED TARGET\nMinecraft Java: {mc}\nModloader: {loader}\nCatalog: {catalog}\n\n"
            f"USER'S MODPACK BRIEF (preserve its constraints):\n{concept}\n\n"
            "Describe gameplay requirements and catalog search terms. Do not name mods. Return JSON only."
        )
        raw_plan = self.llm.text(modpack_system(catalog), plan_input)
        plan = self.llm.json_from(raw_plan)
        requirements = plan.get("requirements") if isinstance(plan, dict) else None
        if not isinstance(requirements, list) or not requirements:
            raise ValueError("AI did not return a non-empty requirements array.")
        requirements = requirements[:8]
        summary = str(plan.get("design_summary", "")).strip()
        self.log(f"AI defined {len(requirements)} gameplay requirements.")
        if summary:
            self.log(f"Design: {summary}")

        self.progress(25, 100, "Discovering real catalog projects…")
        self.log(f"2/4 · Searching and verifying {catalog} candidates…")
        verified = self.discover_candidates(requirements, mc, loader)
        selected = self.select_candidates(verified, concept, mc, loader, catalog)

        # Resolve the full required-dependency graph before touching the instance.
        # A pack with a missing required library must never be partially installed.
        queue = list((project_id, item) for project_id, item in selected.items())
        resolved = {}
        seen = set()
        unresolved_required = []
        while queue:
            project_id, item = queue.pop(0)
            project_id = str(project_id)
            if project_id in seen:
                continue
            seen.add(project_id)
            if item is None:
                try:
                    item = self.api.resolve(project_id, mc, loader)
                except Exception as exc:
                    self.log(f"Could not resolve required dependency {project_id}: {exc}")
                    unresolved_required.append(project_id)
                    continue
            if not item:
                self.log(f"Required dependency has no compatible file: {project_id}")
                unresolved_required.append(project_id)
                continue
            resolved[str(item["project_id"])] = item
            for dependency in item.get("dependencies", []):
                if dependency.get("dependency_type") == "required":
                    dependency_id = dependency.get("project_id")
                    if dependency_id and str(dependency_id) not in seen:
                        queue.append((str(dependency_id), None))

        if unresolved_required:
            missing = ", ".join(sorted(set(unresolved_required)))
            raise RuntimeError(
                "Installation cancelled before downloading: required dependencies "
                f"have no compatible {mc}/{loader} file: {missing}. "
                "Choose another Minecraft release or remove the mod that requires them."
            )
        if not resolved:
            raise RuntimeError(f"No compatible {catalog} files found for Minecraft {mc}/{loader}.")
        self.log(f"Selected {len(selected)} projects; {len(resolved)} including required dependencies.")
        self.progress(50, 100, f"{len(resolved)} compatible projects verified. Preparing installation…")

        mcdir = self.minecraft_dir()
        modsdir = mcdir / "mods"
        modsdir.mkdir(parents=True, exist_ok=True)
        self.log("3/4 · Installing verified JAR files…")
        if self.c.get("backup") and any(modsdir.iterdir()):
            backup = modsdir.with_name("mods.backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
            shutil.copytree(modsdir, backup)
            self.log(f"Backup created: {backup}")

        installed, failed = [], []
        total_downloads = len(resolved)
        for download_index, item in enumerate(resolved.values(), 1):
            self.progress(
                50 + int(35 * (download_index - 1) / max(total_downloads, 1)), 100,
                f"Installing mod {download_index} of {total_downloads}: {item['name']}"
            )
            try:
                path = self.api.download(item, modsdir)
                installed.append({
                    "name": item["name"],
                    "project_id": item["project_id"],
                    "version_id": item["version_id"],
                    "file": path.name,
                })
            except Exception as exc:
                failed.append({"file": item["name"], "error": str(exc)})
                self.log(f"Download failed: {item['name']}: {exc}")

        manifest = {
            "app": "Modpack AI Studio",
            "minecraft": mc,
            "minecraft_version_selection": "ai" if auto_version else "manual",
            "minecraft_version_reason": version_reason,
            "loader": loader,
            "catalog": catalog,
            "concept": concept,
            "design_summary": summary,
            "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "selected_project_ids": list(selected.keys()),
            "installed": installed,
            "failed": failed,
        }
        (mcdir / "modpack-ai-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.log(f"Installed {len(installed)} files; {len(failed)} failed. Manifest saved.")
        self.progress(88, 100, "Mod installation finished.")

        quest_status = {"status": "disabled"}
        if self.c.get("quests"):
            quest_status = {"status": "failed", "error": "Quest generation did not complete."}
            self.progress(0, 0, "AI is generating your native three-chapter quest campaign…")
            self.log("4/4 · Designing a native Minecraft advancement quest campaign…")
            self.log("Quest generation can take a while on a local model. Waiting for the AI response…")
            names = ", ".join(item["name"] for item in installed)
            quest_input = f"Concept: {concept}\nMinecraft {mc} {loader}. Installed mods: {names}"
            try:
                raw_quests = self.llm.text(QUEST_SYSTEM, quest_input)
                self.progress(90, 100, "AI response received. Validating quest campaign…")
                try:
                    campaign = validate_campaign(self.llm.json_from(raw_quests))
                except (ValueError, TypeError, KeyError) as first_error:
                    self.log(f"Quest response was invalid: {first_error}. Requesting one repair attempt…")
                    repair_input = (
                        f"ORIGINAL REQUEST:\n{quest_input}\n\n"
                        f"VALIDATION ERROR:\n{first_error}\n\n"
                        "PREVIOUS AI RESPONSE (repair this; do not start over):\n"
                        f"{raw_quests}\n\n"
                        "Return a corrected JSON object with exactly three chapters. "
                        "Each chapter must contain at least three quests, and each quest "
                        "must contain at least one valid item task. Return JSON only."
                    )
                    repaired = self.llm.text(
                        QUEST_SYSTEM + "\nYou are repairing a failed response. Follow the schema exactly.",
                        repair_input
                    )
                    campaign = validate_campaign(self.llm.json_from(repaired))

                # Build a self-contained vanilla datapack. No quest mod is required.
                datapack_files = build_datapack(campaign, mc)
                import zipfile
                archive = mcdir / "Modpack_AI_Quests.zip"
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as pack:
                    for relative_path, content in datapack_files.items():
                        pack.writestr(relative_path, content)

                world_value = str(self.c.get("world_path", "")).strip()
                installed_to_world = False
                if world_value:
                    world_root = Path(world_value).expanduser().resolve()
                    if not world_root.is_dir() or not (world_root / "level.dat").is_file():
                        raise ValueError(
                            "The selected Minecraft world folder is invalid. Choose the world folder "
                            "that contains level.dat, or leave the field empty to create a datapack ZIP."
                        )
                    datapacks_dir = world_root / "datapacks"
                    datapacks_dir.mkdir(parents=True, exist_ok=True)
                    destination = datapacks_dir / archive.name
                    shutil.copy2(archive, destination)
                    installed_to_world = True
                    self.log(f"Custom quest datapack installed into world: {destination}")
                else:
                    destination = archive
                    self.log(f"Custom quest datapack ZIP created: {archive}")
                    self.log(
                        "To use it, copy this ZIP into your world's datapacks folder, then run /reload "
                        "or re-enter the world. Press L in-game to open the Advancements quest screen."
                    )

                quest_status = {
                    "status": "generated",
                    "system": "minecraft_advancements_datapack",
                    "file": archive.name,
                    "installed_to_world": installed_to_world,
                    "destination": str(destination),
                    "access": "Press L (Advancements) in-game."
                }
                self.log(
                    "Native quest campaign generated. It uses Minecraft's built-in Advancements screen; "
                    "FTB Quests and other quest mods are not required."
                )
            except Exception as exc:
                quest_status = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                self.log(
                    "WARNING · Mods were installed successfully, but quest generation failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        manifest["quests"] = quest_status
        (mcdir / "modpack-ai-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        self.progress(100, 100, "Mod installation complete. Review the manifest and test the Prism instance.")
        self.log("Done. Review the manifest and test the Prism instance.")
        if quest_status["status"] == "failed":
            return {
                "success": True,
                "quests_failed": True,
                "message": "Mods installed successfully, but quest generation failed. See the Activity log and manifest."
            }
        return {
            "success": True,
            "quests_failed": False,
            "message": "Modpack installation completed. Review the manifest and validate the instance in Prism."
        }
