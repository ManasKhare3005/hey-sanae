"""Todo list: things to get done some time, no alarm ("add milk to my list", "what's on my todo list?").

Kept in the memory database and synced to the phone like reminders (sync.py), so the list and
its home-screen widget work with the laptop off and ticks made there come back here.

A todo is open, done (ticked, still shown until cleared) or deleted (cleared). For the sync rule
"deleted" counts as finished, so a cleared todo never comes back; open <-> done goes by the
later edit, so unticking on the phone works.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .reminders import new_uid, now_ms

DONE_SHOWN_DAYS = 7          # ticked todos stay on the list (and the phone) this long unless cleared


@dataclass
class Todo:
    uid: str
    text: str
    status: str = "open"       # open, done, deleted
    created: str = ""
    updated: int = 0

    @property
    def done(self) -> bool:
        return self.status == "done"

    def to_sync(self) -> dict:
        return {"uid": self.uid, "text": self.text, "status": self.status, "created": self.created,
                "updated_ms": self.updated}


def split_items(text: str) -> list[str]:
    """'milk, eggs and bread' -> three todos; 'call mom and dad' stays one (no comma)."""
    text = re.sub(r"\s+", " ", text).strip(" .")
    if "," not in text and ";" not in text:
        return [text] if text else []
    parts = re.split(r"\s*[,;]\s*(?:and\s+)?|\s+and\s+(?=[^,;]*$)", text)
    return [p.strip(" .") for p in parts if p and p.strip(" .")]


_LIST = r"(?:my |the )?(?:to-?do |to do )?list"     # shopping / grocery lists: groceries.py
# The 4b model answered these from the chat (a stale list) or claimed it removed items without the tool
SHOW = re.compile(rf"^\W*(?:(?:hey |ok(?:ay)? )?(?:what'?s|what is|read(?: me)?|show(?: me)?|tell me)\s+(?:on |in )?{_LIST}"
                  rf"|what do i (?:still )?(?:need|have) to do(?: today)?|what'?s left (?:on|in) {_LIST}|"
                  rf"(?:read|show) (?:me )?my to-?dos?)\W*$", re.I)
CLEAR_DONE = re.compile(rf"\b(?:clear|remove|delete|get rid of)\s+(?:all\s+)?(?:the\s+)?(?:done|finished|ticked|completed|checked)"
                        rf"(?:\s+(?:ones|items|things|todos))?(?:\s+(?:from|off|on)\s+{_LIST})?\W*$", re.I)
CLEAR_ALL = re.compile(rf"\b(?:clear|wipe|empty|delete)\s+(?:my |the )?(?:whole |entire )?(?:to-?do |to do )?list\W*$", re.I)
REMOVE = re.compile(rf"\b(?:take|remove|delete|drop|scratch)\s+(?P<item>.+?)\s+(?:off|from)\s+{_LIST}\W*$", re.I)


def todo_route(text: str) -> tuple[str, dict] | None:
    """Clear todo requests mapped straight to their tool."""
    t = text.strip()
    if SHOW.search(t):
        return "list_todos", {}
    if CLEAR_DONE.search(t):
        return "clear_todos", {"which": "done"}
    if CLEAR_ALL.search(t):
        return "clear_todos", {"which": "all"}
    if m := REMOVE.search(t):
        item = re.sub(r"^(?:the|my)\s+", "", m.group("item").strip(), flags=re.I)
        if item.lower() not in ("it", "that", "this"):
            return "clear_todos", {"which": item}
    return None


class Todos:
    def __init__(self, store):
        self.store = store                 # MemoryStore (its schema has the todos table)

    def _rows(self, where: str, args=()) -> list[Todo]:
        with self.store.lock:
            rows = self.store.db.execute(f"SELECT * FROM todos WHERE {where} ORDER BY created, rowid", args).fetchall()
        return [Todo(r["uid"], r["text"], r["status"], r["created"], r["updated"]) for r in rows]

    def _write(self, t: Todo):
        with self.store.lock:
            self.store.db.execute(
                "INSERT INTO todos (uid, text, status, created, updated) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(uid) DO UPDATE SET text = excluded.text, status = excluded.status, "
                "updated = excluded.updated",
                (t.uid, t.text, t.status, t.created or dt.datetime.now().isoformat(timespec="seconds"), t.updated))
            self.store.db.commit()

    def add(self, text: str) -> Todo:
        t = Todo(new_uid(), text.strip(), "open", dt.datetime.now().isoformat(timespec="seconds"), now_ms())
        self._write(t)
        return t

    def by_uid(self, uid: str) -> Todo | None:
        rows = self._rows("uid = ?", (uid,))
        return rows[0] if rows else None

    def open(self) -> list[Todo]:
        return self._rows("status = 'open'")

    def shown(self) -> list[Todo]:
        """Open ones, then ones ticked in the last week (until cleared)."""
        since = int((dt.datetime.now() - dt.timedelta(days=DONE_SHOWN_DAYS)).timestamp() * 1000)
        return self.open() + self._rows("status = 'done' AND updated >= ?", (since,))

    def set_status(self, uid: str, status: str) -> Todo | None:
        t = self.by_uid(uid)
        if t is None:
            return None
        t.status, t.updated = status, now_ms()
        self._write(t)
        return t

    def find(self, description: str, status: str = "open") -> Todo | None:
        """Best match for 'the milk one' among open (or done) todos: words first, then meaning."""
        items = self._rows("status = ?", (status,))
        if not items:
            return None
        if len(items) == 1:
            return items[0]
        words = set(re.findall(r"[a-z0-9]{3,}", description.lower()))
        hits = [t for t in items if words & set(re.findall(r"[a-z0-9]{3,}", t.text.lower()))]
        if len(hits) == 1:
            return hits[0]
        pool = hits or items
        embedder = getattr(self.store, "embedder", None)
        if embedder is None:
            return pool[0]
        vecs = embedder.embed([description] + [t.text for t in pool])
        return pool[int((vecs[1:] @ vecs[0]).argmax())]

    def clear(self, which: str = "done") -> int:
        """Delete ticked todos ("done") or every todo ("all"). Returns how many."""
        rows = self._rows("status = 'done'" if which == "done" else "status != 'deleted'")
        for t in rows:
            t.status, t.updated = "deleted", now_ms()
            self._write(t)
        return len(rows)

    def for_sync(self, recent_days: int = 14) -> list[Todo]:
        """What the phone should hold: open, recently ticked, and recently deleted ones (so it drops them)."""
        recent = int((dt.datetime.now() - dt.timedelta(days=recent_days)).timestamp() * 1000)
        return self._rows("status = 'open' OR updated >= ?", (recent,))

    def apply_sync(self, item: dict) -> Todo | None:
        from .sync import wins

        uid = str(item.get("uid") or "")
        text = str(item.get("text") or "").strip()
        if not uid or not text:
            return None
        status = item.get("status") if item.get("status") in ("open", "done", "deleted") else "open"
        incoming = Todo(uid, text, status, str(item.get("created") or "") or dt.datetime.now().isoformat(timespec="seconds"),
                        int(item.get("updated_ms") or now_ms()))
        ours = self.by_uid(uid)
        as_sync = lambda t: {"status": "cancelled" if t.status == "deleted" else "pending", "updated_ms": t.updated}
        if ours is None or wins(as_sync(incoming), as_sync(ours)):
            if ours is not None:
                incoming.updated = max(incoming.updated, ours.updated)
                incoming.created = ours.created
            self._write(incoming)
        return self.by_uid(uid)

    def spoken(self, limit: int = 8) -> str:
        items = self.open()
        if not items:
            return "Your todo list is empty."
        more = f", and {len(items) - limit} more" if len(items) > limit else ""
        return (f"You have {len(items)} thing{'s' if len(items) != 1 else ''} on your list: "
                + "; ".join(t.text for t in items[:limit]) + more + ".")
