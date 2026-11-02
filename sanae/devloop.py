"""Change Sanae, or any of Alex's projects: a request (typed in the phone app's Settings, or said
to her: "ask Claude to fix the login bug in Flock") is handed to Claude Code on this laptop, which
implements it on its own git branch in a separate work copy. Sanae then runs the tests, builds the
dashboard / phone app if they changed (Sanae only), and reports back. Nothing reaches the
project's branch until the change is approved; pushing to GitHub is a separate, confirmed step.

    request -> worktree on branch phone/<id> (data/dev-worktree, so the running Sanae and the
               main checkout are untouched) -> `claude -p` (edits allowed, shell limited to
               tests/builds/read-only git) -> commit -> pytest -> npm build / gradle build
            -> "ready" (phone shows summary, tests, Approve / Reject)
    approve -> merge into main -> rebuild the dashboard -> publish the APK for the phone's
               Update button -> restart Sanae in background mode
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .config import ROOT

log = logging.getLogger(__name__)
DATA = ROOT / "data"
WORKTREE = DATA / "dev-worktree"          # Sanae's own changes
CODE_WORK = DATA / "code-work"            # other projects: data/code-work/<project>
JOBS_FILE = DATA / "dev-jobs.json"
APK_DIR = DATA / "app"
APK = APK_DIR / "sanae.apk"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROMPT = """Alex sent this change request for Sanae from the phone:

\"\"\"{request}\"\"\"

Implement it completely in this repository. Read CLAUDE.md first and follow its conventions.
You are in a git worktree on the branch {branch}; work only here. The Python tests run with:
  .venv/Scripts/python -m pytest -q
Add or update tests for what you change and make sure they pass. If you change the dashboard,
check it builds with `npm run build` in dashboard/. Don't commit, push, touch secrets.yaml, or
edit files outside this folder. If the request is unclear or unsafe, change nothing and explain.

Finish with a short summary for a phone screen (2-5 plain sentences, no markdown): what you
changed and anything Alex must do (e.g. say a new phrase, install the app update)."""

PROJECT_PROMPT = """Alex asked Sanae (their assistant) to have this change made in their project {project}:

\"\"\"{request}\"\"\"

Implement it completely in this repository. Read CLAUDE.md / README first if there is one and follow
the project's conventions. You are in a git worktree on the branch {branch}; work only here. Add or
update tests if the project has them and make sure they pass{tests}. Don't commit, push, touch .env /
secret files, or edit files outside this folder. If the request is unclear or unsafe, change nothing
and explain.

