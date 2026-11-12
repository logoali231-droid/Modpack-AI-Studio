# Modpack AI Studio

**Free, local-first Minecraft modpack and quest generator inspired by Modbot.gg's describe → resolve → install workflow.** Independent project, not affiliated with Modbot.gg.

## Features
- Linux Mint desktop GUI (PySide6).
- Natural-language modpack design using local Ollama, OpenAI, or Google Gemini.
- Modrinth project/version lookup for Minecraft + Forge/Fabric/NeoForge/Quilt.
- Required dependency resolution and JAR hash verification.
- Installs into an existing Prism Launcher instance, with optional mods-folder backup.
- Generates a three-chapter FTB Quests campaign draft and an install manifest.
- API keys stored in the Linux desktop keyring, never in the repository.

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
Select Ollama (local, free), model `qwen2.5:3b`, your Minecraft version/loader, and the Prism instance folder.

## Current scope and caveats
This is an early Modrinth-first desktop application, not a feature-complete Modbot.gg clone. CurseForge, shader/resource-pack management, automatic loader installation, visual dependency graphs, and one-click launching are not included yet. AI suggestions can conflict despite version filtering. FTB Quests output is a draft: schema varies by FTB Quests version and must be validated in-game before distribution. Back up your instance and close Minecraft before installing mods.

## License
MIT. Minecraft is a trademark of Mojang Studios. Modrinth, CurseForge, Prism Launcher, Ollama, OpenAI, Gemini, and Modbot.gg belong to their respective owners. No affiliation or endorsement is implied.
