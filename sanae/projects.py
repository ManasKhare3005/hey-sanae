"""Alex's code projects: which git repos there are, which one they're working in, what changed,
what GitHub says (issues, pull requests, CI via the gh CLI), what's running, and dev servers she
starts herself (so she can read their output).

Changes to a project are not made here: they go to Claude Code through devloop.DevLoop, which
works on its own branch and waits for an OK before merging.
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT

log = logging.getLogger(__name__)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GH_PORTABLE = Path("C:/max-android/gh/bin/gh.exe")
LOGS = ROOT / "data" / "run-logs"
CODE_APPS = ("code.exe", "cursor.exe", "windowsterminal.exe", "pycharm64.exe", "idea64.exe", "webstorm64.exe",
             "studio64.exe", "devenv.exe", "powershell.exe", "pwsh.exe", "cmd.exe", "wezterm-gui.exe")
ERROR_LINE = re.compile(r"\b(error|exception|traceback|failed|fatal|unhandled|cannot find|not found|not recognized|eaddrinuse|"
                        r"panic|segfault|refused)\b", re.I)


@dataclass
class Project:
    name: str
    path: Path

    @property
    def slug(self) -> str:
        return norm(self.name) or "project"


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def run(cmd: list[str], cwd: Path | None = None, timeout: float = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def ago(seconds: float) -> str:
    s = max(0, int(seconds))
    for unit, size in (("year", 365 * 86400), ("month", 30 * 86400), ("week", 7 * 86400), ("day", 86400),
                       ("hour", 3600), ("minute", 60)):
        if s >= size:
            n = s // size
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def find_gh() -> str | None:
    found = shutil.which("gh")
    if found:
        return found
    return str(GH_PORTABLE) if GH_PORTABLE.exists() else None


def github_slug(remote: str) -> str | None:
    """owner/repo from an origin URL (https or ssh), or None if it isn't GitHub."""
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", remote.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def from_title(title: str, projects: list[Project]) -> Project | None:
    """The project an editor or terminal title names: VS Code shows 'file - Folder - Visual Studio
    Code', terminals the path. The longest matching name wins (so 'focus-react' beats 'focus')."""
    if not title:
        return None
    low = title.lower()
    tokens = {norm(t) for t in re.split(r"[\s\-—|:\\/()\[\]]+", low) if t}
    best = None
    for p in projects:
        key = norm(p.name)
        hit = key in tokens or str(p.path).lower() in low or (len(key) > 4 and key in norm(low))
        if hit and (best is None or len(key) > len(norm(best.name))):
            best = p
    return best


