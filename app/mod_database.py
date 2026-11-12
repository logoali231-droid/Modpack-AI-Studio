"""Local SQLite index for Modrinth and CurseForge mod metadata."""
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


def database_path():
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    folder = root / "modpack-ai-studio"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "mods.sqlite3"


class ModDatabase:
    def __init__(self, path=None):
        self.path = Path(path) if path else database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS mods (
                    source TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    slug TEXT,
                    name TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    authors TEXT NOT NULL DEFAULT '[]',
                    categories TEXT NOT NULL DEFAULT '[]',
                    game_versions TEXT NOT NULL DEFAULT '[]',
                    loaders TEXT NOT NULL DEFAULT '[]',
                    downloads INTEGER NOT NULL DEFAULT 0,
                    icon_url TEXT NOT NULL DEFAULT '',
                    website TEXT NOT NULL DEFAULT '',
                    license TEXT NOT NULL DEFAULT '',
                    date_modified TEXT NOT NULL DEFAULT '',
                    last_synced TEXT NOT NULL,
                    PRIMARY KEY (source, project_id)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_mods_name ON mods(name COLLATE NOCASE)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_mods_downloads ON mods(downloads DESC)")

    @staticmethod
    def _json(value):
        return json.dumps(value if value is not None else [], ensure_ascii=False)

    def upsert(self, item):
        source = str(item.get("source", "")).strip().lower()
        project_id = str(item.get("project_id", "")).strip()
        name = str(item.get("name", "")).strip()
        if source not in ("modrinth", "curseforge") or not project_id or not name:
            raise ValueError("A mod database record needs source, project_id and name.")
        now = datetime.now(timezone.utc).isoformat()
        values = (
            source, project_id, str(item.get("slug") or ""),
            name, str(item.get("summary") or "")[:1000],
            str(item.get("description") or "")[:50000],
            self._json(item.get("authors")), self._json(item.get("categories")),
            self._json(item.get("game_versions")), self._json(item.get("loaders")),
            max(0, int(item.get("downloads") or 0)), str(item.get("icon_url") or ""),
            str(item.get("website") or ""), str(item.get("license") or ""),
            str(item.get("date_modified") or ""), now
        )
        with self._connect() as db:
            db.execute("""
                INSERT INTO mods (
                    source, project_id, slug, name, summary, description, authors,
                    categories, game_versions, loaders, downloads, icon_url,
                    website, license, date_modified, last_synced
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, project_id) DO UPDATE SET
                    slug=excluded.slug,
                    name=excluded.name,
                    summary=CASE WHEN excluded.summary='' THEN mods.summary ELSE excluded.summary END,
                    description=CASE WHEN excluded.description='' THEN mods.description ELSE excluded.description END,
                    authors=CASE WHEN excluded.authors='[]' THEN mods.authors ELSE excluded.authors END,
                    categories=CASE WHEN excluded.categories='[]' THEN mods.categories ELSE excluded.categories END,
                    game_versions=CASE WHEN excluded.game_versions='[]' THEN mods.game_versions ELSE excluded.game_versions END,
                    loaders=CASE WHEN excluded.loaders='[]' THEN mods.loaders ELSE excluded.loaders END,
                    downloads=MAX(mods.downloads, excluded.downloads),
                    icon_url=CASE WHEN excluded.icon_url='' THEN mods.icon_url ELSE excluded.icon_url END,
                    website=CASE WHEN excluded.website='' THEN mods.website ELSE excluded.website END,
                    license=CASE WHEN excluded.license='' THEN mods.license ELSE excluded.license END,
                    date_modified=CASE WHEN excluded.date_modified='' THEN mods.date_modified ELSE excluded.date_modified END,
                    last_synced=excluded.last_synced
            """, values)
        return project_id

    def search(self, query="", source="all", limit=200):
        terms = [part.strip() for part in str(query).split() if part.strip()]
        where = []
        params = []
        if source in ("modrinth", "curseforge"):
            where.append("source=?")
            params.append(source)
        for term in terms:
            where.append("(name LIKE ? OR summary LIKE ? OR description LIKE ? OR categories LIKE ?)")
            pattern = f"%{term}%"
            params.extend([pattern] * 4)
        sql = "SELECT * FROM mods"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY downloads DESC, name COLLATE NOCASE LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, source, project_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM mods WHERE source=? AND project_id=?",
                (source.lower(), str(project_id))
            ).fetchone()
        return self._decode(row) if row else None

    def stats(self):
        with self._connect() as db:
            rows = db.execute(
                "SELECT source, COUNT(*) AS total, MAX(last_synced) AS last_synced "
                "FROM mods GROUP BY source"
            ).fetchall()
        return {row["source"]: {"total": row["total"], "last_synced": row["last_synced"]} for row in rows}

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        item = dict(row)
        for key in ("authors", "categories", "game_versions", "loaders"):
            try:
                item[key] = json.loads(item[key])
            except (TypeError, json.JSONDecodeError):
                item[key] = []
        return item
