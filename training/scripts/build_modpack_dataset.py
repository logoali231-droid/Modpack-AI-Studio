"""Gera rascunhos para modpack_design.jsonl com grounding rigoroso."""

import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
DB_PATH = DATA_HOME / "modpack-ai-studio" / "mods.sqlite3"
OUTPUT = PROJECT_ROOT / "training" / "datasets" / "modpack_design.jsonl"
DEBUG_DIR = PROJECT_ROOT / "training" / "datasets" / "_failed_raw"

OLLAMA_URL = os.environ.get("MODPACK_AI_OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/generate"
MODEL = os.environ.get("MODPACK_AI_MODEL", "qwen2.5:3b")
ATTEMPTS = 3
TEMPS = [0.5, 0.7, 0.9]
PICK_LIMIT = 30  # mais opções = mais chance de coerência

# Few-shot: 1 exemplo curto ancora o formato e a qualidade.
SYSTEM_PROMPT = """You are a Minecraft modpack design specialist.
You receive a design brief and a list of real, compatible mods.
Return ONLY a JSON object with three keys:

"progression": 4-6 stage strings. Each stage MUST be a specific verb phrase
  (e.g. "Punch trees and craft a wooden pickaxe"), NOT a generic noun
  ("Basics", "Tools", "Exploits" are FORBIDDEN). Order matters and must
  respect Minecraft progression.
"design_rules": 3-5 rules about DESIGN PHILOSOPHY (grind, pacing, compat,
  rewards). NEVER mention specific mod names here.
"suggested_mods": 3-6 mod names copied EXACTLY from the provided list.
  Pick ONLY mods that fit the theme and grind level. Be conservative:
  if only 3 mods fit, return 3.

MANDATORY MINECRAFT RULES (violations = rejected):
- Wooden tools → stone tools → iron tools → diamond tools. Never out of order.
- Obsidian requires a diamond pickaxe. NEVER mention obsidian before diamond tier.
- Nether access requires obsidian portal. NEVER mention the Nether before iron tier.
- Furnaces are crafted from cobblestone — NEVER smelted from iron ore.
- Iron pickaxe requires a furnace. Furnace requires cobblestone mining first.
- Minecraft has no "firewood" — you gather logs, you don't craft firewood.

EXAMPLE OF GOOD OUTPUT:
{
  "progression": [
    "Punch trees and craft a wooden pickaxe",
    "Mine stone, craft stone tools, build a shelter",
    "Mine iron ore and smelt it in a furnace",
    "Craft iron tools and explore nearby caves",
    "Collect diamonds and craft a diamond pickaxe"
  ],
  "design_rules": [
    "Every tool tier should feel earned, not grindy",
    "Avoid recipe gating behind non-essential mods",
    "Keep early-game tools usable through mid-game",
    "Reward exploration with utility items, not raw resources"
  ],
  "suggested_mods": [
    "<copy exact names from the list, only ones that fit>"
  ]
}

Return only the JSON. No markdown, no trailing commas, no text outside."""

# Categorias proibidas por tema (mods com QUALQUER uma delas são descartados)
DEFAULT_FORBID = {
    "primitive survival": [
        "technology",
        "storage",
        "transportation",
        "management",
        "magic",
    ],
    "technology and automation": ["magic", "adventure"],
    "exploration and survival": ["management"],
    "low-grind progression": [],
    "multiblock industry": ["magic", "adventure", "decoration"],
    "hardcore survival": [
        "technology",
        "storage",
        "transportation",
        "magic",
        "decoration",
    ],
    "mixed gameplay": [],
}

# ========== SPECS (carregado do JSON gerado por generate_specs.py) ==========
SPECS_FILE = PROJECT_ROOT / "training" / "datasets" / "specs_generated.json"

if not SPECS_FILE.exists():
    raise SystemExit(
        f"Arquivo de specs não encontrado: {SPECS_FILE}\n"
        f"Rode primeiro:  python training/scripts/generate_specs.py --count 100"
    )

SPECS = json.loads(SPECS_FILE.read_text(encoding="utf-8"))
print(f"[specs] Carregados {len(SPECS)} specs de {SPECS_FILE.name}")
# ============================================================================


def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_valid_mod(suggested: str, allowed_norm: set) -> bool:
    s = normalize_name(suggested)
    if not s:
        return False
    if s in allowed_norm:
        return True
    for cat in allowed_norm:
        if len(cat) >= 6 and cat in s:
            return True
    return False


def extract_json_object(raw: str) -> dict:
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"sem chaves: {raw[:120]!r}")
    depth, in_string, escape, end = 0, False, False, -1
    for i in range(start, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise ValueError(f"chaves não balanceadas")
    candidate = raw[start:end]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            raise ValueError(f"JSON inválido: {e}") from None


def call_ollama(system: str, user: str, temperature: float) -> str:
    payload = {
        "model": MODEL,
        "system": system,
        "prompt": user,
        "stream": False,
        "options": {"temperature": temperature},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            return json.loads(resp.read().decode("utf-8")).get("response", "").strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {e.code} em /api/generate: {body}") from None


def fetch_mods_for_spec(conn, spec, limit=15):
    forbidden = DEFAULT_FORBID.get(spec["theme"], [])
    rows = conn.execute(
        "SELECT name, categories, downloads FROM mods "
        "WHERE game_versions LIKE ? AND loaders LIKE ? "
        "ORDER BY downloads DESC LIMIT ?",
        (f'%"{spec["mc"]}"%', f'%"{spec["loader"]}"%', limit * 10),
    ).fetchall()
    picked = []
    for name, cats_json, downloads in rows:
        try:
            cats = json.loads(cats_json or "[]")
        except json.JSONDecodeError:
            cats = []
        if spec["category"] not in cats:
            continue
        if any(f in cats for f in forbidden):
            continue
        picked.append({"name": name, "downloads": downloads})
        if len(picked) >= limit:
            break
    return picked


def build_user_prompt(spec, mods):
    lines = "\n".join(f"- {m['name']}" for m in mods)
    return (
        f"Design brief:\n"
        f"  version={spec['mc']} loader={spec['loader']}\n"
        f"  theme={spec['theme']}\n"
        f"  focus={spec['focus']}\n"
        f"  grind={spec['grind']}\n\n"
        f"Allowed mods (copy names EXACTLY; do not pick what doesn't fit):\n{lines}\n\n"
        "Return the JSON object."
    )


def validate_response(raw, allowed_mods_list):
    obj = extract_json_object(raw)
    allowed_norm = {normalize_name(m["name"]) for m in allowed_mods_list}
    allowed_raw = {m["name"] for m in allowed_mods_list}

    # 1. Keys e tipos
    for key in ("progression", "design_rules", "suggested_mods"):
        if not isinstance(obj.get(key), list) or not obj[key]:
            raise ValueError(f"{key} ausente/vazio")

    # 2. Progression: 4-6 itens, cada um com >=2 palavras
    prog = obj["progression"]
    if not (4 <= len(prog) <= 6):
        raise ValueError(f"progression deve ter 4-6 itens, tem {len(prog)}")
    for item in prog:
        if not isinstance(item, str) or len(item.split()) < 2:
            raise ValueError(f"progression item genérico: {item!r}")

    # 3. design_rules: 3-5 itens, nenhum pode citar mod
    rules = obj["design_rules"]
    if not (3 <= len(rules) <= 5):
        raise ValueError(f"design_rules deve ter 3-5 itens")
    for rule in rules:
        rule_norm = normalize_name(rule)
        for mod_name in allowed_raw:
            if len(mod_name) >= 6 and normalize_name(mod_name) in rule_norm:
                raise ValueError(f"design_rule cita mod '{mod_name}': {rule[:60]!r}")

    # 4. suggested_mods: TODOS devem vir da lista enviada (não do catálogo todo)
    bad = [m for m in obj["suggested_mods"] if not is_valid_mod(m, allowed_norm)]
    if bad:
        raise ValueError(f"mods fora da lista enviada: {bad}")

    if len(obj["suggested_mods"]) < 3:
        raise ValueError(f"só {len(obj['suggested_mods'])} mods sugeridos (mín 3)")

    if len(obj["suggested_mods"]) > 6:
        raise ValueError(f"{len(obj['suggested_mods'])} mods (máx 6)")

    return obj


def prompt_hash(user_prompt: str) -> str:
    return hashlib.sha1(user_prompt.encode("utf-8")).hexdigest()


def load_existing_hashes() -> set:
    hashes = set()
    if not OUTPUT.exists():
        return hashes
    for line in OUTPUT.open("r", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            for msg in obj.get("messages", []):
                if msg.get("role") == "user":
                    hashes.add(prompt_hash(msg["content"]))
        except Exception:
            pass
    return hashes


def dump_failed_raw(index, spec, raw):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (DEBUG_DIR / f"spec_{index:03d}.txt").write_text(
        f"# spec:\n{json.dumps(spec, indent=2)}\n\n# raw:\n{raw}\n",
        encoding="utf-8",
    )


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Banco não encontrado: {DB_PATH}")

    fresh = "--fresh" in sys.argv
    if fresh and OUTPUT.exists():
        OUTPUT.unlink()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing_hashes()
    print(f"Já presentes: {len(existing)} exemplo(s).")

    conn = sqlite3.connect(DB_PATH)
    ok, fail, skipped_mods, resumed = 0, 0, 0, 0

    with OUTPUT.open("a", encoding="utf-8") as f:
        for i, spec in enumerate(SPECS, 1):
            mods = fetch_mods_for_spec(conn, spec)
            if len(mods) < 3:
                skipped_mods += 1
                print(
                    f"[{i}/{len(SPECS)}] {spec['theme']} → SKIP (só {len(mods)} mods)"
                )
                continue

            user = build_user_prompt(spec, mods)
            if prompt_hash(user) in existing:
                resumed += 1
                continue

            print(
                f"[{i}/{len(SPECS)}] {spec['theme']} ({len(mods)}) … ",
                end="",
                flush=True,
            )

            last_err, last_raw, success = None, None, False
            for attempt in range(ATTEMPTS):
                try:
                    raw = call_ollama(SYSTEM_PROMPT, user, TEMPS[attempt])
                    last_raw = raw
                    obj = validate_response(raw, mods)
                    example = {
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user},
                            {
                                "role": "assistant",
                                "content": json.dumps(obj, ensure_ascii=False),
                            },
                        ]
                    }
                    f.write(json.dumps(example, ensure_ascii=False) + "\n")
                    f.flush()
                    ok += 1
                    success = True
                    print("OK" if attempt == 0 else f"OK (tent {attempt + 1})")
                    break
                except Exception as exc:
                    last_err = exc

            if not success:
                fail += 1
                if last_raw:
                    dump_failed_raw(i, spec, last_raw)
                print(f"FALHOU ({last_err})")

    conn.close()
    total = sum(1 for _ in OUTPUT.open("r", encoding="utf-8")) if OUTPUT.exists() else 0
    print(
        f"\nNovos: {ok} | Falhas: {fail} | Skip: {skipped_mods} | Já existiam: {resumed}"
    )
    print(f"Total no arquivo: {total}")


if __name__ == "__main__":
    main()
