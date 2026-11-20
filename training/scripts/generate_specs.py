"""generate_specs.py v3.0 — Gera SPECS do catálogo SQLite, com diversidade real.

Novidades v3.0 (vs v2):
- FIX: round-robin real entre temas (antes: 100% primitive survival)
- Balanceamento por (mc, loader) DENTRO de cada tema
- Focus com 13 templates (mod-anchored / constraint / pacing / narrative)
- min_mods configurável via --min-mods (default 10)
- Preview de distribuição + warning se algum tema estiver sub-representado
- Sumário por tema E por (mc, loader) no output final

Uso:
    python training/scripts/generate_specs.py --count 100
    python training/scripts/generate_specs.py --count 100 --min-mods 8 --seed 42
"""

import argparse
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

DB_PATH  = Path.home() / ".local" / "share" / "modpack-ai-studio" / "mods.sqlite3"
OUT_FILE = Path(__file__).resolve().parents[1] / "datasets" / "specs_generated.json"

# Tema → categorias, grind permitido, categorias proibidas (fit temático)
THEMES = {
    "primitive survival": {
        "categories": ["adventure", "worldgen", "food"],
        "grind": ["low"],
        "forbid": ["technology", "storage", "transportation", "management", "magic"],
    },
    "technology and automation": {
        "categories": ["technology", "storage", "transportation"],
        "grind": ["medium", "low"],
        "forbid": ["magic"],
    },
    "exploration and survival": {
        "categories": ["adventure", "worldgen", "magic"],
        "grind": ["medium"],
        "forbid": ["management"],
    },
    "low-grind progression": {
        "categories": ["utility", "equipment", "game-mechanics"],
        "grind": ["low"],
        "forbid": [],
    },
    "multiblock industry": {
        "categories": ["technology", "storage"],
        "grind": ["high"],
        "forbid": ["magic", "adventure", "decoration"],
    },
    "hardcore survival": {
        "categories": ["adventure", "worldgen", "mobs"],
        "grind": ["high"],
        "forbid": ["technology", "storage", "transportation", "magic", "decoration"],
    },
    "mixed gameplay": {
        "categories": ["technology", "magic", "adventure"],
        "grind": ["medium"],
        "forbid": [],
    },
}

# Templates de focus — mistura mod-anchored, constraint, pacing, narrative
FOCUS_TEMPLATES = [
    # A — mod-anchored (concreto)
    "{top} + {second} progression",
    "{top} early → {second} endgame",
    "{top}-centered with {second} as side path",
    "{top} core, {second} optional",
    # B — constraint-focused (espaço negativo)
    "no {cat2} content, only {cat} via {top}",
    "avoid {cat2} entirely, {top} as anchor",
    "{cat}-only, {top} primary",
    # C — pacing-focused
    "slow {cat} start, {top} unlocks mid-game",
    "{top} at endgame, {cat} grounded early",
    "tight pacing, {top} core",
    # D — narrative-focused
    "primitive start, {top} as breakthrough",
    "{top} as central tree, no shortcuts",
    # E — combo-focused
    "{top} + {second} + {cat} synergy",
]


def load_catalog():
    if not DB_PATH.exists():
        sys.exit(f"Banco não encontrado: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT name, categories, game_versions, loaders, downloads FROM mods"
    ).fetchall()
    conn.close()
    out = []
    for name, cats_j, vers_j, load_j, dl in rows:
        try:
            cats = json.loads(cats_j or "[]")
            vers = json.loads(vers_j or "[]")
            loads = json.loads(load_j or "[]")
        except json.JSONDecodeError:
            continue
        out.append({
            "name": name, "cats": cats, "versions": vers,
            "loaders": loads, "downloads": dl or 0,
        })
    return out


def popular_combos(mods, min_mods=10):
    c = Counter()
    for m in mods:
        for v in m["versions"]:
            for l in m["loaders"]:
                c[(v, l)] += 1
    return [(v, l, n) for (v, l), n in c.most_common() if n >= min_mods]


def top_in_category(mods, category, version, loader, n=3, forbid=()):
    matches = [
        x for x in mods
        if category in x["cats"]
        and version in x["versions"]
        and loader in x["loaders"]
        and not any(f in x["cats"] for f in forbid)
    ]
    matches.sort(key=lambda x: -x["downloads"])
    return matches[:n]


def make_focus(template, top, cats_cycle):
    cat = cats_cycle[0] if cats_cycle else "gameplay"
    cat2 = cats_cycle[1] if len(cats_cycle) > 1 else cat
    return template.format(
        top=top[0]["name"] if len(top) > 0 else "core mod",
        second=top[1]["name"] if len(top) > 1 else "vanilla",
        cat=cat,
        cat2=cat2,
    )


