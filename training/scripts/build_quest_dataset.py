"""Gera instruções para criar quests no FTB Quests editor.

Saída: training/datasets/quest_generation.jsonl
Cada exemplo = 1 capítulo com N quests (3-8) prontas pra digitar no FTB.

Uso:
    python training/scripts/build_quest_dataset.py --fresh
"""

import hashlib, json, re, sqlite3, sys, unicodedata, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path.home() / ".local" / "share" / "modpack-ai-studio" / "mods.sqlite3"
SPECS_FILE = PROJECT_ROOT / "training" / "datasets" / "specs_generated.json"
OUTPUT = PROJECT_ROOT / "training" / "datasets" / "quest_generation.jsonl"
DEBUG_DIR = PROJECT_ROOT / "training" / "datasets" / "_failed_raw_quests"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:3b"
ATTEMPTS = 4
TEMPS = [0.4, 0.6, 0.8, 1.0]

SYSTEM_PROMPT = """You design Minecraft FTB Quests chapters.
You receive a modpack theme and a list of real mods available.
Return ONLY JSON:

{
  "chapter": {
    "title": "short chapter name",
    "description": "1 sentence overview",
    "icon": "minecraft:<id> or <mod>:<id>"
  },
  "quests": [
    {
      "title": "Short quest name",
      "description": "What the player must do, 1-2 sentences.",
      "icon": "<mod>:<id> or minecraft:<id>",
      "task": {
        "type": "item" | "kill" | "dimension" | "advancement",
        "target": "<id> or #<tag>",
        "count": <int, optional>
      },
      "reward": {
        "type": "item" | "xp",
        "target": "<id> (only if item)",
        "amount": <int>
      },
      "depends_on": [<titles of previous quests in this chapter>],
      "ftb_tip": "How to create this in FTB Quests editor (1 short sentence)."
    }
  ]
}

RULES (violations = rejected):
- Return 3 to 8 quests.
- Each quest MUST respect Minecraft progression (wood→stone→iron→diamond).
- Obsidian requires diamond pickaxe. Nether requires obsidian portal.
- Quest 1 has depends_on: [].
- Every other quest depends on at least one previous quest.
- ftb_tip must reference FTB Quests editor features (Item task, Kill task,
  Advancement task, Reward Table, tag selector, etc).
- NEVER cite mod names inside descriptions or ftb_tip.
  Only inside task.target and reward.target as IDs.
- icon and target must look like "namespace:path".
  If unsure, use "minecraft:crafting_table" for icon.
"""


def normalize(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s)).strip()


