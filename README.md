# Modpack AI Studio

**Free, local-first Minecraft modpack and quest generator inspired by Modbot.gg's describe → resolve → install workflow.** Independent project, not affiliated with Modbot.gg.

## Features
- Linux Mint desktop GUI (PySide6).
- Natural-language modpack design using local Ollama, OpenAI, or Google Gemini.
- AI-selected Minecraft version, validated against released game versions.
- Modrinth and CurseForge project/version lookup for Minecraft + Forge/Fabric/NeoForge/Quilt.
- Required dependency graph resolution from catalog metadata.
- **JAR-internal dependency verification:** inspects Forge/NeoForge `mods.toml`, Fabric/Quilt metadata, and legacy `mcmod.info` IDs before installation. Downloads are staged and checked before being copied into the Prism instance.
- Installs into an existing Prism Launcher instance, with optional mods-folder backup.
- Progression-sized quest campaigns generated as native Minecraft datapacks. Chapter count is no longer fixed at three. No FTB Quests or other quest mod is required.
- Optional Playwright browser research can collect public documentation snippets for the local model. Browser text is untrusted context, never proof of compatibility.
- API keys stored in the Linux desktop keyring, never in the repository.

## Optional Playwright browser research
The normal app does not need Playwright. To enable the optional browser-research checkbox:
```bash
source .venv/bin/activate
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
```
The app performs bounded DuckDuckGo searches and reads a small number of pages. It does not give the model unrestricted browser control. Page content may be inaccurate or malicious, so it is treated as untrusted context. Catalog APIs and downloaded JAR metadata remain authoritative. Browser research is off by default and can be slow.

## Dependency verification
Catalog APIs expose dependency relationships, but their project IDs are not always the same as the internal mod IDs checked by Forge/Fabric. The verifier inspects the actual downloaded archives and checks mandatory internal mod IDs across the combined existing + staged mod set. This catches cases such as a mod declaring a required `selene` mod ID even when the catalog dependency graph did not reveal it. The verifier also reports duplicate IDs and unreadable archives. It does not yet prove every semantic compatibility rule, evaluate all Maven version-range expressions, or guarantee that two mods cannot conflict at runtime.

## Free by design
No subscription, credits, hosted backend, or app fee. For AI with no API bill, install [Ollama](https://ollama.com):
```bash
ollama pull qwen2.5:3b
```
Cloud providers are optional and may charge for API usage. Modrinth downloads use its public API. CurseForge requires the user's own API key.

## Install on Linux Mint
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
git clone https://github.com/logoali231-droid/Modpack-AI-Studio.git
cd Modpack-AI-Studio
chmod +x launch.sh
./launch.sh
```
Select Ollama (local, free), model `qwen2.5:3b`, and your modloader. First let the AI choose the Minecraft version, create a matching Prism instance, then select its folder. If you already have a world save, optionally select the world folder containing `level.dat` to install the quest datapack directly.

## Quest system scope
The model chooses the number of chapters based on the requested progression. The validator accepts 1-100 chapters and 1-20 quests per chapter as safety limits, not design targets. Quest objectives and rewards currently use vanilla item IDs only. Datapacks support the verified legacy advancement/item schema for Minecraft 1.13 through 1.20.4; unsupported newer schemas are rejected before mod installation. If no world is selected, the app creates `Modpack_AI_Quests.zip` in the Prism Minecraft directory; copy it into the target world's `datapacks` folder. Enter the world or run `/reload`, then press `L`. This uses Minecraft's native Advancements UI, not a separate custom quest-book screen.

## AI Structure Designer (first version)

The **Structure Designer** tab turns a natural-language building request into a compact AI blueprint, then uses a deterministic procedural builder to create the actual block layout. The model does not emit thousands of block coordinates. It chooses bounded dimensions, building type, floors, roof style, room types, features, and materials from a strict whitelist; Python validates the blueprint and constructs the geometry.

The first exporter writes a gzip-compressed vanilla Minecraft structure NBT file for **Minecraft Java 1.16.5 only** (DataVersion 2586). Current limits are 9–25 blocks wide/deep, 1–4 floors, up to 60,000 blocks, and a verified vanilla material palette. The generated file can be imported with a compatible structure tool or placed using Minecraft's Structure Block. The app does not yet place structures automatically or inject them into natural chunk generation. It also does not yet add modded blocks, loot-table contents, entities, or custom structure-generation rules. The optional cellar feature currently represents a cellar access detail, not a fully excavated underground dungeon.

To use it, open **Structure Designer**, describe a building, keep the target at Minecraft 1.16.5, choose an output .nbt path, and click **Generate custom structure with AI**. It uses the same configured AI provider/model as the rest of the app. With Ollama, no cloud API is required.

## Current scope and caveats
This remains an early desktop application, not a feature-complete Modbot.gg clone. AI selection and browser research do not guarantee conflict-free gameplay. The dependency verifier checks declared required internal mod IDs, but version-range evaluation and all loader-specific edge cases are not yet complete. Back up your instance and close Minecraft before installing mods.

## License
MIT. Minecraft is a trademark of Mojang Studios. Modrinth, CurseForge, Prism Launcher, Ollama, OpenAI, Gemini, and Modbot.gg belong to their respective owners. No affiliation or endorsement is implied.


## Error Auto Fix and persistent lessons
The Error Auto Fix tab sends the selected log to the configured model for diagnosis. It reports evidence, likely causes, safe repair steps, and a code-change suggestion; it does not silently edit the project or delete files. Each diagnosis is stored locally under `~/.local/share/modpack-ai-studio/error_lessons.json`, with a readable companion `error_lessons.md`. New lessons start as unverified. Only lessons explicitly confirmed by the user are reused as context in later modpack planning, quest planning, and error analyses. This is retrieval-based memory, not model-weight training.

If quest generation fails after mods have been installed, use **Retry quest generation only** in the Error Auto Fix tab. It reads the existing Prism manifest and regenerates the datapack without searching for or reinstalling mods.


## Local Mod Library (Modrinth + CurseForge)
The **Mod Library** tab maintains a local SQLite index at `~/.local/share/modpack-ai-studio/mods.sqlite3` (or `$XDG_DATA_HOME/modpack-ai-studio/mods.sqlite3`). Search and filter cached projects by text, Minecraft version, loader, and source. Use **Sync from selected catalog** to search the official Modrinth or CurseForge catalog and cache up to 20 matching projects, including full descriptions where the provider API exposes them. Normal modpack generation also caches catalog summaries and enriches selected projects.

The database stores project IDs, names, summaries, descriptions, authors, categories, Minecraft versions, loaders, download counts, icons, links, licenses where available, and sync timestamps. It is an incremental local cache, not a full mirror of every project on either platform. Repeat syncs to refresh metadata or broaden coverage with different search terms. Modrinth metadata is available through its public API. CurseForge requires your own API key; the app stores it in the desktop keyring and never in SQLite or the repository. Compatibility for installation is still verified against actual downloadable files before a mod can be selected or installed; database tags are discovery metadata, not installation proof.
