"""Sanae as a plug-in for Claude Desktop (an MCP server over stdio).

Claude Desktop starts this (claude_desktop_config.json -> mcpServers.sanae) and can then see and
use Sanae's world: your day, what's coming up, what she knows about you, her diary, recent chats,
her lessons and aims; and add reminders, todos, events and memories, or message her.

  python -m sanae.mcp_server            # what Claude Desktop runs
  python -m sanae.mcp_server --install  # adds it to Claude Desktop's config (a backup is kept)

Reading goes straight to data/sanae.db, read-only, so it works even while Sanae is off. Writing
goes through her running app (127.0.0.1:8765) so the phone syncs and she knows about it.

What Claude Desktop sees still leaves the laptop, so the private things stay out: chats from a
hard moment (comfort.py) and the diary of a hard day, private notebook pages, other voices,
health numbers, and sentences about health, money, passwords, religion, politics or sexuality
(friend.SENSITIVE); emails, phone numbers, links and long numbers are masked. Names are kept:
it's you asking about your own life.

The protocol is small JSON-RPC over stdin/stdout (initialize, tools/list, tools/call), written
here by hand so Sanae needs no extra package. Nothing but protocol messages goes to stdout.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "sanae.db"
API = os.environ.get("SANAE_API", "http://127.0.0.1:8765")
NAME = "sanae"
VERSION = "1.0"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")


# ----- keeping private things private -----
def private_turns(db) -> set[int]:
    row = db.execute("SELECT value FROM kv WHERE key = 'comfort:turns'").fetchone()
    try:
        return set(json.loads(row[0])) if row else set()
    except ValueError:
        return set()


def safe(text: str) -> str:
    """Sensitive sentences out, contact details and secrets masked; names kept."""
    from .cloudbrain import EMAIL, LINK, LONG_NUMBER, PHONE, SECRET, SENTENCE
    from .friend import sensitive

    if not text:
        return ""
    kept = [s for s in SENTENCE.split(text) if s.strip() and not sensitive(s)]
    out = " ".join(kept)
    for rx, mask in ((EMAIL, "[email]"), (LINK, "[link]"), (SECRET, "[hidden]"), (PHONE, "[number]"), (LONG_NUMBER, "[number]")):
        out = rx.sub(mask, out)
    return out


# ----- reading (sanae.db, read-only) -----
def connect(path: Path | None = None):
    path = path or DB
    if not path.exists():
        raise RuntimeError("Sanae's memory isn't there yet (data/sanae.db)")
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def has_table(db, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def nice_time(iso: str) -> str:
    try:
        d = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d:%a %b} {d.day}, {d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'}"


def upcoming(db, days: int = 7, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    until = (now + dt.timedelta(days=days)).isoformat(timespec="seconds")
    out = []
    if has_table(db, "events"):
        rows = db.execute("SELECT title, start, end, all_day, location FROM events WHERE status = 'active' AND end > ? "
                          "AND start < ? ORDER BY start", (now.isoformat(timespec="seconds"), until)).fetchall()
        out += [f"- {r['title']}: " + (f"{dt.datetime.fromisoformat(r['start']):%a %b %d} (all day)" if r["all_day"]
                                       else nice_time(r["start"])) + (f" at {r['location']}" if r["location"] else "")
                for r in rows]
    if has_table(db, "reminders"):
        rows = db.execute("SELECT * FROM reminders WHERE status = 'pending' AND due < ? ORDER BY due", (until,)).fetchall()
        out += [f"- Reminder: {safe(r['text'])} ({nice_time(r['due'])}"
                + (f", repeats {r['repeat_rule']}" if "repeat_rule" in r.keys() and r["repeat_rule"] else "") + ")" for r in rows]
    if has_table(db, "todos"):
        rows = db.execute("SELECT text FROM todos WHERE status = 'open' ORDER BY created").fetchall()
        out += [f"- To do: {safe(r['text'])}" for r in rows]
    return "\n".join(out) or f"Nothing on the calendar, no reminders and no open todos in the next {days} days."


def what_she_knows(db, query: str = "") -> str:
    rows = []
    if has_table(db, "facts"):
        rows += [("You asked her to remember", r["text"]) for r in db.execute("SELECT text FROM facts ORDER BY id")]
    if has_table(db, "about"):
        rows += [(f"She learned ({r['kind']})", r["text"]) for r in db.execute("SELECT text, kind FROM about ORDER BY updated DESC")]
    words = [w for w in re.findall(r"[a-z0-9']{3,}", query.lower())]
    if words:
        rows = [r for r in rows if any(w in r[1].lower() for w in words)]
    lines = [f"- {safe(text)} [{where}]" for where, text in rows if safe(text)]
    return "\n".join(lines[:80]) or ("Nothing about that." if words else "She doesn't know much about you yet.")


def diary(db, days: int = 7, now: dt.datetime | None = None) -> str:
    if not has_table(db, "diary"):
        return "Her diary is off."
    since = ((now or dt.datetime.now()).date() - dt.timedelta(days=max(1, min(days, 60)))).isoformat()
    rows = db.execute("SELECT day, text, mood FROM diary WHERE day >= ? ORDER BY day", (since,)).fetchall()
    out = []
    for r in rows:
        if "hard" in (r["mood"] or ""):
            out.append(f"{r['day']}: (a private day, not shared)")
            continue
        text = safe(r["text"])
        if text:
            out.append(f"{r['day']}" + (f" (felt {r['mood']})" if r["mood"] else "") + f": {text}")
    note = "Her diary is written by her small local model and can get details wrong.\n\n"
    return note + "\n".join(out) if out else "No diary entries in that time."


def notebook(db, days: int = 14, now: dt.datetime | None = None) -> str:
    if not has_table(db, "journal"):
        return "The shared notebook is off."
    since = ((now or dt.datetime.now()).date() - dt.timedelta(days=max(1, min(days, 90)))).isoformat()
    rows = db.execute("SELECT id, day, author, text, private FROM journal WHERE kind = 'page' AND day >= ? ORDER BY id",
                      (since,)).fetchall()
    out, seen = [], set()
    for r in rows:
        if r["private"]:
            continue
        key = (r["author"], r["text"])
        if key in seen:
            continue
        seen.add(key)
        text = safe(r["text"])
        if text:
            out.append(f"{r['day']} ({'you' if r['author'] == 'you' else 'Sanae'}): {text}")
    return "\n".join(out) or "No shared notebook pages in that time."


def recent_chats(db, limit: int = 40, query: str = "") -> str:
    hidden = private_turns(db)
    rows = db.execute("SELECT id, ts, user, reply, heard FROM turns ORDER BY id DESC LIMIT 2000").fetchall()
    words = [w for w in re.findall(r"[a-z0-9']{3,}", query.lower())]
    out = []
    for r in rows:
        if r["id"] in hidden or (r["heard"] or "") not in ("", "you", "she"):
            continue
        both = f"{r['user']} {r['reply']}".lower()
        if words and not any(w in both for w in words):
            continue
        said, reply = safe(r["user"] or ""), safe(r["reply"] or "")
        if not said and not reply:
            continue
        line = f"[{nice_time(r['ts'])}] " + (f"You: {said} | " if said and r["heard"] != "she" else "(she started) ") + f"Sanae: {reply}"
        out.append(line)
        if len(out) >= max(1, min(limit, 200)):
            break
    return "\n".join(reversed(out)) or ("No chats mention that." if words else "No chats yet.")


def brain(db) -> str:
    out = []
    if has_table(db, "lessons"):
        rows = db.execute("SELECT text, day FROM lessons WHERE expires >= ? ORDER BY seen DESC, created DESC",
                          (dt.date.today().isoformat(),)).fetchall()
        out += ["What she's learned from past chats:"] + [f"- {r['text']} (from {r['day']})" for r in rows]
    row = db.execute("SELECT value FROM kv WHERE key = 'aims:week'").fetchone()
    if row:
        w = json.loads(row[0])
        out += [f"Her aims for {w.get('week')}:"] + [f"- {a['aim']}: " + "; ".join(a.get("ways", [])) for a in w.get("aims", [])]
    return "\n".join(out) or "No lessons or aims yet (her slow brain writes them overnight and on Mondays)."


# ----- writing (through Sanae) -----
def call_api(method: str, path: str, body: dict | None = None, timeout: float = 90) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"Sanae said no: {detail}")
    except (urllib.error.URLError, OSError):
        raise RuntimeError("Sanae isn't running on the laptop right now, so I can't change anything. Start her and try again.")


# ----- the tools -----
def S(props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or []}


STR = {"type": "string"}
INT = {"type": "integer"}
TOOLS = [
    ("sanae_today", "What's on the user's plate today and soon, from their assistant Sanae: class schedule and Canvas "
     "assignments due, events, reminders, todos. Needs Sanae running.", S()),
    ("sanae_upcoming", "Events, reminders and open todos in the next N days (default 7), from Sanae.",
     S({"days": INT})),
    ("sanae_what_she_knows", "What Sanae (the user's AI companion) knows about the user: things they asked her to remember "
     "and what she learned from chats (likes, people, plans, projects). Optional query filters by words.",
     S({"query": STR})),
    ("sanae_diary", "Sanae's diary about her days with the user (one entry per day, with how the day felt), last N days "
     "(default 7). Written by a small local model, details can be wrong.", S({"days": INT})),
    ("sanae_notebook", "The shared notebook: pages the user wrote and Sanae's replies, last N days (default 14). "
     "Private pages are never included.", S({"days": INT})),
    ("sanae_recent_chats", "Recent conversation between the user and Sanae (newest last). Optional query keeps only "
     "chats with those words. Default 40 exchanges.", S({"limit": INT, "query": STR})),
    ("sanae_brain", "Sanae's own lessons from past chats and her aims for this week.", S()),
    ("sanae_add_reminder", "Set a reminder through Sanae (rings on the user's phone and laptop). `when` in plain words: "
     "'tomorrow at 9am', 'friday 5pm', 'every month on the 5th'.", S({"text": STR, "when": STR}, ["text", "when"])),
    ("sanae_add_todo", "Add to the user's todo list in Sanae (one or more items, comma-separated).",
     S({"text": STR}, ["text"])),
    ("sanae_add_event", "Add an event to the user's Sanae calendar (synced to their phone). `when` in plain words; "
     "minutes = length.", S({"title": STR, "when": STR, "minutes": INT, "location": STR}, ["title", "when"])),
    ("sanae_remember", "Ask Sanae to remember a fact about the user (they'll see it in her memory).",
     S({"text": STR}, ["text"])),
    ("sanae_message", "Send Sanae a message as the user and get her reply (she may also act on it, e.g. 'play our "
     "playlist'). Risky actions still need the user's yes on their laptop or phone.", S({"text": STR}, ["text"])),
]


def run_tool(name: str, args: dict) -> str:
    args = args or {}
    if name == "sanae_today":
        t = call_api("GET", "/api/today", timeout=40)
        lines = [f"Today ({t.get('date')}):"]
        lines += [f"- Class: {c['title']} {c.get('when', '')}".rstrip() for c in t.get("classes", [])]
        lines += [f"- Due today: {i['title']} ({i.get('course', '')})" for i in t.get("due_today", [])]
        lines += [f"- Due soon: {i['title']} ({i.get('course', '')}, {nice_time(i['due'])})" for i in t.get("due_soon", [])]
        lines += [f"- Event: {e['title']}" + ("" if e.get("all_day") else f" at {nice_time(e['start'])}") for e in t.get("events", [])]
        lines += [f"- Reminder: {safe(r['text'])} at {nice_time(r['due'])}" for r in t.get("reminders", [])]
        lines += [f"- To do: {safe(x.get('text', ''))}" for x in t.get("todos", [])]
        return "\n".join(lines) if len(lines) > 1 else lines[0] + " nothing scheduled."
    if name == "sanae_add_reminder":
        r = call_api("POST", "/api/reminders", {"text": args["text"], "when": args["when"]})
        return f"Reminder set: {r.get('spoken') or r}"
    if name == "sanae_add_todo":
        r = call_api("POST", "/api/todos", {"text": args["text"]})
        return f"Added to the todo list: {json.dumps(r, ensure_ascii=False)[:300]}"
    if name == "sanae_add_event":
        body = {"title": args["title"], "when": args["when"], "minutes": int(args.get("minutes") or 60),
                "location": args.get("location") or ""}
        r = call_api("POST", "/api/events", body)
        return f"Event added: {json.dumps(r, ensure_ascii=False)[:300]}"
    if name == "sanae_remember":
        r = call_api("POST", "/api/facts", {"text": args["text"]})
        return "Sanae will remember that." + (" (Updated something she already knew.)" if r.get("updated") else "")
    if name == "sanae_message":
        r = call_api("POST", "/api/command", {"text": args["text"]}, timeout=180)
        return f"Sanae: {r.get('reply', '')}"
    with connect() as db:
        if name == "sanae_upcoming":
            return upcoming(db, int(args.get("days") or 7))
        if name == "sanae_what_she_knows":
            return what_she_knows(db, str(args.get("query") or ""))
        if name == "sanae_diary":
            return diary(db, int(args.get("days") or 7))
        if name == "sanae_notebook":
            return notebook(db, int(args.get("days") or 14))
        if name == "sanae_recent_chats":
            return recent_chats(db, int(args.get("limit") or 40), str(args.get("query") or ""))
        if name == "sanae_brain":
            return brain(db)
    raise KeyError(name)


# ----- the protocol -----
def handle(msg: dict) -> dict | None:
    """One JSON-RPC message -> the reply (None for notifications)."""
    mid, method = msg.get("id"), msg.get("method", "")
    if mid is None:
        return None                                       # notifications/initialized etc.
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion", PROTOCOLS[0])
        result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                  "capabilities": {"tools": {}}, "serverInfo": {"name": NAME, "version": VERSION},
                  "instructions": "Sanae is the user's local AI companion (voice assistant on their laptop and phone). "
                                  "Use these tools for their schedule, reminders, todos, and what Sanae knows about them."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]}
    elif method == "tools/call":
        p = msg.get("params") or {}
        try:
            text, error = run_tool(p.get("name", ""), p.get("arguments") or {}), False
        except KeyError as exc:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool or argument {exc}"}}
        except Exception as exc:
            text, error = str(exc), True
        result = {"content": [{"type": "text", "text": text}], "isError": error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


# ----- installing into Claude Desktop -----
def desktop_configs() -> list[Path]:
    """Claude Desktop's config: the Microsoft Store app keeps it inside its package folder."""
    out = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        out += sorted(Path(local, "Packages").glob("Claude_*/LocalCache/Roaming/Claude/claude_desktop_config.json"))
    roaming = os.environ.get("APPDATA", "")
    if roaming and Path(roaming, "Claude").exists():
        out.append(Path(roaming, "Claude", "claude_desktop_config.json"))
    return out


def install(path: Path) -> str:
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if path.exists():
        backup = path.with_name(path.name + ".before-sanae")
        if not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    cfg.setdefault("mcpServers", {})[NAME] = {"command": str(python), "args": ["-m", "sanae.mcp_server"],
                                             "cwd": str(ROOT), "env": {"PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def main():
    if "--install" in sys.argv:
        paths = desktop_configs()
        if not paths:
            print("Claude Desktop's config folder wasn't found. Is Claude Desktop installed?")
            return
        for p in paths:
            print("Added Sanae to", install(p))
        print("Quit Claude Desktop fully (tray icon -> Quit) and open it again.")
        return
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    serve()


if __name__ == "__main__":
    main()