Finish with a short summary she can read aloud (2-4 plain sentences, no markdown, no file paths):
what you changed and anything Alex must do."""

ALLOWED_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep", "TodoWrite",
    "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)", "Bash(git show*)",
    "Bash(ls*)", "Bash(cat*)", "Bash(head*)", "Bash(tail*)", "Bash(grep*)", "Bash(find*)", "Bash(wc*)",
    "Bash(npm run build*)", "Bash(cd dashboard && npm run build*)", "Bash(npx tsc*)",
    "Bash(.venv/Scripts/python -m pytest*)", "Bash(.venv/Scripts/python.exe -m pytest*)",
]
PROJECT_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep", "TodoWrite",
    "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)", "Bash(git show*)",
    "Bash(ls*)", "Bash(cat*)", "Bash(head*)", "Bash(tail*)", "Bash(grep*)", "Bash(find*)", "Bash(wc*)",
    "Bash(npm test*)", "Bash(npm run test*)", "Bash(npm run build*)", "Bash(npm run lint*)", "Bash(npx tsc*)",
    "Bash(npx vitest*)", "Bash(npx jest*)", "Bash(python -m pytest*)", "Bash(pytest*)",
    "Bash(.venv/Scripts/python -m pytest*)", "Bash(venv/Scripts/python -m pytest*)",
    "Bash(gh issue view*)", "Bash(gh issue list*)", "Bash(gh pr view*)", "Bash(gh pr list*)", "Bash(gh run view*)",
]
DENIED_TOOLS = ["Bash(git push*)", "Bash(git commit*)", "Bash(git reset*)", "Bash(git checkout*)", "Bash(rm *)",
                "Bash(curl*)", "Bash(powershell*)", "WebFetch", "WebSearch"]


@dataclass
class Job:
    id: int
    request: str
    status: str = "queued"     # queued, working, testing, building, ready, failed, merged, rejected
    created: float = field(default_factory=time.time)
    branch: str = ""
    progress: list[str] = field(default_factory=list)     # recent steps, e.g. "Editing agent.py"
    summary: str = ""
    files: list[str] = field(default_factory=list)
    tests: str = ""            # "129 passed" / failure tail
    tests_ok: bool = False
    apk: bool = False          # a new phone app was built for this change
    error: str = ""
    project: str = "Sanae"
    repo: str = ""             # the project's folder ("" = Sanae)
    base: str = "main"         # the branch it merges into
    pushed: bool = False

    @property
    def path(self) -> Path:
        return Path(self.repo) if self.repo else ROOT

    @property
    def is_sanae(self) -> bool:
        return self.path.resolve() == ROOT.resolve()

    @property
    def worktree(self) -> Path:
        if self.is_sanae:
            return WORKTREE
        return CODE_WORK.resolve() / (re.sub(r"[^a-z0-9]+", "-", self.project.lower()).strip("-") or "project")


SHARED = (".venv", "dashboard/node_modules", "models")      # junctions into the main checkout
JUNK = re.compile(r"(^|/)(__pycache__|\.pytest_cache|node_modules|\.mypy_cache|\.ruff_cache)/|\.py[co]$|(^|/)\.DS_Store$")


def shared_dirs(repo: Path) -> list[str]:
    """Big gitignored folders a work copy borrows from the project as junctions: Sanae's fixed list,
    or a project's node_modules (top level and one folder down) and its virtualenv."""
    if repo.resolve() == ROOT.resolve():
        return list(SHARED)
    found = [v for v in (".venv", "venv", "env") if (repo / v / "Scripts").exists() or (repo / v / "bin").exists()]
    if (repo / "node_modules").is_dir():
        found.append("node_modules")
    try:
        for d in sorted(repo.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name != "node_modules" and (d / "node_modules").is_dir():
                found.append(f"{d.name}/node_modules")
    except OSError:
        pass
    return found


def unlink_junctions(path: Path):
    """rmdir every junction in the top two levels of a work copy (rmdir on a junction removes only
    the link), so deleting the copy can never recurse into a real .venv, node_modules or models."""
    for rel in SHARED:
        link = path / rel
        if os.path.lexists(link) and is_junction(link):
            os.rmdir(link)
    for d in list(path.iterdir()) if path.exists() else []:
        if is_junction(d):
            os.rmdir(d)
            continue
        if d.is_dir() and not d.name.startswith(".git"):
            try:
                for sub in list(d.iterdir()):
                    if is_junction(sub):
                        os.rmdir(sub)
            except OSError:
                pass


def remove_worktree(path: Path = WORKTREE, repo: Path = ROOT):
    """Delete a work copy (links first, see unlink_junctions)."""
    unlink_junctions(path)
    if path == WORKTREE:
        for rel in SHARED:
            if (path / rel).exists():
                raise RuntimeError(f"{path / rel} isn't a link; not deleting the work copy automatically")
    if path.exists():
        run(["git", "worktree", "remove", "--force", str(path)], repo)
        shutil.rmtree(path, ignore_errors=True)
    run(["git", "worktree", "prune"], repo)


def test_command(repo: Path) -> list[str] | None:
    """How a project's tests run, or None when it has none we can find."""
    if repo.resolve() == ROOT.resolve():
        return [str(VENV_PY), "-m", "pytest", "-q"]
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            test = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {}).get("test", "")
        except ValueError:
            test = ""
        if test and "no test specified" not in test:
            return ["cmd", "/c", "npm", "test", "--silent"]
    if (repo / "tests").is_dir() or (repo / "pytest.ini").exists() or any(repo.glob("test_*.py")):
        for v in (".venv", "venv", "env"):
            py = repo / v / "Scripts" / "python.exe"
            if py.exists():
                return [str(py), "-m", "pytest", "-q"]
        return [str(VENV_PY), "-m", "pytest", "-q"]       # no venv of its own: Sanae's has pytest
    return None


def as_shell(cmd: list[str]) -> str:
    """A test command as Claude's Bash tool would type it (forward slashes, quoted path)."""
    if cmd[0] == "cmd":
        return "npm test"
    exe = cmd[0].replace("\\", "/")
    return (f'"{exe}"' if " " in exe else exe) + " " + " ".join(cmd[1:])


def is_junction(path: Path) -> bool:
    if hasattr(os.path, "isjunction") and os.path.isjunction(path):
        return True
    return os.path.islink(path)


