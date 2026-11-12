"""Persistent, confirmation-gated lessons from Error Auto Fix."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone

def memory_path():
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "modpack-ai-studio" / "error_lessons.json"

def _read():
    path = memory_path()
    if not path.is_file():
        return {"schema": 1, "lessons": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("lessons"), list) else {"schema": 1, "lessons": []}
    except (OSError, json.JSONDecodeError):
        return {"schema": 1, "lessons": []}

def load_confirmed_lessons(limit=12):
    return [item for item in _read()["lessons"] if item.get("status") == "confirmed"][-limit:]

def record_lesson(diagnosis, model, provider):
    data = _read()
    data["lessons"].append({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "unverified",
        "model": str(model),
        "provider": str(provider),
        "diagnosis": diagnosis,
    })
    data["lessons"] = data["lessons"][-100:]
    path = memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    return path

def confirm_latest_lesson():
    data = _read()
    for item in reversed(data["lessons"]):
        if item.get("status") == "unverified":
            item["status"] = "confirmed"
            item["confirmed_at"] = datetime.now(timezone.utc).isoformat()
            path = memory_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
            return True
    return False
