"""One-time move of files named after Max (the old name) to Sanae's names.

data/max.db -> data/sanae.db, ~/Documents/Max Notes -> Sanae Notes, ~/Documents/Max Course
Material -> Sanae Course Material (with the paths stored in the database updated), and the
published phone app. Runs at start-up; does nothing once the new names exist.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .config import resolve_path

log = logging.getLogger("sanae")


def _move(old: Path, new: Path) -> bool:
    if not old.exists() or new.exists():
        return False
    new.parent.mkdir(parents=True, exist_ok=True)
    old.rename(new)
    log.info("renamed %s -> %s", old, new)
    return True


def _old_folder(new: Path) -> Path:
    return new.with_name(new.name.replace("Sanae", "Max", 1))


def migrate(cfg) -> None:
    try:
        db = resolve_path((cfg.get("memory", {}) or {}).get("db", "data/sanae.db"))
        if db.name == "sanae.db":
            for suffix in ("", "-wal", "-shm"):
                _move(db.with_name("max.db" + suffix), db.with_name("sanae.db" + suffix))
        _move(resolve_path("data/app/max.apk"), resolve_path("data/app/sanae.apk"))

        folders = [(cfg.get("notes", {}) or {}).get("folder", "")]
        folders += list((cfg.get("course", {}) or {}).get("folders", []) or [])
        moved = []
        for f in folders:
            new = Path(os.path.expanduser(f)) if f else None
            if new is not None and "Sanae" in new.name and _move(_old_folder(new), new):
                moved.append((str(_old_folder(new)), str(new)))
        if moved and db.exists():
            with closing(sqlite3.connect(db)) as con, con:
                for old, new in moved:
                    con.execute("UPDATE notes SET folder = ? || substr(folder, ?) WHERE folder LIKE ? || '%'",
                                (new, len(old) + 1, old))
                    rows = con.execute("SELECT key FROM kv WHERE key LIKE ? || '%'", ("docnote:" + old,)).fetchall()
                    for (key,) in rows:
                        con.execute("UPDATE OR REPLACE kv SET key = ? WHERE key = ?",
                                    ("docnote:" + new + key[len("docnote:" + old):], key))
    except Exception as exc:                # never block start-up over a rename
        log.warning("couldn't move the old Max files: %s", exc)
