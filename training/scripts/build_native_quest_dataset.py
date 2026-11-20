"""Build SFT examples for the app's native advancement/datapack quest format.

This deliberately does NOT generate FTB Quests instructions. Every generated
chapter is validated by the same validator used by the desktop application.
"""
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.quests import validate_campaign  # noqa: E402

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
DB_PATH = DATA_HOME / "modpack-ai-studio" / "mods.sqlite3"
SPECS = ROOT / "training" / "datasets" / "specs_generated.json"
OUTPUT = ROOT / "training" / "datasets" / "quest_generation.jsonl"
FAILED = ROOT / "training" / "datasets" / "_failed_raw_quests"

MODEL = os.environ.get("MODPACK_AI_MODEL", "qwen2.5:3b")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/") + "/api/chat"
SYSTEM = """You create quest chapters for Modpack AI Studio's NATIVE Minecraft advancement datapack.
Return ONLY JSON with this exact shape:
{
  "title": "Chapter title",
  "description": "Short chapter purpose",
  "quests": [
    {
      "title": "Quest title",
      "description": "A clear player objective",
      "tasks": [{"item": "minecraft:oak_log", "count": 8}],
      "reward": {"item": "minecraft:bread", "count": 2}
    }
  ]
}
Rules:
- Create exactly 3 quests for one chapter.
- Each quest must have 1-2 item tasks and one item reward.
- Task and reward IDs MUST be real vanilla Minecraft item IDs beginning with minecraft:.
- Counts must be integers from 1 to 64.
- Do not use modded item IDs. The current datapack validator intentionally supports vanilla items only.
- Respect the Minecraft version and progression stage in the brief.
- No FTB Quests, no ftb_tip, no depends_on, no chapter wrapper.
- Return valid JSON only, without markdown.
"""


def prompt_for(spec):
    return (
        f"Design one native quest chapter for this modpack brief.\n"
        f"Minecraft: {spec.get('mc')} / {spec.get('loader')}\n"
        f"Theme: {spec.get('theme')}\n"
        f"Focus: {spec.get('focus')}\n"
        f"Grind target: {spec.get('grind')}\n"
        "Make the chapter fit this stage and create a meaningful, non-repetitive "
        "sequence of three objectives. Return the JSON object."
    )


def ask_ollama(user):
    body = json.dumps({
        "model": MODEL,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0.35},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    content = data.get("message", {}).get("content", "").strip()
    if not content:
        raise ValueError("Ollama returned an empty response.")
    return content


def load_existing():
    hashes = set()
    if OUTPUT.exists():
        for line in OUTPUT.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                for msg in row.get("messages", []):
                    if msg.get("role") == "user":
                        hashes.add(hashlib.sha256(msg.get("content", "").encode()).hexdigest())
            except (ValueError, AttributeError):
                continue
    return hashes


def main():
    if not SPECS.is_file():
        raise SystemExit("Run the GUI pipeline first so specs_generated.json exists.")
    if not DB_PATH.is_file():
        raise SystemExit(f"Mod database not found: {DB_PATH}")

    specs = json.loads(SPECS.read_text(encoding="utf-8"))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing()
    created = failed = skipped = 0

    with OUTPUT.open("a", encoding="utf-8") as out:
        for index, spec in enumerate(specs, 1):
            user = prompt_for(spec)
            digest = hashlib.sha256(user.encode()).hexdigest()
            if digest in existing:
                skipped += 1
                continue
            print(f"[{index}/{len(specs)}] {spec.get('theme')} · {spec.get('mc')} {spec.get('loader')}", flush=True)
            raw = ""
            try:
                raw = ask_ollama(user)
                chapter = json.loads(raw)
                if not isinstance(chapter, dict) or len(chapter.get("quests", [])) != 3:
                    raise ValueError("Chapter must contain exactly 3 quests.")
                for quest_index, quest in enumerate(chapter["quests"], 1):
                    if not isinstance(quest, dict) or not isinstance(quest.get("tasks"), list):
                        raise ValueError(f"Quest {quest_index} has no task list.")
                    for task in quest["tasks"]:
                        item = task.get("item") if isinstance(task, dict) else None
                        if not isinstance(item, str) or not item.startswith("minecraft:"):
                            raise ValueError(f"Quest {quest_index} contains a non-vanilla task item.")
                    reward = quest.get("reward")
                    reward_item = reward.get("item") if isinstance(reward, dict) else None
                    if not isinstance(reward_item, str) or not reward_item.startswith("minecraft:"):
                        raise ValueError(f"Quest {quest_index} contains a non-vanilla reward item.")
                chapter["title"] = str(chapter.get("title") or f"Chapter {index}")[:80]
                chapter["description"] = str(chapter.get("description") or spec.get("focus", ""))[:200]
                validated = validate_campaign({"chapters": [chapter]})["chapters"][0]
                # Match the live app's exact output shape and constraints.
                example = {
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": json.dumps(validated, ensure_ascii=False)},
                    ]
                }
                out.write(json.dumps(example, ensure_ascii=False) + "\n")
                out.flush()
                existing.add(digest)
                created += 1
                print("  ✓ validated", flush=True)
            except Exception as exc:
                failed += 1
                FAILED.mkdir(parents=True, exist_ok=True)
                (FAILED / f"chapter_{index:04d}.json").write_text(
                    json.dumps({"spec": spec, "error": str(exc), "raw": raw},
                               ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"  ✗ {exc}", flush=True)

    print(f"\nNative quest dataset: {created} new, {skipped} already present, {failed} failed.")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
