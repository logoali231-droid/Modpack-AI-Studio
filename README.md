Vou atualizar o `README.md` para incluir todo o pipeline de treinamento de IA que construímos, mantendo o conteúdo original da aplicação e adicionando a nova seção de forma clara. Abaixo está o conteúdo completo do README atualizado, pronto para ser copiado e colado no repositório.

---

# Modpack AI Studio

**Free, local-first Minecraft modpack and quest generator inspired by Modbot.gg's describe → resolve → install workflow.** Independent project, not affiliated with Modbot.gg.

## Features

* Linux Mint desktop GUI (PySide6).
* Natural-language modpack design using local Ollama, OpenAI, or Google Gemini.
* AI-selected Minecraft version, validated against released game versions.
* Modrinth and CurseForge project/version lookup for Minecraft + Forge/Fabric/NeoForge/Quilt.
* Required dependency graph resolution from catalog metadata.
* **JAR-internal dependency verification:** inspects Forge/NeoForge `mods.toml`, Fabric/Quilt metadata, and legacy `mcmod.info` IDs before installation. Downloads are staged and checked before being copied into the Prism instance.
* Installs into an existing Prism Launcher instance, with optional mods-folder backup.
* Progression-sized quest campaigns generated as native Minecraft datapacks. Chapter count is no longer fixed at three. No FTB Quests or other quest mod is required.
* Optional Playwright browser research can collect public documentation snippets for the local model. Browser text is untrusted context, never proof of compatibility.
* API keys stored in the Linux desktop keyring, never in the repository.
* **Local Mod Library (Modrinth + CurseForge):** maintains a local SQLite index at `~/.local/share/modpack-ai-studio/mods.sqlite3` (or `$XDG_DATA_HOME/modpack-ai-studio/mods.sqlite3`). Search and filter cached projects by text, Minecraft version, loader, and source. Use **Sync from selected catalog** to search the official Modrinth or CurseForge catalog and cache up to 20 matching projects, including full descriptions where the provider API exposes them. Normal modpack generation also caches catalog summaries and enriches selected projects.
* **Error Auto Fix and persistent lessons:** sends selected logs to the configured model for diagnosis. Reports evidence, likely causes, safe repair steps, and a code-change suggestion; does not silently edit the project or delete files. Each diagnosis is stored locally under `~/.local/share/modpack-ai-studio/error_lessons.json`. Only lessons explicitly confirmed by the user are reused as context in later modpack planning, quest planning, and error analyses.
* **AI Structure Designer:** supports single buildings and multi-building settlements. Qwen creates a compact architectural plan; Python validates it, builds the block geometry, and exports one vanilla structure NBT file for Minecraft Java 1.16.5 (DataVersion 2586). Includes interactive isometric 3D preview, modded block palette support, and one constrained repair attempt on invalid JSON.

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
sudo apt install -y python3 python3-venv python3-pip git
git clone https://github.com/logoali231-droid/Modpack-AI-Studio.git
cd Modpack-AI-Studio
chmod +x launch.sh
./launch.sh
```

Select Ollama (local, free), model `qwen2.5:3b`, and your modloader. First let the AI choose the Minecraft version, create a matching Prism instance, then select its folder. If you already have a world save, optionally select the world folder containing `level.dat` to install the quest datapack directly.

## Quest system scope

The model chooses the number of chapters based on the requested progression. The validator accepts 1-100 chapters and 1-20 quests per chapter as safety limits, not design targets. Quest objectives and rewards currently use vanilla item IDs only. Datapacks support the verified legacy advancement/item schema for Minecraft 1.13 through 1.20.4; unsupported newer schemas are rejected before mod installation. If no world is selected, the app creates `Modpack_AI_Quests.zip` in the Prism Minecraft directory; copy it into the target world's `datapacks` folder. Enter the world or run `/reload`, then press `L`. This uses Minecraft's native Advancements UI, not a separate custom quest-book screen.

## AI Structure Designer

The **Structure Designer** tab supports single buildings and multi-building settlements. Qwen creates a compact architectural plan; Python validates it, builds the block geometry, and exports one vanilla structure NBT file for **Minecraft Java 1.16.5** (DataVersion 2586). The model does not emit individual block coordinates.

### Current capabilities

* Single buildings: houses, keeps, towers, outposts and ruins, with multiple floors, rooms, roofs, balconies, windows and decoration.
* Settlements: 2–10 buildings in one combined structure, with optional roads, central well/plaza and palisade. Overlapping AI placements are automatically moved to the nearest available grid position when space permits.
* Underground dungeons: a real multi-room underground chamber with walls, corridors, barred cells, a ladder shaft, chest and spawner. The result reports the Structure Block Y offset (-7) needed to align the building's ground level with the placement point. This is geometry and vanilla block placement, not a custom loot table or configured mob-spawner payload.
* Modded block palette: scan a local Prism `minecraft/mods` folder for blockstate assets inside JARs, then use the suggested namespace:block IDs as material keys. Manual JSON palettes are also supported, e.g. `{"create_casing":"create:andesite_casing"}`. Discovery is based on JAR assets, not proof of runtime registration in the selected loader/version.
* Interactive isometric 3D preview: drag to rotate and use the mouse wheel to zoom. The preview samples up to 5,000 blocks for responsiveness; the exported NBT contains the complete structure.
* One constrained repair attempt when Qwen returns invalid JSON or a blueprint outside the safety rules.

### How to use

1. Open **Structure Designer** and describe a building or settlement.
2. Optionally provide a custom mod block palette as JSON. Vanilla materials are available without this.
3. Choose an output `.nbt` path and generate.
4. Inspect the 3D preview. Drag to rotate; scroll to zoom.
5. Copy the NBT file into the target world's `generated/minecraft/structures/` folder and load it with a Minecraft Structure Block, or use a compatible structure editor.

### Scope and safety

* The NBT exporter currently targets Minecraft Java 1.16.5 only. Other versions need their own DataVersion-aware export/compatibility work.
* Structure export is not natural chunk generation and does not install or build a Forge mod.
* Modded resource IDs are not verified against runtime registries. If a block is missing or its blockstate properties differ, Minecraft may substitute, reject or warn about it.
* The preview is an isometric voxel viewport, not a full Minecraft renderer. It does not simulate lighting, block models, fluids, redstone or collision.
* Dungeon chest/spawner blocks are placed, but no loot table or mob-spawner entity configuration is embedded.
* Maximum project size is 120,000 blocks; settlement footprint is limited to 96×96; a settlement may contain 2–10 buildings.

## Current scope and caveats

This remains an early desktop application, not a feature-complete Modbot.gg clone. AI selection and browser research can be wrong. The dependency verifier checks declared required internal mod IDs, but version-range evaluation and all loader-specific edge cases are not yet complete. Back up your instance and close Minecraft before installing mods.

## AI Training Pipeline (Experimental)

This repository now includes an **experimental AI training pipeline** designed to fine-tune a local Qwen model (e.g., `qwen2.5:3b`) specifically for Minecraft modpack design and quest generation. The pipeline is **local-first**, uses only free tools (Ollama, SQLite, Python), and is intended for users who want to specialize the model beyond generic instruction-following.

### Overview

The pipeline follows a **grounded generation** approach: every training example is anchored in the real mod catalog stored in the local SQLite database. This prevents the model from inventing mods and enforces logical Minecraft progression.

```
Modrinth/CurseForge  →  sync_mods.py  →  SQLite (mods.sqlite3)
                                     ↓
                          export_mods.py  →  mod_knowledge.jsonl (RAG source)
                                     ↓
                       generate_specs.py  →  specs_generated.json (100+ design briefs)
                                     ↓
                  build_modpack_dataset.py  →  modpack_design.jsonl (validated examples)
                                     ↓
                  build_quest_dataset.py    →  quest_generation.jsonl (FTB-style instructions)
                                     ↓
                         QLoRA fine-tuning  →  specialized Qwen model
