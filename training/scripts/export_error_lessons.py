"""Export only user-confirmed Error Auto Fix lessons as conversational JSONL."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.error_memory import _read

OUT = ROOT / "training" / "datasets" / "error_diagnosis.jsonl"
SYSTEM = (
    "You are a careful Minecraft modpack debugging assistant. Separate evidence "
    "from hypotheses. Recommend minimal reversible fixes and never invent log evidence."
)


def main():
    lessons = [x for x in _read().get("lessons", []) if x.get("status") == "confirmed"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        for item in lessons:
            diagnosis = item.get("diagnosis", {})
            user = (
                "Diagnose this confirmed error case.\n"
                + "Original log/context was not retained by older app versions.\n"
                + "Model/provider: " + str(item.get("provider")) + "/" + str(item.get("model"))
            )
            answer = json.dumps(diagnosis, ensure_ascii=False)
            row = {"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
                {"role": "assistant", "content": answer},
            ]}
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Exported {len(lessons)} confirmed lesson(s) to {OUT}")
    if not lessons:
        print("No confirmed lessons yet. Analyze an error and confirm its lesson in the GUI first.")


if __name__ == "__main__":
    main()
