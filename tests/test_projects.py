"""Code projects (projects.py), Claude changes in any project (devloop.py), and their voice tools."""
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sanae import devloop
from sanae.projects import Project, Projects, from_title, github_slug

WINDOWS = sys.platform == "win32"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def make_repo(path: Path, files: dict[str, str] | None = None) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@t")
    git(path, "config", "user.name", "t")
    for rel, text in (files or {"README.md": "hi\n"}).items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "first commit")
    return path


def test_github_remote_and_window_title_parsing():
    assert github_slug("https://github.com/ManasKhare3005/San-AI.git") == "ManasKhare3005/San-AI"
    assert github_slug("git@github.com:me/flock.git") == "me/flock"
    assert github_slug("https://gitlab.com/me/flock.git") is None
    ps = [Project("Flock", Path("C:/p/Flock")), Project("focus-react", Path("C:/p/focus-react")),
          Project("Lofty", Path("C:/p/Lofty"))]
    assert from_title("App.tsx - focus-react - Visual Studio Code", ps).name == "focus-react"
    assert from_title("● server.js - Flock - Visual Studio Code", ps).name == "Flock"
    assert from_title("C:\\p\\Lofty> npm run dev", ps).name == "Lofty"
    assert from_title("YouTube - Google Chrome", ps) is None


def test_projects_are_found_matched_and_described(tmp_path):
    root = tmp_path / "My Projects"
    make_repo(root / "Flock")
    make_repo(root / "resume-builder")
    make_repo(root / "Chat Room" / "chatroom")
    (root / "notes").mkdir()                                    # not a repo: skipped
    front = {"exe": "", "title": ""}
    p = Projects([root], aliases={"chat app": "Chat Room"}, foreground=lambda: (front["exe"], front["title"]), gh="")
    names = [x.name for x in p.all()]
    assert {"Flock", "resume-builder", "Chat Room", "Sanae"} <= set(names) and "notes" not in names
    assert p.find("flock").name == "Flock"
    assert p.find("resume builder").name == "resume-builder"
    assert p.find("chat app").name == "Chat Room"
    assert p.find("yourself").name == "Sanae"
    assert p.find("banana") is None
    assert "don't see a project called banana" in p.resolve("banana")
    front.update(exe="Code.exe", title="index.js - Flock - Visual Studio Code")
    assert p.resolve("").name == "Flock"
    assert p.resolve("it").name == "Flock"                      # "is it running?" = the one just talked about
    flock = p.find("Flock")
    (flock.path / "new.js").write_text("x")
    status = p.status(flock)
    assert "on branch main with 1 uncommitted file" in status and "'first commit'" in status
    assert "isn't on GitHub" in p.github(flock)
    assert p.status(flock, days=7).count("commit(s) in the last 7 days") == 1
    assert p.running(flock) == "Nothing from Flock is running."