```

### Directory structure

```
training/
├── scripts/
│   ├── sync_mods.py              # Populate SQLite from Modrinth (curated queries)
│   ├── export_mods.py            # Export mod table to JSONL for RAG
│   ├── generate_specs.py         # Generate design briefs from catalog statistics
│   ├── build_modpack_dataset.py  # Generate & validate modpack design examples
│   └── build_quest_dataset.py    # (Planned) Generate FTB-style quest instructions
├── data/
│   ├── raw/
│   │   └── mod_knowledge.jsonl   # Full mod catalog (RAG source)
│   └── processed/                # (Reserved for future splits)
├── datasets/
│   ├── specs_generated.json      # Auto-generated design briefs
│   ├── modpack_design.jsonl      # Validated training examples (modpack design)
│   ├── quest_generation.jsonl    # (Planned) FTB quest instructions
│   └── _failed_raw/              # Raw model outputs that failed validation (debug)
└── evaluation/                   # (Reserved for test prompts and metrics)
```

### Script reference

| Script | Purpose | Output |
|--------|---------|--------|
| `sync_mods.py` | Calls `sync_catalog` for a curated list of mod queries, populating the SQLite database with real mod metadata. | `~/.local/share/modpack-ai-studio/mods.sqlite3` |
| `export_mods.py` | Reads the `mods` table and writes a JSONL file with one mod per line. JSON columns are parsed into arrays. | `training/data/raw/mod_knowledge.jsonl` |
| `generate_specs.py` | Analyzes the catalog to produce design briefs (`SPECS`) with version, loader, theme, category, grind level, and focus. Uses round-robin to ensure diversity across themes. | `training/datasets/specs_generated.json` |
| `build_modpack_dataset.py` | For each spec, fetches a filtered set of real mods, prompts Ollama (with few-shot and hard Minecraft rules), and validates the JSON response. Only valid examples are written. | `training/datasets/modpack_design.jsonl` |
| `build_quest_dataset.py` | *(Planned)* Generates FTB Quests chapter instructions (title, description, icon, task, reward, dependencies, ftb_tip) using the same grounding approach. | `training/datasets/quest_generation.jsonl` |

### Validation rules

Both dataset generators apply **strict deterministic validators**:

* **Modpack design:**
  - `progression` must contain 4–6 verb phrases, each with ≥2 words.
  - `design_rules` must not mention any mod name.
  - `suggested_mods` must be a subset of the mods provided in the prompt.
  - Minecraft logic checks: wood → stone → iron → diamond → obsidian; no “craft flint” or “mine obsidian” without diamond.
* **Quest generation (planned):**
  - 3–8 quests per chapter.
  - First quest has `depends_on: []`; all others depend on at least one previous quest.
  - `icon` and `task.target` must contain a namespace (`mod:id`).
  - No mod names in descriptions; only in `task.target` / `reward.target`.
  - Same Minecraft logic checks.

### How to run (modpack dataset example)

```bash
# 1. Activate the virtual environment
source .venv/bin/activate