def build_theme_candidates(theme, meta, mods, combos):
    """Constrói candidatos balanceados por (mc, loader) — round-robin interno."""
    groups = defaultdict(list)
    for (mc, loader, _) in combos:
        for category in meta["categories"]:
            top = top_in_category(
                mods, category, mc, loader, n=3, forbid=meta["forbid"]
            )
            if len(top) < 3:            # precisa de ≥3 pra passar no build_modpack
                continue
            for template in FOCUS_TEMPLATES:
                focus = make_focus(template, top, meta["categories"])
                groups[(mc, loader)].append({
                    "mc": mc, "loader": loader, "theme": theme,
                    "category": category,
                    "grind": random.choice(meta["grind"]),
                    "focus": focus,
                })
    for g in groups.values():
        random.shuffle(g)
    # Round-robin interno: alterna (mc, loader) pra não enviesar por versão
    candidates = []
    while any(groups.values()):
        for key in list(groups.keys()):
            if groups[key]:
                candidates.append(groups[key].pop())
    return candidates


def generate(target_count=100, seed=42, min_mods=10):
    random.seed(seed)
    mods = load_catalog()
    combos = popular_combos(mods, min_mods=min_mods)

    print(f"Catálogo: {len(mods)} mods")
    print(f"Combos (versão+loader) com ≥{min_mods} mods: {len(combos)}")
    for (v, l, n) in combos[:10]:
        print(f"  {v:8s} {l:10s} → {n} mods")
    if not combos:
        sys.exit(f"Nenhum combo com ≥{min_mods} mods. Rode sync_mods.py primeiro.")

    # Construir candidatos por tema
    print("\nConstruindo candidatos por tema...")
    ideal = target_count / len(THEMES)
    candidates_by_theme = {}
    for theme, meta in THEMES.items():
        cand = build_theme_candidates(theme, meta, mods, combos)
        candidates_by_theme[theme] = cand
        status = "⚠️ " if len(cand) < ideal * 1.5 else "✅"
        print(f"  {status} {theme:30s} → {len(cand):3d} candidatos (precisa ~{ideal:.0f})")

    # Round-robin entre temas (um de cada, depois volta)
    specs, seen = [], set()
    theme_queue = {t: list(c) for t, c in candidates_by_theme.items()}
    theme_names = list(THEMES.keys())

    while len(specs) < target_count:
        progressed = False
        for theme in theme_names:
            if len(specs) >= target_count:
                break
            queue = theme_queue[theme]
            while queue:
                spec = queue.pop(0)
                key = (spec["theme"], spec["mc"], spec["loader"],
                       spec["category"], spec["focus"])
                if key in seen:
                    continue
                seen.add(key)
                specs.append(spec)
                progressed = True
                break
        if not progressed:
            print("⚠️  Todos os temas esgotados — alvo não atingido.")
            break

    return specs


def validate_distribution(specs):
    if not specs:
        return
    n = len(specs)
    ideal = n / len(THEMES)

    print("\nDistribuição por tema:")
    by_theme = Counter(s["theme"] for s in specs)
    for theme in THEMES:
        count = by_theme.get(theme, 0)
        pct = 100 * count / n
        status = "⚠️ " if count < ideal * 0.5 else "✅"
        print(f"  {status} {count:3d} ({pct:4.1f}%)  {theme}")

    print("\nDistribuição por (mc, loader):")
    by_combo = Counter((s["mc"], s["loader"]) for s in specs)
    for (mc, loader), count in by_combo.most_common():
        print(f"    {count:3d}  {mc} · {loader}")

    # Alerta se algum combo domina demais
    top_count = by_combo.most_common(1)[0][1]
    if top_count > n * 0.6:
        print(f"\n⚠️  Um único (mc, loader) tem >60% dos specs — considere rodar "
              f"sync_mods.py com mais versões/loaders.")


def main():
    parser = argparse.ArgumentParser(description="Gera SPECS do catálogo SQLite")
    parser.add_argument("--count", type=int, default=100, help="Total de specs")
    parser.add_argument("--seed", type=int, default=42, help="Seed (reprodutível)")
    parser.add_argument("--min-mods", type=int, default=10,
                        help="Mínimo de mods pra considerar (mc, loader) válido")
    args = parser.parse_args()

    specs = generate(target_count=args.count, seed=args.seed, min_mods=args.min_mods)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(specs, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n✅ {len(specs)} specs → {OUT_FILE}")
    validate_distribution(specs)

    print("\nPrimeiras 3:")
    for s in specs[:3]:
        print(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()