def find_claude() -> str:
    """The Claude Code executable. npm installs a .cmd shim; call the real claude.exe behind it,
    because cmd.exe would mangle arguments."""
    found = shutil.which("claude") or "claude"
    exe = Path(found).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    return str(exe) if found.lower().endswith((".cmd", ".ps1")) or not Path(found).suffix and exe.exists() else found


def run(cmd: list[str], cwd: Path, timeout: float = 900, env: dict | None = None) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=NO_WINDOW, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def git(*args: str, cwd: Path = ROOT) -> str:
    code, out = run(["git", *args], cwd, timeout=120)
    if code != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.strip()[-300:]}")
    return out.strip()


def clashes(porcelain: str, files: list[str]) -> list[str]:
    """Files of a change that the main checkout has unsaved edits to, from raw (unstripped)
    `git status --porcelain` output. Untracked files count too (the merge would refuse to
    overwrite them); an untracked folder shows as 'dir/' and covers everything inside it."""
    dirty = set()
    for line in porcelain.splitlines():
        if len(line) > 3:
            dirty.update(p.strip().strip('"') for p in line[3:].split(" -> "))
    return sorted(f for f in files if f in dirty or any(d.endswith("/") and f.startswith(d) for d in dirty))


def describe_tool(name: str, args: dict) -> str:
    """One line for the phone: what Claude is doing right now."""
    path = Path(str(args.get("file_path") or args.get("path") or "")).name
    if name in ("Edit", "Write", "MultiEdit"):
        return f"Editing {path}"
    if name == "Read":
        return f"Reading {path}"
    if name in ("Grep", "Glob"):
        return f"Searching for {str(args.get('pattern', ''))[:40]}"
    if name == "Bash":
        cmd = str(args.get("command", ""))
        return "Running the tests" if "pytest" in cmd else "Building the dashboard" if "npm" in cmd else f"Running {cmd[:50]}"
    return name