class Projects:
    def __init__(self, roots: list[Path], aliases: dict[str, str] | None = None, run_commands: dict[str, str] | None = None,
                 foreground=None, gh: str | None = None):
        self.roots = [Path(r) for r in roots]
        self.aliases = {norm(k): v for k, v in (aliases or {}).items()}     # "san ai" -> "jarvis"
        self.run_commands = {norm(k): v for k, v in (run_commands or {}).items()}
        self.foreground = foreground          # () -> (exe, title)
        self.gh = gh if gh is not None else find_gh()
        self._cache: tuple[float, list[Project]] = (0.0, [])
        self._started: dict[str, tuple[subprocess.Popen, Path, str]] = {}   # slug -> (proc, log, command)
        self.last: Project | None = None      # the one talked about last ("is it running?")

    # ----- which projects -----
    def all(self) -> list[Project]:
        stamp, cached = self._cache
        if cached and time.monotonic() - stamp < 300:
            return cached
        found: dict[str, Project] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for d in sorted(root.iterdir()):
                if not d.is_dir() or d.name.startswith("."):
                    continue
                if (d / ".git").exists():
                    found[str(d).lower()] = Project(d.name, d)
                    continue
                for sub in sorted(d.iterdir()) if d.is_dir() else []:      # e.g. Jarvis/jarvis, Chat Room/chatroom
                    try:
                        if sub.is_dir() and (sub / ".git").exists():
                            found[str(sub).lower()] = Project(d.name, sub)
                    except OSError:
                        pass
        if str(ROOT).lower() not in found:
            found[str(ROOT).lower()] = Project("Sanae", ROOT)
        else:
            found[str(ROOT).lower()].name = "Sanae"
        projects = sorted(found.values(), key=lambda p: p.name.lower())
        self._cache = (time.monotonic(), projects)
        return projects

    def find(self, name: str) -> Project | None:
        projects = self.all()
        key = norm(name)
        if not key:
            return None
        key = norm(self.aliases.get(key, key))
        for p in projects:
            if key in (norm(p.name), norm(p.path.name)):
                return p
        if key in ("sanae", "sanai", "sanay", "you", "yourself", "jarvis", "sanaeai", "sanai"):
            return next((p for p in projects if p.path == ROOT), None)
        names = {norm(p.name): p for p in projects} | {norm(p.path.name): p for p in projects}
        close = difflib.get_close_matches(key, list(names), n=1, cutoff=0.72)
        if close:
            return names[close[0]]
        part = [p for k, p in names.items() if len(key) >= 4 and (key in k or k in key)]
        return part[0] if len(set(id(p) for p in part)) == 1 else None

    def mentioned(self, text: str) -> Project | None:
        """A project named in what they said ("is Flock up?"), as a whole word; short or common names
        (under 4 letters) don't count."""
        words = {norm(w) for w in re.findall(r"[\w-]+", text.lower())}
        joined = norm(text)
        for p in sorted(self.all(), key=lambda x: -len(x.name)):
            key = norm(p.name)
            if len(key) >= 4 and p.path != ROOT and (key in words or ("-" in p.name or " " in p.name or "_" in p.name)
                                                    and key in joined):
                return p
        return None

    def current(self) -> Project | None:
        """The project in front (editor/terminal title), else the one with the newest git activity."""
        projects = self.all()
        if self.foreground is not None:
            try:
                exe, title = self.foreground()
            except Exception:
                exe, title = "", ""
            if exe.lower() in CODE_APPS or "visual studio code" in title.lower():
                hit = from_title(title, projects)
                if hit:
                    return hit
        def touched(p: Project) -> float:
            stamps = []
            for f in (".git/index", ".git/logs/HEAD", ".git/FETCH_HEAD"):
                try:
                    stamps.append((p.path / f).stat().st_mtime)
                except OSError:
                    pass
            return max(stamps, default=0.0)
        return max(projects, key=touched, default=None)

    def resolve(self, name: str = "") -> Project | str:
        """The project meant, or a sentence to say instead. Blank = 'it' / the current one."""
        name = (name or "").strip()
        if name.lower() in ("", "it", "this", "this project", "current", "the current one", "my project", "that"):
            p = self.last if name.lower() in ("it", "that") and self.last else self.current()
        else:
            p = self.find(name)
        if p is None:
            names = ", ".join(x.name for x in self.all())
            return f"I don't see a project called {name}. Your projects: {names}." if name else "I can't tell which project you mean."
        self.last = p
        return p

    def listing(self) -> str:
        cur = self.current()
        names = [p.name + (" (open now)" if cur and p.path == cur.path else "") for p in self.all()]
        return f"{len(names)} projects: " + ", ".join(names) + "."

    # ----- git -----
    def git(self, p: Project, *args: str, timeout: float = 30) -> str:
        code, out = run(["git", *args], p.path, timeout)
        return out if code == 0 else ""

    def status(self, p: Project, days: int = 0) -> str:
        branch = self.git(p, "rev-parse", "--abbrev-ref", "HEAD") or "?"
        dirty = [l for l in self.git(p, "status", "--porcelain").splitlines() if l.strip()]
        lines = [f"{p.name} is on branch {branch}" + (f" with {len(dirty)} uncommitted file{'s' if len(dirty) != 1 else ''}"
                                                       if dirty else ", nothing uncommitted") + "."]
        counts = self.git(p, "rev-list", "--left-right", "--count", "@{u}...HEAD")
        if counts:
            behind, ahead = (int(x) for x in counts.split()[:2])
            if ahead or behind:
                lines.append(f"{ahead} commit(s) not pushed, {behind} not pulled (as of the last fetch).")
        span = [f"--since={days} days ago", "-n30"] if days else ["-n3"]
        log_out = self.git(p, "log", *span, "--format=%s|%ct|%an")
        commits = []
        for row in log_out.splitlines():
            parts = row.rsplit("|", 2)
            if len(parts) == 3:
                commits.append(f"'{parts[0][:80]}' ({ago(time.time() - int(parts[1]))})")
        if commits:
            head = f"{len(commits)} commit(s) in the last {days} days" if days else "Latest commits"
            lines.append(head + ": " + "; ".join(commits[:5]) + ("; and more." if len(commits) > 5 else "."))
        elif days:
            lines.append(f"No commits in the last {days} days.")
        return " ".join(lines)

    # ----- GitHub -----
    def github(self, p: Project) -> str:
        slug = github_slug(self.git(p, "remote", "get-url", "origin"))
        if not slug:
            return f"{p.name} isn't on GitHub (no GitHub remote)."
        if not self.gh:
            return "GitHub isn't set up: the gh tool isn't installed."
        out = [f"GitHub {slug}:"]
        issues = self._gh_json(["issue", "list", "-R", slug, "--limit", "5", "--json", "number,title"])
        if issues is None:
            return "I couldn't reach GitHub. Is gh signed in? (gh auth login)"
        out.append(f"{len(issues)} open issue(s)" + (": " + "; ".join(f"#{i['number']} {i['title'][:60]}" for i in issues) if issues else "") + ".")
        prs = self._gh_json(["pr", "list", "-R", slug, "--limit", "5", "--json", "number,title"]) or []
        if prs:
            out.append(f"{len(prs)} open pull request(s): " + "; ".join(f"#{x['number']} {x['title'][:60]}" for x in prs) + ".")
        runs = self._gh_json(["run", "list", "-R", slug, "--limit", "1", "--json", "status,conclusion,workflowName,createdAt"]) or []
        if runs:
            r = runs[0]
            state = r.get("conclusion") or r.get("status") or "?"
            out.append(f"Last CI run ({r.get('workflowName', '')}): {state}.")
        return " ".join(out)

    def repos(self) -> str:
        if not self.gh:
            return "GitHub isn't set up: the gh tool isn't installed."
        rows = self._gh_json(["repo", "list", "--limit", "30", "--json", "name,updatedAt,isPrivate"])
        if rows is None:
            return "I couldn't reach GitHub. Is gh signed in? (gh auth login)"
        rows.sort(key=lambda r: r.get("updatedAt", ""), reverse=True)
        return f"{len(rows)} repos on GitHub, newest first: " + ", ".join(
            r["name"] + (" (private)" if r.get("isPrivate") else "") for r in rows[:15]) + "."

    def _gh_json(self, args: list[str]):
        code, out = run([self.gh, *args], timeout=30)
        if code != 0:
            log.info("gh %s failed: %s", " ".join(args[:2]), out[-200:])
            return None
        try:
            return json.loads(out or "[]")
        except ValueError:
            return None

    # ----- what's running -----
    def processes(self, p: Project) -> list[dict]:
        """Processes working inside the project folder (dev servers, scripts), with ports."""
        try:
            import psutil
        except ImportError:
            return []
        root = str(p.path).lower()
        me = os.getpid()
        found = []
        for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                if proc.pid == me or proc.info["name"].lower() in CODE_APPS:
                    continue
                cmd = " ".join(proc.info["cmdline"] or [])
                cwd = ""
                try:
                    cwd = proc.cwd().lower()
                except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
                    pass
                if not (cwd.startswith(root) or root in cmd.lower()):
                    continue
                if proc.info["name"].lower() in ("git.exe", "conhost.exe", "esbuild.exe"):
                    continue
                ports = sorted({c.laddr.port for c in proc.net_connections("inet") if c.status == "LISTEN"})
                found.append({"pid": proc.pid, "name": proc.info["name"], "cmd": cmd[:120], "ports": ports,
                              "up": time.time() - (proc.info["create_time"] or time.time())})
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        # a parent and its children (npm -> node): keep the one with ports, else the oldest
        found.sort(key=lambda x: (not x["ports"], -x["up"]))
        return found[:6]

    def claude_sessions(self) -> list[tuple[Project, float]]:
        """Claude Code sessions open in a terminal (not ones Sanae started): (project, seconds open).
        Sanae can't see inside them, only which project they're in."""
        try:
            import psutil
        except ImportError:
            return []
        projects = sorted(self.all(), key=lambda p: -len(str(p.path)))
        found: dict[str, tuple[Project, float]] = {}
        for proc in psutil.process_iter(["name", "cmdline", "create_time"]):
            try:
                if (proc.info["name"] or "").lower() != "claude.exe":
                    continue
                args = proc.info["cmdline"] or []
                if "-p" in args or "--print" in args or any(a.startswith("--chrome") for a in args):
                    continue                              # devloop's own jobs, the browser helper
                cwd = proc.cwd().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
            if "\\data\\dev-worktree" in cwd or "\\data\\code-work" in cwd:
                continue
            for p in projects:
                root = str(p.path).lower()
                if cwd == root or cwd.startswith(root + "\\"):
                    up = time.time() - (proc.info["create_time"] or time.time())
                    if p.slug not in found or up > found[p.slug][1]:
                        found[p.slug] = (p, up)
                    break
        return list(found.values())

    def activity(self, p: Project) -> str:
        """What's been happening in the folder: newest edit, uncommitted files, last commit."""
        dirty = []
        for line in self.git(p, "status", "--porcelain").splitlines():
            if line.strip():
                dirty.append(line[3:].split(" -> ")[-1].strip().strip('"'))
        newest = 0.0
        for name in dirty:
            try:
                f = p.path / name
                if f.is_file():
                    newest = max(newest, f.stat().st_mtime)
            except OSError:
                continue
        parts = []
        if newest:
            parts.append(f"last file edit {ago(time.time() - newest)}")
        if dirty:
            parts.append(f"{len(dirty)} uncommitted file{'s' if len(dirty) != 1 else ''}")
        last = self.git(p, "log", "-1", "--format=%s|%ct").rsplit("|", 1)
        if len(last) == 2 and last[1].strip().isdigit():
            parts.append(f"last commit '{last[0][:80]}' {ago(time.time() - int(last[1]))}")
        return ", ".join(parts)

    def running(self, p: Project) -> str:
        procs = self.processes(p)
        mine = self._started.get(p.slug)
        if mine and mine[0].poll() is not None:
            code = mine[0].returncode
            tail = self.errors(p)
            return f"{p.name} stopped (exit code {code})." + (f" Last errors: {tail}" if tail else "")
        if not procs:
            return f"Nothing from {p.name} is running."
        parts = []
        for x in procs[:3]:
            port = f" on port {', '.join(map(str, x['ports']))}" if x["ports"] else ""
            parts.append(f"{x['name']}{port}, up {ago(x['up']).replace(' ago', '')}")
        out = f"{p.name} is running: " + "; ".join(parts) + "."
        if mine:
            errs = self.errors(p)
            out += f" Recent errors in its output: {errs}" if errs else " No errors in its output."
        else:
            out += " I didn't start it, so I can't see its output."
        return out

    # ----- dev servers she starts -----
    def run_command(self, p: Project) -> str | None:
        if p.slug in self.run_commands:
            return self.run_commands[p.slug]
        pkg = p.path / "package.json"
        if pkg.exists():
            try:
                scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
            except ValueError:
                scripts = {}
            for s in ("dev", "start", "serve"):
                if s in scripts:
                    return f"npm run {s}"
        for f in ("manage.py",):
            if (p.path / f).exists():
                return "python manage.py runserver"
        for f in ("app.py", "main.py", "server.py"):
            if (p.path / f).exists():
                return f"python {f}"
        return None

    def start(self, p: Project, command: str = "") -> str:
        mine = self._started.get(p.slug)
        if mine and mine[0].poll() is None:
            return f"{p.name} is already running ({mine[2]})."
        cmd = command.strip() or self.run_command(p)
        if not cmd:
            return f"I don't know how to start {p.name}. Tell me the command, like 'npm run dev'."
        LOGS.mkdir(parents=True, exist_ok=True)
        logfile = LOGS / f"{p.slug}.log"
        handle = open(logfile, "w", encoding="utf-8", errors="replace")
        env = {**os.environ, "FORCE_COLOR": "0", "NO_COLOR": "1", "BROWSER": "none"}
        venv = next((p.path / v / "Scripts" for v in (".venv", "venv", "env") if (p.path / v / "Scripts").exists()), None)
        if venv is not None:
            env["PATH"] = f"{venv};{env.get('PATH', '')}"
            env["VIRTUAL_ENV"] = str(venv.parent)
        # a string, not a list: list quoting would escape the command's own quotes for cmd
        proc = subprocess.Popen(f'cmd /s /c "{cmd}"', cwd=str(p.path), stdout=handle, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW)
        self._started[p.slug] = (proc, logfile, cmd)
        return f"Started {p.name} with '{cmd}'. Ask me if it's running or if there are errors."

    def stop(self, p: Project) -> str:
        mine = self._started.pop(p.slug, None)
        if not mine or mine[0].poll() is not None:
            return f"I didn't start {p.name}, or it already stopped. Close it where it's running."
        try:
            import psutil

            parent = psutil.Process(mine[0].pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except Exception:
            mine[0].kill()
        return f"Stopped {p.name}."

    def output(self, p: Project, lines: int = 60) -> str:
        mine = self._started.get(p.slug)
        logfile = mine[1] if mine else LOGS / f"{p.slug}.log"
        if not logfile.exists():
            return ""
        text = logfile.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
        return "\n".join(text.splitlines()[-lines:])

    def errors(self, p: Project) -> str:
        out = self.output(p, 200).splitlines()
        hits = [i for i, l in enumerate(out) if ERROR_LINE.search(l)]
        if not hits:
            return ""
        first = max(0, hits[-1] - 6)
        return " | ".join(l.strip() for l in out[first:hits[-1] + 4] if l.strip())[:700]

    # ----- small git actions -----
    def pull(self, p: Project) -> str:
        code, out = run(["git", "pull", "--ff-only"], p.path, timeout=120)
        if code != 0:
            return f"Couldn't pull {p.name}: {out.splitlines()[-1][:200] if out else 'git failed'}."
        return f"{p.name} is up to date." if "Already up to date" in out else f"Pulled the latest {p.name}."

    def push(self, p: Project) -> str:
        branch = self.git(p, "rev-parse", "--abbrev-ref", "HEAD")
        code, out = run(["git", "push", "origin", branch], p.path, timeout=180)
        if code != 0:
            return f"Push failed for {p.name}: {out.splitlines()[-1][:200] if out else 'git failed'}."
        return f"Pushed {p.name} ({branch}) to GitHub."