@pytest.mark.skipif(not WINDOWS, reason="starts a process through cmd")
def test_she_starts_a_project_and_reads_its_errors(tmp_path, monkeypatch):
    from sanae import projects as projects_mod

    monkeypatch.setattr(projects_mod, "LOGS", tmp_path / "logs")
    repo = make_repo(tmp_path / "Flock")
    p = Projects([tmp_path], gh="")
    flock = p.find("Flock")
    assert "don't know how to start" in p.start(flock)
    py = sys.executable
    out = p.start(flock, f'"{py}" -c "import sys; print(\'listening\'); sys.exit(\'Error: EADDRINUSE port 3000\')"')
    assert out.startswith("Started Flock")
    for _ in range(100):
        if p._started[flock.slug][0].poll() is not None:
            break
        time.sleep(0.05)
    said = p.running(flock)
    assert "stopped (exit code 1)" in said and "EADDRINUSE" in said
    (repo / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
    assert p.run_command(flock) == "npm run dev"


def test_test_commands_are_detected(tmp_path):
    js = tmp_path / "js"
    js.mkdir()
    (js / "package.json").write_text(json.dumps({"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}}))
    assert devloop.test_command(js) is None
    (js / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    assert devloop.test_command(js)[-2:] == ["test", "--silent"]
    py = tmp_path / "py"
    (py / "tests").mkdir(parents=True)
    assert devloop.test_command(py) == [str(devloop.VENV_PY), "-m", "pytest", "-q"]     # no venv: Sanae's
    assert devloop.as_shell(devloop.test_command(py)).endswith('python.exe" -m pytest -q')
    assert devloop.as_shell(devloop.test_command(js)) == "npm test"
    assert devloop.test_command(devloop.ROOT)[0].endswith("python.exe")


FAKE_CLAUDE = r'''
import json, sys
from pathlib import Path
sys.stdin.read()
Path("hello.txt").write_text("hello from claude\n")
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write",
      "input": {"file_path": "hello.txt"}}]}}))
print(json.dumps({"type": "result", "result": "Added a hello file. Nothing else to do."}))
'''


@pytest.mark.skipif(not WINDOWS, reason="uses directory junctions and a .bat stand-in for claude")
def test_claude_changes_a_project_on_a_branch_then_merge_and_push(tmp_path, monkeypatch):
    monkeypatch.setattr(devloop, "DATA", tmp_path / "data")
    monkeypatch.setattr(devloop, "JOBS_FILE", tmp_path / "data" / "jobs.json")
    monkeypatch.setattr(devloop, "CODE_WORK", tmp_path / "data" / "code-work")
    (tmp_path / "data").mkdir()
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    repo = make_repo(tmp_path / "Flock", {"README.md": "flock\n", ".gitignore": "node_modules/\n"})
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    (repo / "node_modules" / "left-pad").mkdir(parents=True)
    (repo / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1")
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLAUDE)
    bat = tmp_path / "claude.bat"
    bat.write_text(f'@"{sys.executable}" "{script}"\r\n')

    said = []
    loop = devloop.DevLoop(claude=str(bat))
    loop.on_done = lambda job: said.append(job.status)
    job = loop.submit("add a hello file", "Flock", repo)
    assert job.branch.startswith("sanae/") and job.base == "main"
    for _ in range(600):
        if job.status not in ("queued", "working", "testing", "building"):
            break
        time.sleep(0.1)
    assert job.status == "ready", (job.status, job.error)
    assert job.files == ["hello.txt"] and job.tests == "no tests in this project" and said == ["ready"]
    assert job.summary.startswith("Added a hello file")
    assert not (repo / "hello.txt").exists()                     # nothing touched the project yet
    with pytest.raises(RuntimeError, match="finished change in Flock"):
        loop.submit("another change", "Flock", repo)

    loop.approve(job.id)
    assert job.status == "merged" and (repo / "hello.txt").read_text() == "hello from claude\n"
    assert (repo / "node_modules" / "left-pad" / "index.js").exists()      # the borrowed folder survived cleanup
    assert not job.worktree.exists()
    branches = subprocess.run(["git", "branch"], cwd=repo, capture_output=True, text=True).stdout
    assert "sanae/" not in branches
    loop.push(job.id)
    assert job.pushed
    log = subprocess.run(["git", "log", "--oneline", "main"], cwd=remote, capture_output=True, text=True).stdout
    assert "add a hello file" in log
    with pytest.raises(RuntimeError, match="already on GitHub"):
        loop.push(job.id)


def test_code_tools_by_voice(tmp_path, monkeypatch):
    from sanae.tools import code as code_tools
    from sanae.tools.registry import ToolRegistry

    monkeypatch.setattr(devloop, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(devloop, "DATA", tmp_path)
    monkeypatch.setattr(devloop.DevLoop, "_work", lambda self, job: None)
    repo = make_repo(tmp_path / "proj" / "Flock")
    answers = []
    ctx = SimpleNamespace(projects=Projects([tmp_path / "proj"], gh=""), dev=devloop.DevLoop(),
                          confirm=lambda prompt: answers.append(prompt) or False)
    reg = ToolRegistry(context=ctx)
    code_tools.register(reg)
    assert "Claude is working on that in Flock" in reg.run("code_change", {"request": "fix the login bug", "project": "flock"})
    assert "still on it in Flock" in reg.run("code_change_status", {})
    assert "still working on it" in reg.run("approve_code_change", {})
    job = ctx.dev.latest()
    job.status, job.tests_ok, job.files, job.summary = "ready", False, ["a.js"], "Fixed the login check. Done."
    said = reg.run("code_change_status", {"project": "Flock"})
    assert "ready: Fixed the login check. Done. 1 file changed. But the tests failed." in said
    assert reg.run("approve_code_change", {}) == "Okay, I left it waiting."     # failed tests: asks, silence = no
    assert "tests failed" in answers[-1]
    assert reg.run("push_project", {"project": "Flock"}) == "Okay, I didn't push it."
    assert answers[-1] == "Push Flock (main) to GitHub?"
    assert "threw away the change in Flock" in reg.run("reject_code_change", {})
    assert "don't see a project called nope" in reg.run("project_status", {"project": "nope"})
    assert "isn't on GitHub" not in reg.run("project_status", {"project": "Flock", "what": "commits"})


def test_status_mentions_claude_open_in_a_terminal(tmp_path, monkeypatch):
    from sanae.tools import code as code_tools
    from sanae.tools.registry import ToolRegistry

    monkeypatch.setattr(devloop, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(devloop, "DATA", tmp_path)
    repo = make_repo(tmp_path / "proj" / "Flock")
    (repo / "new.py").write_text("x = 1\n")
    projects = Projects([tmp_path / "proj"], gh="")
    ctx = SimpleNamespace(projects=projects, dev=devloop.DevLoop())
    reg = ToolRegistry(context=ctx)
    code_tools.register(reg)
    monkeypatch.setattr(projects, "claude_sessions", lambda: [])
    assert "isn't working on anything" in reg.run("code_change_status", {})
    flock = projects.find("Flock")
    monkeypatch.setattr(projects, "claude_sessions", lambda: [(flock, 3 * 3600)])
    said = reg.run("code_change_status", {})
    assert "Claude Code is open in a terminal on Flock (for 3 hours)" in said
    assert "not one I started" in said and "1 uncommitted file" in said and "last commit" in said
    assert "isn't working" not in reg.run("code_change_status", {"project": "Flock"})


def test_clear_code_requests_skip_the_model(tmp_path, monkeypatch):
    from sanae.tools.code import code_route

    monkeypatch.setattr(devloop, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(devloop, "DATA", tmp_path)
    monkeypatch.setattr(devloop.DevLoop, "_work", lambda self, job: None)
    make_repo(tmp_path / "proj" / "Flock")
    make_repo(tmp_path / "proj" / "resume-builder")
    ctx = SimpleNamespace(projects=Projects([tmp_path / "proj"], gh=""), dev=devloop.DevLoop())
    route = lambda text: code_route(text, ctx)
    assert route("is resume builder running?") == ("project_running", {"project": "resume-builder"})
    assert route("did the server crash?") == ("project_running", {"project": ""})
    assert route("is spotify running?") is None                         # not a project
    assert route("push Flock") == ("push_project", {"project": "Flock"})
    assert route("push it to GitHub") == ("push_project", {"project": ""})
    assert route("what changed in Flock this week?") == ("project_status", {"project": "Flock", "what": "commits", "days": 7})
    assert route("what was my last commit in resume builder?")[1] == {"project": "resume-builder", "what": "commits", "days": 0}
    assert route("any open issues on San-AI?") == ("project_status", {"project": "Sanae", "what": "github", "days": 0})
    assert route("merge it") is None and route("throw that change away") is None     # nothing waiting
    ctx.dev.submit("fix it", "Flock", tmp_path / "proj" / "Flock")
    assert route("merge it") == ("approve_code_change", {})
    assert route("throw that change away") == ("reject_code_change", {})
    assert route("is Claude done yet?") == ("code_change_status", {})
    # the phone chat that got "Let me check on that for you..." and no tool, three times
    assert route("what's the status of claude code running for san-ai")[0] == "code_change_status"
    assert route("any updates on what claude is doing in Flock?") == ("code_change_status", {"project": "Flock"})
    before = "what's the status of claude code\nLet me check on that for you..."
    assert code_route("any updates?", ctx, before)[0] == "code_change_status"
    assert code_route("what's the status", ctx, before)[0] == "code_change_status"
    assert code_route("any updates?", ctx, "how was dinner?\nIt was good!") is None
    assert ctx.projects.mentioned("is Flock up?").name == "Flock"
    assert ctx.projects.mentioned("open the resume builder") .name == "resume-builder"
    assert ctx.projects.mentioned("what's the weather") is None