# 2. Populate the SQLite database (one-time or when refreshing)
python training/scripts/sync_mods.py

# 3. Export the catalog for RAG
python training/scripts/export_mods.py

# 4. Generate design briefs (100 specs, diverse themes)
python training/scripts/generate_specs.py --count 100

# 5. Generate and validate training examples
python training/scripts/build_modpack_dataset.py --fresh

# 6. Inspect the results
wc -l training/datasets/modpack_design.jsonl
head -n 1 training/datasets/modpack_design.jsonl | python -m json.tool
```

**Expected runtime:** With `qwen2.5:3b` on a mid-range CPU, ~55 seconds per example. 100 examples take ~90 minutes. The script uses append mode by default; use `--fresh` to restart from scratch.

### Model recommendations

| Model | RAM (Q4_K_M) | Quality | Recommendation |
|-------|--------------|---------|----------------|
| `qwen2.5:3b` | ~2 GB | Good for structure, weak on causal logic | **Default**; sufficient with strict validation |
| `qwen2.5:7b` | ~4.7 GB | Better logical consistency | Use if ≥6 GB RAM free; expect ~2× slower |
| `llama3.1:8b` | ~4.9 GB | Strong JSON adherence | Alternative to 7b |
| `gemma2:9b` | ~5.5 GB | Excellent reasoning | Heavy; use only with 8+ GB free |

**Note:** All models are pulled via Ollama. The pipeline never sends data to external APIs—everything runs locally.

### Fine-tuning (planned)

The generated datasets (`modpack_design.jsonl` and `quest_generation.jsonl`) are designed for **QLoRA fine-tuning** using Unsloth on Google Colab (free T4 GPU). The training script and evaluation harness are not yet included in this repository, but the data format is compatible with `SFTTrainer` from Hugging Face TRL (conversational `messages` array).

### Current status (as of November 2026)

* **Mod catalog:** ~450 real mods synced from Modrinth.
* **Specs:** 100 diverse design briefs generated (14–15 per theme).
* **Modpack dataset:** 84 validated examples (some specs skipped due to insufficient mods; some failed validation and were discarded).
* **Quest dataset:** Not yet generated (script planned).
* **Fine-tuning:** Not started.

### Why this pipeline exists

Generic LLMs, even large ones, often hallucinate mod names and violate Minecraft progression (e.g., “mine obsidian with a stone pickaxe”). By grounding every example in the **real catalog** and enforcing **hard logical rules**, the resulting specialized model can generate coherent, actionable modpack designs and quest outlines—saving hours of manual design work.

## License

MIT. Minecraft is a trademark of Mojang Studios. Modrinth, CurseForge, Prism Launcher, Ollama, OpenAI, Gemini, and Modbot.gg belong to their respective owners. No affiliation or endorsement is implied.
