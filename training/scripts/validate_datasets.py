"""Structural and task-specific validation for training JSONL files."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "training" / "datasets"
NAMESPACE_ID = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")


def validate_messages(example, path, line_no):
    messages = example.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        raise ValueError("messages must be a list with at least two entries")
    roles = [m.get("role") for m in messages if isinstance(m, dict)]
    if len(roles) != len(messages) or "user" not in roles or "assistant" not in roles:
        raise ValueError("messages must contain user and assistant objects")
    if roles[-1] != "assistant":
        raise ValueError("last message must be assistant")
    if any(not isinstance(m.get("content"), str) for m in messages):
        raise ValueError("every message content must be text")


def validate_quest_answer(text):
    obj = json.loads(text)
    chapter = obj.get("chapter")
    quests = obj.get("quests")
    if not isinstance(chapter, dict) or not isinstance(quests, list) or not 3 <= len(quests) <= 8:
        raise ValueError("FTB answer needs chapter object and 3-8 quests")
    titles = []
    for index, quest in enumerate(quests):
        for key in ("title", "description", "icon", "task", "reward", "depends_on", "ftb_tip"):
            if key not in quest:
                raise ValueError(f"quest {index + 1} missing {key}")
        if not NAMESPACE_ID.fullmatch(str(quest["icon"])):
            raise ValueError(f"quest {index + 1} has invalid icon ID")
        task = quest["task"]
        if not isinstance(task, dict) or task.get("type") not in ("item", "kill", "dimension", "advancement"):
            raise ValueError(f"quest {index + 1} has invalid task type")
        target = str(task.get("target", ""))
        if not (NAMESPACE_ID.fullmatch(target) or target.startswith("#")):
            raise ValueError(f"quest {index + 1} has invalid task target")
        reward = quest["reward"]
        if not isinstance(reward, dict) or reward.get("type") not in ("item", "xp"):
            raise ValueError(f"quest {index + 1} has invalid reward")
        if index == 0 and quest["depends_on"]:
            raise ValueError("first quest must have no dependencies")
        if index > 0 and not quest["depends_on"]:
            raise ValueError(f"quest {index + 1} needs a previous dependency")
        if any(dep not in titles for dep in quest["depends_on"]):
            raise ValueError(f"quest {index + 1} depends on a title that has not appeared")
        titles.append(quest["title"])


def main():
    files = {
        "modpack_design.jsonl": "modpack",
        "quest_generation.jsonl": "quest",
        "error_diagnosis.jsonl": "generic",
    }
    total = errors = 0
    for filename, kind in files.items():
        path = DATASETS / filename
        if not path.exists():
            print(f"SKIP {filename}: not created yet")
            continue
        seen = set()
        valid = 0
        for line_no, raw in enumerate(path.open(encoding="utf-8"), 1):
            if not raw.strip():
                continue
            total += 1
            try:
                example = json.loads(raw)
                validate_messages(example, path, line_no)
                assistant = next(m["content"] for m in reversed(example["messages"]) if m["role"] == "assistant")
                if kind == "quest":
                    validate_quest_answer(assistant)
                elif kind == "modpack":
                    answer = json.loads(assistant)
                    if not all(isinstance(answer.get(k), list) and answer[k] for k in ("progression", "design_rules", "suggested_mods")):
                        raise ValueError("modpack answer missing non-empty required arrays")
                key = json.dumps(example, sort_keys=True, ensure_ascii=False)
                if key in seen:
                    raise ValueError("duplicate example in same dataset")
                seen.add(key)
                valid += 1
            except Exception as exc:
                errors += 1
                print(f"FAIL {filename}:{line_no}: {exc}")
        print(f"{'OK' if valid else 'EMPTY'} {filename}: {valid} valid example(s)")
    print(f"\nTotal checked: {total} | Errors: {errors}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
