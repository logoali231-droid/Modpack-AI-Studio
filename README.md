# Modpack AI Studio

**Free, local-first Minecraft modpack and quest generator inspired by Modbot.gg's describe → resolve → install workflow.** Independent project, not affiliated with Modbot.gg.

## Features
- Linux Mint desktop GUI (PySide6).
- Natural-language modpack design using local Ollama, OpenAI, or Google Gemini.
- **AI-selected Minecraft version:** enabled by default. Describe the gameplay and mod requirements; the AI recommends a stable Minecraft release, and the app checks that it is a recognized release before searching for files. You can disable this and enter a version manually.
- Modrinth project/version lookup for Minecraft + Forge/Fabric/NeoForge/Quilt.
- Required dependency resolution and JAR hash verification.
- Installs into an existing Prism Launcher instance, with optional mods-folder backup.
- Generates a three-chapter quest campaign as a native Minecraft datapack using the built-in Advancements screen. No FTB Quests or other quest mod is required.
- API keys stored in the Linux desktop keyring, never in the repository.

## How AI version selection works
The app first asks the selected AI provider to choose a Minecraft Java release based on your prompt. It then validates that release against Modrinth's public list of released game versions. Only after validation does it ask the AI to design the mod list for that exact version and loader. Each candidate mod is then checked against the selected Minecraft version and loader before download. If the AI proposes an unknown or non-release version, generation stops before installing anything. The Activity log explains the choice, and the manifest records the chosen version and rationale.

The AI chooses the Minecraft version, while the user still chooses the modloader. If your prompt names a specific version or a mod with a known version requirement, the AI is instructed to respect it. Compatibility is checked per project, but this does not guarantee that every mod works conflict-free with every other mod.

## Free by design
No subscription, credits, hosted backend, or app fee. For AI with no API bill, install [Ollama](https://ollama.com):
```bash
ollama pull qwen2.5:3b
```
Cloud providers are optional and may charge for API usage. Modrinth downloads use its public API.

## Install on Linux Mint
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
git clone https://github.com/logoali231-droid/Modpack-AI-Studio.git
cd Modpack-AI-Studio
chmod +x launch.sh
./launch.sh
```
Select Ollama (local, free), model `qwen2.5:3b`, and your modloader. First let the AI choose the Minecraft version, create a matching Prism instance, then select its folder. If you already have a world save, optionally select the world folder (the folder containing `level.dat`) so the app can install the quest datapack directly into it.

## Current scope and caveats
This is an early Modrinth-first desktop application, not a feature-complete Modbot.gg clone. CurseForge, shader/resource-pack management, automatic loader installation, visual dependency graphs, and one-click launching are not included yet. AI suggestions can conflict despite version filtering. The built-in quest system currently uses vanilla item-inventory objectives, native advancements, and loot-table rewards. It deliberately uses vanilla item IDs only, avoiding invalid guessed mod item IDs. If you select a world folder, the app installs the datapack into that world's `datapacks` directory. Otherwise it creates `Modpack_AI_Quests.zip` in the Prism Minecraft directory; copy that ZIP into the target world's `datapacks` folder. Enter the world or run `/reload`, then press `L` to open the Advancements screen. This first version uses Minecraft's native Advancements UI, not a separate custom quest-book screen. Back up your instance and close Minecraft before installing mods.

## License
MIT. Minecraft is a trademark of Mojang Studios. Modrinth, CurseForge, Prism Launcher, Ollama, OpenAI, Gemini, and Modbot.gg belong to their respective owners. No affiliation or endorsement is implied.
