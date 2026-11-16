"""Popula o banco de mods chamando sync_catalog em uma lista curada de buscas.

Uso (a partir da raiz do projeto, com o .venv ativo):
    python training/scripts/sync_mods.py

Não precisa do Ollama rodando — o sync só fala com a API da Modrinth/CurseForge.
"""

import sys
from pathlib import Path

# Permite importar `app.*` quando o script é chamado de training/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.orchestrator import ModpackPipeline


# ========== Configuração ==========
MC_VERSION = "1.20.1"   # troque para "1.19.4" se seu modpack alvo for 1.19.4
LOADER     = "forge"    # "forge" | "fabric" | "neoforge" | "quilt"
SOURCE     = "modrinth" # "modrinth" | "curseforge" (curseforge exige API key)

# Cobertura por categoria — o guia original prevê estes temas nos datasets.
QUERIES = [
    # Primitive survival
    "terrafirmacraft",
    "primitive survival",
    "primal",
    "tfc",

    # Technology
    "create",
    "thermal",
    "mekanism",
    "immersive engineering",
    "industrial foregoing",
    "gregtech",
    "pneumaticcraft",

    # Automation / storage
    "applied energistics",
    "refined storage",
    "pipez",
    "pretty pipes",
    "modular routers",

    # Exploration
    "twilight forest",
    "alex mobs",
    "yungs",
    "aether",
    "blue skies",
    "betterend",

    # Farming / food
    "farmers delight",
    "croptopia",
    "pams harvestcraft",

    # Utility / UI
    "jei",
    "jade",
    "journeymap",
    "curios",
    "ftb quests",

    # Combat / hardcore
    "apotheosis",
    "epic fight",
    "ice and fire",

    # Magic
    "botania",
    "ars nouveau",
    "blood magic",
]
# ==================================


def main() -> int:
    # Config mínima só para o construtor do pipeline. Nada disso é usado no sync.
    cfg = {
        "provider":       "ollama",
        "model":          "qwen2.5:3b",
        "api_key":        "",
        "ollama_url":     "http://localhost:11434",
        "catalog":        "Modrinth",
        "curseforge_key": "",
    }

    pipeline = ModpackPipeline(cfg, log=print, progress=None)

    total_saved  = 0
    total_failed = 0

    for i, query in enumerate(QUERIES, 1):
        print(f"\n[{i}/{len(QUERIES)}] '{query}' ({SOURCE} · {MC_VERSION} · {LOADER})")
        try:
            result = pipeline.sync_catalog(query, SOURCE, MC_VERSION, LOADER)
            total_saved  += result["saved"]
            total_failed += result["failures"]
        except Exception as exc:
            print(f"  ERRO: {exc}")

    stats = pipeline.database.stats()
    print("\n========== RESUMO ==========")
    print(f"Salvos nesta execução:  {total_saved}")
    print(f"Falhas nesta execução:  {total_failed}")
    print(f"Stats do banco:         {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())