class DevLoop:
    def __init__(self, on_event: Callable[[str, dict], None] | None = None, claude: str | None = None,
                 model: str = "", timeout_min: float = 40, restart: Callable[[], None] | None = None):
        self.on_event = on_event or (lambda kind, data: None)
        self.claude = claude or find_claude()
        self.model = model
        self.timeout = timeout_min * 60
        self.restart = restart or (lambda: None)        # restart Sanae after a merge (set by main)
        self.on_done: Callable[[Job], None] | None = None   # voice mode: say it when a change is ready / failed
        self.jobs: list[Job] = self._load()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        for j in self.jobs:                              # Sanae restarted mid-job
            if j.status in ("queued", "working", "testing", "building"):
                j.status, j.error = "failed", "Sanae restarted while this was running."
        self._save()

    # ----- persistence -----
    def _load(self) -> list[Job]:
        try:
            return [Job(**j) for j in json.loads(JOBS_FILE.read_text(encoding="utf-8"))]
        except Exception:
            return []

    def _save(self):
        DATA.mkdir(exist_ok=True)
        JOBS_FILE.write_text(json.dumps([asdict(j) for j in self.jobs[-30:]], indent=1), encoding="utf-8")

    def _update(self, job: Job, **changes):
        with self._lock:
            for k, v in changes.items():
                setattr(job, k, v)
            self._save()
        self.on_event("devjob", {"id": job.id, "status": job.status, "step": (job.progress or [""])[-1],
                                 "request": job.request[:80], "project": job.project})
        if changes.get("status") in ("ready", "failed") and self.on_done is not None:
            try:
                self.on_done(job)
            except Exception:
                log.exception("dev job notice failed")

    def list(self) -> list[dict]:
        with self._lock:
            return [asdict(j) for j in reversed(self.jobs[-15:])]

    def get(self, job_id: int) -> Job:
        for j in self.jobs:
            if j.id == job_id:
                return j
        raise KeyError(job_id)

    @property
    def busy(self) -> Job | None:
        return next((j for j in self.jobs if j.status in ("queued", "working", "testing", "building")), None)

    # ----- a new request -----
    def latest(self, project: str = "") -> Job | None:
        """The newest job (for one project, if named)."""
        jobs = [j for j in self.jobs if not project or j.project.lower() == project.lower()]
        return jobs[-1] if jobs else None

    def waiting(self, project: str = "") -> Job | None:
        """The newest change waiting for an OK (for one project, if named)."""
        return next((j for j in reversed(self.jobs) if j.status == "ready" and
                     (not project or j.project.lower() == project.lower())), None)

    def submit(self, request: str, project: str = "Sanae", repo: Path | None = None) -> Job:
        request = request.strip()
        if len(request) < 5:
            raise ValueError("Describe the change in a few words.")
        repo = Path(repo).resolve() if repo else ROOT       # long form: Claude Code balks at 8.3 names (MANASK~1)
        sanae = repo == ROOT.resolve()
        base = "main"
        if not sanae:
            code, out = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo, timeout=30)
            if code != 0 or not out.strip() or out.strip() == "HEAD":
                raise RuntimeError(f"{project} isn't on a branch right now, so I can't start a change there.")
            base = out.strip()
        with self._lock:
            if self.busy is not None:
                raise RuntimeError(f"Claude is still working on the last request (in {self.busy.project}).")
            if any(j.status == "ready" and j.path.resolve() == repo.resolve() for j in self.jobs):
                raise RuntimeError(f"Approve or reject the finished change in {'Sanae' if sanae else project} first.")
            job = Job(id=max((j.id for j in self.jobs), default=0) + 1, request=request,
                      project="Sanae" if sanae else project, repo="" if sanae else str(repo), base=base)
            job.branch = f"{'phone' if sanae else 'sanae'}/{job.id}-{time.strftime('%Y%m%d-%H%M')}"
            self.jobs.append(job)
            self._save()
        threading.Thread(target=self._work, args=(job,), name="dev-job", daemon=True).start()
        return job

    def _step(self, job: Job, text: str):
        self._update(job, progress=(job.progress + [text])[-8:])

    def _work(self, job: Job):
        try:
            self._update(job, status="working")
            self._prepare(job)
            self._run_claude(job)
            changed = self._commit(job)
            if not changed:
                self._update(job, status="failed", error="Claude didn't change anything. " + job.summary[:200])
                self._cleanup(job, delete_branch=True)
                return
            self._update(job, status="testing", files=changed)
            tests = test_command(job.path)
            if tests is None:
                self._update(job, tests_ok=True, tests="no tests in this project")
            else:
                self._step(job, "Running all tests")
                code, out = run(tests, job.worktree, timeout=900)
                tail = [l for l in out.strip().splitlines() if l.strip()] or ["(no output)"]
                self._update(job, tests_ok=code == 0, tests=(tail[-1] if code == 0 else "\n".join(tail[-12:]))[:1500])
            if not job.is_sanae:
                self._step(job, "Ready for your OK")
                self._update(job, status="ready")
                return
            self._update(job, status="building")
            if any(f.startswith("dashboard/") for f in changed):
                self._step(job, "Building the dashboard")
                code, out = run(["cmd", "/c", "npm", "run", "build"], WORKTREE / "dashboard", timeout=600)
                if code != 0:
                    raise RuntimeError("dashboard build failed: " + out.strip()[-400:])
            if any(f.startswith("android/") for f in changed):
                self._step(job, "Building the phone app (a few minutes)")
                self._build_apk(job)
            self._update(job, status="ready")
            self._step(job, "Ready for your OK")
        except Exception as exc:
            if job.status != "rejected":                 # rejected from the phone while running
                log.exception("dev job %s failed", job.id)
                self._update(job, status="failed", error=str(exc)[:600])
            self._cleanup(job, delete_branch=True)
        finally:
            self._proc = None

    def _prepare(self, job: Job):
        self._step(job, "Setting up a separate copy of the code")
        repo, work = job.path, job.worktree
        work.parent.mkdir(parents=True, exist_ok=True)
        remove_worktree(work, repo)
        git("worktree", "add", "-b", job.branch, str(work), job.base, cwd=repo)
        # Big, gitignored folders are shared with the main checkout instead of copied
        for rel in shared_dirs(repo):
            src, dst = repo / rel, work / rel
            if src.exists() and not dst.exists() and dst.parent.exists():
                run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], repo)
        # Gitignored but needed: the project notes for Claude, settings to run tests and builds
        extra = ("CLAUDE.md", "secrets.yaml", "android/local.properties") if job.is_sanae else ("CLAUDE.md", "local.properties")
        for rel in extra:
            if (repo / rel).exists() and not (work / rel).exists():
                shutil.copy2(repo / rel, work / rel)

    def _run_claude(self, job: Job):
        self._step(job, "Claude is reading the code")
        if job.is_sanae:
            prompt, allowed = PROMPT.format(request=job.request, branch=job.branch), ALLOWED_TOOLS
        else:
            tests = test_command(job.path)
            hint = f" (run them with exactly: {as_shell(tests)})" if tests else ""
            prompt = PROJECT_PROMPT.format(request=job.request, branch=job.branch, project=job.project, tests=hint)
            allowed = PROJECT_TOOLS + ([f"Bash({as_shell(tests)}*)"] if tests else [])
        cmd = [self.claude, "-p", "--output-format", "stream-json", "--verbose",
               "--permission-mode", "acceptEdits", "--allowedTools", *allowed,
               "--disallowedTools", *DENIED_TOOLS]
        if self.model:
            cmd += ["--model", self.model]
        env = {**os.environ, "SANAE_DEV_JOB": str(job.id)}
        self._proc = subprocess.Popen(cmd, cwd=str(job.worktree), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      stdin=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                      creationflags=NO_WINDOW, env=env)
        self._proc.stdin.write(prompt)                   # via stdin: no quoting trouble with the request
        self._proc.stdin.close()
        killer = threading.Timer(self.timeout, self._proc.kill)
        killer.start()
        result, other = "", []
        try:
            for line in self._proc.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    other.append(line.strip())
                    continue
                if msg.get("type") == "assistant":
                    for part in (msg.get("message") or {}).get("content") or []:
                        if part.get("type") == "tool_use":
                            self._step(job, describe_tool(part.get("name", ""), part.get("input") or {}))
                elif msg.get("type") == "result":
                    result = str(msg.get("result") or "")
                    if msg.get("is_error"):
                        raise RuntimeError("Claude stopped: " + result[:400])
            self._proc.wait()
        finally:
            killer.cancel()
        if self._proc.returncode not in (0, None) and not result:
            raise RuntimeError("Claude Code failed: " + " ".join(other)[-400:] if other else
                               f"Claude Code exited with code {self._proc.returncode} (timed out?)")
        self._update(job, summary=result.strip()[:2000])

    def _commit(self, job: Job) -> list[str]:
        work = job.worktree
        status = git("status", "--porcelain", cwd=work)          # links, CLAUDE.md, secrets: gitignored
        if not status:
            return []
        # a project may not gitignore its node_modules / venv: never commit the borrowed links
        links = [rel for rel in shared_dirs(job.path) if (work / rel).exists()
                 and run(["git", "check-ignore", "-q", rel], work)[0] != 0] if not job.is_sanae else []
        git("add", "-A", "--", ".", *[f":(exclude){rel}" for rel in links], cwd=work)
        if not job.is_sanae and (job.path / "CLAUDE.md").exists() and \
                run(["git", "ls-files", "--error-unmatch", "CLAUDE.md"], job.path)[0] != 0:
            run(["git", "reset", "-q", "--", "CLAUDE.md"], work)          # copied in; not part of the project
        files = git("diff", "--cached", "--name-only", cwd=work).splitlines()
        junk = [f for f in files if JUNK.search(f)]       # a project without a .gitignore: test-run leftovers
        if junk and not job.is_sanae:
            git("reset", "-q", "--", *junk, cwd=work)
            files = [f for f in files if f not in junk]
        if not files:
            return []
        who = "Sanae (Claude, from phone)" if job.is_sanae else "Sanae (Claude)"
        title = f"Phone request: {job.request[:60]}" if job.is_sanae else job.request[:72]
        git("-c", f"user.name={who}", "-c", "user.email=sanae@localhost", "commit", "-q",
            "-m", title, "-m", f"{job.request}\n\n{job.summary}", cwd=work)
        return files

    def _build_apk(self, job: Job):
        tools = Path("C:/max-android")
        env = {**os.environ, "JAVA_HOME": str(tools / "jdk17"), "ANDROID_HOME": str(tools / "sdk")}
        code, out = run(["cmd", "/c", "gradlew.bat", "assembleRelease", "--console=plain"], WORKTREE / "android",
                        timeout=1500, env=env)
        if code != 0:
            raise RuntimeError("phone app build failed: " + out.strip()[-500:])
        built = WORKTREE / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
        APK_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, APK_DIR / f"pending-{job.id}.apk")
        self._update(job, apk=True)

    def _cleanup(self, job: Job, delete_branch: bool):
        remove_worktree(job.worktree, job.path)
        if delete_branch and job.branch:
            run(["git", "branch", "-D", job.branch], job.path)

    # ----- the decision (from the phone) -----
    def approve(self, job_id: int) -> Job:
        job = self.get(job_id)
        if job.status != "ready":
            raise RuntimeError(f"That change is {job.status}, not waiting for approval.")
        try:
            self._merge(job)
        except Exception as exc:                         # stays "ready"; the phone shows why
            log.warning("approving dev job %s failed: %s", job.id, exc)
            self._update(job, error=f"Approve failed: {str(exc)[:500]}")
            raise RuntimeError(str(exc)) from exc
        return job

    def _merge(self, job: Job):
        repo = job.path
        here = job.base if job.is_sanae else git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
        if here != job.base:
            raise RuntimeError(f"{job.project} is on the branch {here} now, not {job.base}. Switch back to "
                               f"{job.base}, then approve again.")
        code, status = run(["git", "status", "--porcelain", "--untracked-files=all"], repo, timeout=120)
        if code != 0:
            raise RuntimeError("git status: " + status.strip()[-300:])
        overlap = clashes(status, job.files)             # raw output: strip() would eat the first line's " M"
        if overlap:
            raise RuntimeError("These files have unsaved edits on the laptop: " + ", ".join(overlap[:5]) +
                               ". Commit or undo them on the laptop, then approve again.")
        self._cleanup(job, delete_branch=False)
        what = "phone request" if job.is_sanae else "Sanae's change"
        try:
            git("merge", "--no-ff", "-q", "-m", f"Merge {what} {job.id}: {job.request[:50]}", job.branch, cwd=repo)
        except RuntimeError:
            run(["git", "merge", "--abort"], repo)
            raise
        git("branch", "-d", job.branch, cwd=repo)
        if not job.is_sanae:
            self._update(job, status="merged", error="")
            return
        if any(f.startswith("dashboard/") for f in job.files):
            run(["cmd", "/c", "npm", "run", "build"], ROOT / "dashboard", timeout=600)
        pending = APK_DIR / f"pending-{job.id}.apk"
        if pending.exists():
            pending.replace(APK)
        self._update(job, status="merged", error="")
        if any(f.startswith("sanae/") or f == "config.yaml" for f in job.files):
            threading.Timer(2.0, self.restart).start()     # let the API answer first

    def push(self, job_id: int) -> Job:
        """Push a merged change to GitHub: a separate step, asked for after a yes."""
        job = self.get(job_id)
        if job.status != "merged":
            raise RuntimeError(f"That change is {job.status}; only merged changes can be pushed.")
        if job.pushed:
            raise RuntimeError("That change is already on GitHub.")
        code, out = run(["git", "push", "origin", job.base], job.path, timeout=180)
        if code != 0:
            raise RuntimeError("git push failed: " + out.strip()[-300:])
        self._update(job, pushed=True)
        return job

    def reject(self, job_id: int) -> Job:
        job = self.get(job_id)
        if job.status in ("working", "testing", "building", "queued"):
            if self._proc is not None:
                self._proc.kill()                           # _work notices and cleans up
            self._update(job, status="rejected")
            return job
        if job.status != "ready":
            raise RuntimeError(f"That change is already {job.status}.")
        self._cleanup(job, delete_branch=True)
        (APK_DIR / f"pending-{job.id}.apk").unlink(missing_ok=True)
        self._update(job, status="rejected")
        return job


def apk_info() -> dict:
    """The phone app the Update button installs (built time in ms, like the app's BuildConfig)."""
    if not APK.exists():
        return {"available": False}
    st = APK.stat()
    return {"available": True, "built": int(st.st_mtime * 1000), "size": st.st_size}


def publish_apk(path: Path) -> dict:
    """Make a freshly built APK the one the phone's Update button offers."""
    APK_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, APK)
    return apk_info()


def restart_sanae_detached():
    """Start a new background Sanae once this one has exited (the single-instance lock frees then)."""
    exe = Path(sys.executable).with_name("pythonw.exe")
    exe = exe if exe.exists() else Path(sys.executable)
    code = (f"import time, subprocess, psutil\n"
            f"try:\n    psutil.Process({os.getpid()}).wait(120)\nexcept Exception:\n    pass\n"
            f"time.sleep(2)\nsubprocess.Popen([r'{exe}', '-m', 'sanae', '--tray'], cwd=r'{ROOT}')\n")
    subprocess.Popen([str(exe), "-c", code], cwd=str(ROOT), creationflags=0x00000008 | 0x00000200,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