def extract_json(raw):
    start = raw.find("{")
    if start == -1:
        raise ValueError("sem chaves")
    depth, ins, esc, end = 0, False, False, -1
    for i in range(start, len(raw)):
        ch = raw[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            ins = not ins
            continue
        if ins:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise ValueError("chaves não balanceadas")
    cand = raw[start:end]
    try:
        return json.loads(cand)
    except json.JSONDecodeError:
        repaired = re.sub(r",(\s*[}\]])", r"\1", cand)
        return json.loads(repaired)


def call_ollama(system, user, temp):
    payload = {
        "model": MODEL,
        "system": system,
        "prompt": user,
        "stream": False,
        "format": "json",
        "options": {"temperature": temp},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read().decode()).get("response", "").strip()


def fetch_mods(conn, spec, limit=20):
    rows = conn.execute(
        "SELECT name, categories, downloads FROM mods "
        "WHERE game_versions LIKE ? AND loaders LIKE ? "
        "ORDER BY downloads DESC LIMIT ?",
        (f'%"{spec["mc"]}"%', f'%"{spec["loader"]}"%', limit * 6),
    ).fetchall()
    out = []
    for name, cats_j, dl in rows:
        try:
            cats = json.loads(cats_j or "[]")
        except:
            cats = []
        if spec["category"] in cats:
            out.append(name)
        if len(out) >= limit:
            break
    return out


def build_user(spec, mods):
    ml = "\n".join(f"- {m}" for m in mods)
    return (
        f"Theme: {spec['theme']}\nFocus: {spec['focus']}\n"
        f"MC: {spec['mc']} / {spec['loader']} / grind={spec['grind']}\n\n"
        f"Available mods:\n{ml}\n\n"
        f"Design one chapter with 4-6 quests. Return the JSON."
    )


MC_RULES = [
    (r"craft\s+(a\s+)?flint", "flint não se craft"),
    (r"craft\s+(some\s+)?coal", "coal não se craft"),
    (r"mine\s+obsidian", "obsidiana exige diamante"),
    (r"mine\s+diamond", "diamante exige ferro"),
]


def validate(raw):
    obj = extract_json(raw)

    if "chapter" not in obj or "quests" not in obj:
        raise ValueError("faltam 'chapter' ou 'quests'")

    ch = obj["chapter"]
    for k in ("title", "description", "icon"):
        if k not in ch or not ch[k]:
            raise ValueError(f"chapter.{k} ausente")

    qs = obj["quests"]
    if not (3 <= len(qs) <= 8):
        raise ValueError(f"{len(qs)} quests (esperado 3-8)")

    seen_titles = set()
    all_steps_lower = []
    for i, q in enumerate(qs):
        for k in (
            "title",
            "description",
            "icon",
            "task",
            "reward",
            "depends_on",
            "ftb_tip",
        ):
            if k not in q:
                raise ValueError(f"quest {i}: falta '{k}'")
        if q["title"] in seen_titles:
            raise ValueError(f"título duplicado: {q['title']}")
        seen_titles.add(q["title"])

        if (
            not isinstance(q["task"], dict)
            or "type" not in q["task"]
            or "target" not in q["task"]
        ):
            raise ValueError(f"quest {i}: task inválida")

        if ":" not in q["icon"]:
            raise ValueError(f"quest {i}: icon sem namespace")

        if ":" not in q["task"]["target"] and not q["task"]["target"].startswith("#"):
            raise ValueError(f"quest {i}: task.target sem namespace")

        # dependências
        if i == 0 and q["depends_on"]:
            raise ValueError("quest 0 não pode depender de nada")
        if i > 0 and not q["depends_on"]:
            raise ValueError(f"quest {i} sem depends_on")
        for dep in q["depends_on"]:
            if dep not in seen_titles and dep != q["title"]:  # noqa: SIM102
                if dep not in [x["title"] for x in qs[:i]]:
                    raise ValueError(
                        f"quest {i} depende de '{dep}' que ainda não existe"
                    )

        all_steps_lower.append(q["description"].lower())

    # Regras Minecraft globais
    joined = " | ".join(all_steps_lower)
    for pattern, reason in MC_RULES:
        if re.search(pattern, joined):
            raise ValueError(f"lógica MC: {reason}")

    return obj


def load_hashes():
    h = set()
    if OUTPUT.exists():
        for line in OUTPUT.open():
            try:
                o = json.loads(line)
                for m in o["messages"]:
                    if m["role"] == "user":
                        h.add(hashlib.sha1(m["content"].encode()).hexdigest())
            except:
                pass
    return h


def main():
    if not SPECS_FILE.exists():
        raise SystemExit(f"Rode generate_specs.py primeiro: {SPECS_FILE}")
    if "--fresh" in sys.argv and OUTPUT.exists():
        OUTPUT.unlink()

    specs = json.loads(SPECS_FILE.read_text())
    existing = load_hashes()
    print(f"Specs: {len(specs)} | Já gerados: {len(existing)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    ok = fail = skip = resumed = 0

    with OUTPUT.open("a", encoding="utf-8") as f:
        for i, spec in enumerate(specs, 1):
            mods = fetch_mods(conn, spec)
            if len(mods) < 3:
                skip += 1
                continue
            user = build_user(spec, mods)
            if hashlib.sha1(user.encode()).hexdigest() in existing:
                resumed += 1
                continue

            print(f"[{i}/{len(specs)}] {spec['theme']} — ", end="", flush=True)
            last_err, last_raw, success = None, None, False
            for att in range(ATTEMPTS):
                try:
                    raw = call_ollama(SYSTEM_PROMPT, user, TEMPS[att])
                    last_raw = raw
                    obj = validate(raw)
                    ex = {
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user},
                            {
                                "role": "assistant",
                                "content": json.dumps(obj, ensure_ascii=False),
                            },
                        ]
                    }
                    f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                    f.flush()
                    ok += 1
                    success = True
                    print("OK" if att == 0 else f"OK({att + 1})")
                    break
                except Exception as e:
                    last_err = e
            if not success:
                fail += 1
                if last_raw:
                    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                    (DEBUG_DIR / f"spec_{i:03d}.txt").write_text(last_raw)
                print(f"FALHOU ({last_err})")

    conn.close()
    total = sum(1 for _ in OUTPUT.open()) if OUTPUT.exists() else 0
    print(f"\nNovos: {ok} | Falhas: {fail} | Skip: {skip} | Já existiam: {resumed}")
    print(f"Total: {total}")


if __name__ == "__main__":
    main()
