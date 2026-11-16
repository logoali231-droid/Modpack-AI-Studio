
import json
import sqlite3
from pathlib import Path

DB_PATH = (
    Path.home()
    / ".local/share/modpack-ai-studio/mods.sqlite3"
)

OUTPUT = Path("training/data/raw/mod_knowledge.jsonl")


def export_mods():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    rows = connection.execute(
        "SELECT * FROM mods ORDER BY name"
    ).fetchall()

    exported = 0

    with OUTPUT.open("w", encoding="utf-8") as file:
        for row in rows:
            mod = dict(row)

            # Convert JSON text columns into actual arrays.
            for field in (
                "authors",
                "categories",
                "game_versions",
                "loaders"
            ):
                try:
                    mod[field] = json.loads(
                        mod.get(field) or "[]"
                    )
                except (json.JSONDecodeError, TypeError):
                    mod[field] = []

            # Keep source information for traceability.
            mod["record_type"] = "mod_catalog_entry"

            file.write(
                json.dumps(mod, ensure_ascii=False) + "\n"
            )

            exported += 1

    connection.close()

    print(f"Export complete: {exported} mods")
    print(f"Output: {OUTPUT.resolve()}")


if __name__ == "__main__":
    export_mods()
