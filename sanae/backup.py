"""Nightly backup of everything she keeps about you two, so a dead disk doesn't take it with it.

  - Once a day (the first check after 4 AM, or at start-up if the last one is older than a day):
    the databases (sanae.db: chats, diary, journal, sketches, lists...; course.db) are copied with
    SQLite's online backup (safe while she's running) into one zip per day, with a few small files
    (persona.yaml, the voice profile, the avatar position).
  - Photos and voice notes (data/scrapbook, data/voicenotes) are mirrored into <folder>/files:
    only new or changed files are copied, and a file you deleted is deleted there too (so "forget"
    really forgets).
  - Kept: every day for `keep_days` (60), then the first backup of each month for good.
  - Where: backup.folder in config.yaml; empty = OneDrive\\Sanae Backups when OneDrive is set up
    (so it leaves the laptop), else data/backups.
  - Never copied: secrets.yaml, the phone token, the browser profile.

Restore (with Sanae closed): python -m sanae.backup restore 2026-10-27   (or: list)
The current files are kept next to the restored ones as *.before-restore.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from .config import ROOT, resolve_path

log = logging.getLogger(__name__)
DATABASES = ["data/sanae.db", "data/course.db"]
SMALL_FILES = ["persona.yaml", "data/voice_profile.npy", "data/avatar-position.json", "data/wake_keywords.txt",
               "data/interrupt_keywords.txt"]
FOLDERS = ["data/scrapbook", "data/voicenotes"]
KEEP_DAYS = 60
DAY_STARTS = 4                     # a "day" for backups starts at 4 AM, like the diary


def default_folder() -> Path:
    od = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if od and Path(od).is_dir():
        return Path(od) / "Sanae Backups"
    return ROOT / "data" / "backups"


def day_of(t: dt.datetime) -> str:
    return (t - dt.timedelta(hours=DAY_STARTS)).date().isoformat()


class Backup:
    def __init__(self, folder: str | Path | None = None, keep_days: int = KEEP_DAYS, root: Path = ROOT,
                 clock=time.time, databases=DATABASES, small_files=SMALL_FILES, folders=FOLDERS):
        self.folder = Path(folder) if folder else default_folder()
        if not self.folder.is_absolute():
            self.folder = resolve_path(str(self.folder))
        self.keep_days, self.root, self.clock = keep_days, root, clock
        self.databases, self.small_files, self.folders = databases, small_files, folders
        self.lock = threading.Lock()
        self.last_error = ""
        self._stop = threading.Event()

    # ----- making one -----
    def zips(self) -> list[Path]:
        return sorted(self.folder.glob("sanae-????-??-??.zip")) if self.folder.is_dir() else []

    def latest(self) -> str | None:
        z = self.zips()
        return z[-1].stem.removeprefix("sanae-") if z else None

    def due(self) -> bool:
        return self.latest() != day_of(dt.datetime.fromtimestamp(self.clock()))

    def run(self) -> dict:
        """Back up now (today's zip is replaced if there is one). Returns what was done."""
        with self.lock:
            day = day_of(dt.datetime.fromtimestamp(self.clock()))
            self.folder.mkdir(parents=True, exist_ok=True)
            target = self.folder / f"sanae-{day}.zip"
            part = target.with_suffix(".zip.part")
            with tempfile.TemporaryDirectory(prefix="sanae-backup-") as tmp:
                with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
                    for rel in self.databases:
                        src = self.root / rel
                        if not src.is_file():
                            continue
                        copy = Path(tmp) / Path(rel).name
                        snapshot(src, copy)
                        z.write(copy, rel)
                    for rel in self.small_files:
                        src = self.root / rel
                        if src.is_file():
                            z.write(src, rel)
            part.replace(target)
            copied, removed = self.mirror()
            pruned = self.prune()
            self.last_error = ""
            info = {"day": day, "file": str(target), "kb": target.stat().st_size // 1024, "copied": copied,
                    "removed": removed, "pruned": pruned}
            log.info("backup: %s", info)
            return info

    def mirror(self) -> tuple[int, int]:
        """Photos and voice notes: copy new / changed files, delete ones that are gone here."""
        copied = removed = 0
        for rel in self.folders:
            src_dir, dst_dir = self.root / rel, self.folder / "files" / rel
            have = set()
            if src_dir.is_dir():
                for src in src_dir.rglob("*"):
                    if not src.is_file():
                        continue
                    sub = src.relative_to(src_dir)
                    have.add(sub)
                    dst = dst_dir / sub
                    st = src.stat()
                    if dst.is_file() and dst.stat().st_size == st.st_size and dst.stat().st_mtime >= st.st_mtime - 2:
                        continue
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    copied += 1
            if dst_dir.is_dir():
                for dst in dst_dir.rglob("*"):
                    if dst.is_file() and dst.relative_to(dst_dir) not in have:
                        dst.unlink()
                        removed += 1
        return copied, removed

    def prune(self) -> int:
        """Every day for keep_days, then the first of each month for good."""
        today = dt.date.fromisoformat(day_of(dt.datetime.fromtimestamp(self.clock())))
        months: set[str] = set()
        gone = 0
        for z in self.zips():                     # oldest first: the first one of a month is the keeper
            day = dt.date.fromisoformat(z.stem.removeprefix("sanae-"))
            month = day.isoformat()[:7]
            first_of_month = month not in months
            months.add(month)
            if (today - day).days > self.keep_days and not first_of_month:
                z.unlink()
                gone += 1
        return gone

    def status(self) -> dict:
        z = self.zips()
        return {"folder": str(self.folder), "latest": self.latest(), "count": len(z),
                "mb": round(sum(p.stat().st_size for p in z) / 1e6, 1), "error": self.last_error}

    def spoken(self) -> str:
        s = self.status()
        if not s["latest"]:
            return "I haven't made a backup yet."
        when = "today" if s["latest"] == day_of(dt.datetime.fromtimestamp(self.clock())) else f"on {s['latest']}"
        return f"Last backup was {when}. I'm keeping {s['count']} of them ({s['mb']} MB) in {s['folder']}."

    # ----- every night -----
    def start(self, every_s: float = 1800) -> "Backup":
        def loop():
            self._stop.wait(120)                  # let start-up settle first
            while not self._stop.is_set():
                try:
                    if self.due():
                        self.run()
                except Exception as exc:
                    self.last_error = str(exc)
                    log.warning("backup failed: %s", exc)
                self._stop.wait(every_s)

        threading.Thread(target=loop, name="backup", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()


def snapshot(src: Path, dst: Path):
    """A consistent copy of a live SQLite database."""
    a = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    b = sqlite3.connect(dst)
    try:
        a.backup(b)
    finally:
        b.close()
        a.close()


def restore(day: str, backup: Backup | None = None) -> list[str]:
    b = backup or Backup()
    z = b.folder / f"sanae-{day}.zip"
    if not z.is_file():
        raise FileNotFoundError(f"no backup for {day} in {b.folder}")
    out = []
    with zipfile.ZipFile(z) as zf:
        for name in zf.namelist():
            dst = b.root / name
            if dst.exists():
                shutil.copy2(dst, dst.with_name(dst.name + ".before-restore"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(dst, "wb") as f:
                shutil.copyfileobj(src, f)
            out.append(name)
    for rel in b.folders:                         # photos / voice notes: copy back what's missing
        src_dir = b.folder / "files" / rel
        if src_dir.is_dir():
            for src in src_dir.rglob("*"):
                dst = b.root / rel / src.relative_to(src_dir)
                if src.is_file() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
    return out


def make(cfg) -> Backup | None:
    c = cfg.get("backup", {}) or {}
    if c.get("enabled", True) is False:
        return None
    return Backup(c.get("folder") or None, int(c.get("keep_days", KEEP_DAYS)))


if __name__ == "__main__":
    from .config import load_config

    args = sys.argv[1:]
    b = make(load_config()) or Backup()
    if args[:1] == ["restore"] and len(args) == 2:
        print("restored:", ", ".join(restore(args[1], b)))
    elif args[:1] == ["list"]:
        for z in b.zips():
            print(z.name, f"{z.stat().st_size // 1024} KB")
    elif args[:1] == ["now"]:
        print(b.run())
    else:
        print("usage: python -m sanae.backup list | now | restore YYYY-MM-DD")
