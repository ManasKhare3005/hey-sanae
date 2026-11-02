"""Alex's code projects by voice: status, GitHub, what's running, dev servers, and changes made by
Claude Code (devloop.DevLoop) on a branch that waits for an OK. Pushing is the only outward step and
always asks first."""
from __future__ import annotations

import re
import time

from ..projects import ago
from .registry import ToolRegistry

PROJECT = {"type": "string", "description": "Project name as said (e.g. 'Flock'); empty = the current one"}


# The 4b model called stop_project for "is resume builder running?", and for "merge it", "throw that
# change away" and "push Flock" said it had done so without calling anything: clear phrasings go
# straight to the tool (agent.handle asks code_route after direct_route)
RUNNING = re.compile(r"^(?:hey,? )?(?:is|are) (?P<p>.+?) (?:still )?(?:running|up|on)\??$|"
                     r"^did (?:the )?(?P<q>.+?) (?:server |app )?(?:crash|die|stop)\w*\??$", re.I)
CLAUDE_STATUS = re.compile(r"\b(is claude (still working|done|finished|ready)|how'?s (the|claude'?s) (change|work) going|"
                           r"what did claude (change|do)|is (the|my) change (done|ready))\b|"
                           # "what's the status of claude code running for san-ai" got "Let me check..." and no tool
                           r"\b(status|update|updates|progress|news)\b.{0,40}\bclaude\b|"
                           r"\bclaude\b.{0,40}\b(status|still (running|working|going|at it)|doing|up to|progress)\b", re.I)
# "any updates?" right after talking about Claude's work
FOLLOW_UP = re.compile(r"^(?:and |so |okay,? |ok,? )?(any (updates?|news|progress)( (on|with) (it|that))?|"
                       r"what'?s the (status|update)( now)?|status|(is it|is that) (done|finished|ready)( yet)?|"
                       r"how'?s it (going|coming along)|(is it )?still (going|working|running))[?.!]*$", re.I)
ABOUT_CLAUDE = re.compile(r"\bclaude\b|\bcode change\b", re.I)
MERGE = re.compile(r"^(?:ok(?:ay)?,? |yes,? |yeah,? |looks good,? )?(?:merge|approve|apply) (?:it|that|the change|"
                   r"claude'?s change|the fix)\b", re.I)
REJECT = re.compile(r"\b(reject (it|that|the change)|throw (it|that|the|this) (change )?away|"
                    r"throw away (the|that|this|claude'?s) change|cancel (the|that|this|claude'?s) change|"
                    r"discard (it|that|the change))\b", re.I)
CHANGES = re.compile(r"^what(?:'?s| has| have)? (?:changed|happened|been done) (?:in|on|to) (?P<p>.+?)"
                     r"(?P<w> this week| today| lately| recently| this month)?\??$", re.I)
LAST_COMMIT = re.compile(r"\b(?:my |the )?(?:last|latest) commits? (?:in|on|for|to) (?P<p>.+?)\??$", re.I)
GITHUB = re.compile(r"\b(?:open )?(?:issues|pull requests|prs|ci|builds?|checks) (?:on|in|for) (?P<p>.+?)"
                    r"(?: passing| failing| green| okay)?\??$", re.I)
SPAN = {" today": 1, " this week": 7, " lately": 7, " recently": 7, " this month": 30}
PUSH = re.compile(r"^(?:ok(?:ay)?,? |now )?push (?P<p>it|that|the change|my changes|[\w .\-]+?)(?: to github)?[.!]?$", re.I)
THIS = ("it", "that", "the change", "my changes", "the server", "my server", "the app", "my app", "my project",
        "the project", "this")


def code_route(text: str, ctx, before: str = "") -> tuple[str, dict] | None:
    """`before` = the last exchange (user words + her reply), for follow-ups like "any updates?"."""
    text = text.strip()
    projects, dev = getattr(ctx, "projects", None), getattr(ctx, "dev", None)

    def named(phrase: str | None) -> str | None:
        """'' for it/that, the project name if it is one, else None (not about a project)."""
        phrase = (phrase or "").strip().lower()
        if phrase in THIS or re.sub(r"^(the|my) ", "", phrase) in ("server", "app", "project", "site", "dev server"):
            return ""
        found = projects.find(phrase) if projects is not None else None
        return found.name if found is not None else None

    if dev is not None and (CLAUDE_STATUS.search(text) or (FOLLOW_UP.match(text) and ABOUT_CLAUDE.search(before))):
        found = projects.mentioned(text) if projects is not None else None
        return "code_change_status", {"project": found.name} if found is not None else {}
    pending = dev is not None and (dev.busy is not None or dev.waiting() is not None)
    if pending and MERGE.match(text):
        return "approve_code_change", {}
    if pending and REJECT.search(text):
        return "reject_code_change", {}
    if projects is None:
        return None
    if m := RUNNING.match(text):
        name = named(m.group("p") or m.group("q"))
        if name is not None:
            return "project_running", {"project": name}
    if m := PUSH.match(text):
        name = named(m.group("p"))
        if name is not None:
            return "push_project", {"project": name}
    if m := CHANGES.match(text):
        name = named(m.group("p"))
        if name is not None:
            return "project_status", {"project": name, "what": "commits", "days": SPAN.get((m.group("w") or "").lower(), 7)}
    if m := LAST_COMMIT.search(text):
        name = named(m.group("p"))
        if name is not None:
            return "project_status", {"project": name, "what": "commits", "days": 0}
    if m := GITHUB.search(text):
        name = named(m.group("p"))
        if name is not None:
            return "project_status", {"project": name, "what": "github", "days": 0}
    return None


def first_sentences(text: str, n: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return " ".join(parts[:n])[:400]


def register(reg: ToolRegistry):
    ctx = reg.context

    def projects():
        return getattr(ctx, "projects", None)

    def pick(name: str):
        p = projects()
        if p is None:
            return None, "Projects aren't set up (projects.folders in config.yaml)."
        found = p.resolve(name)
        return (None, found) if isinstance(found, str) else (found, "")

    @reg.tool("List the user's code projects (git repos); github=true adds their GitHub repos.",
              params={"github": {"type": "boolean", "description": "Also list repos on GitHub"}}, required=[])
    def list_projects(github: bool = False):
        p = projects()
        if p is None:
            return "Projects aren't set up (projects.folders in config.yaml)."
        out = p.listing()
        return out + " " + p.repos() if github else out

    @reg.tool("A code project's commits / uncommitted files (what=commits), GitHub issues, pull requests and CI "
              "(what=github), or both. 'What changed this week', 'any open issues', 'my last commit'.",
              params={"project": PROJECT,
                      "what": {"type": "string", "enum": ["commits", "github", "all"]},
                      "days": {"type": "number", "description": "Commits from the last N days (7 = this week); 0 = latest few"}},
              required=[], direct=True)
    def project_status(project: str = "", what: str = "all", days: float = 0):
        proj, why = pick(project)
        if proj is None:
            return why
        parts = []
        if what in ("commits", "all", ""):
            parts.append(projects().status(proj, int(days or 0)))
        if what in ("github", "all", ""):
            parts.append(projects().github(proj))
        return " ".join(parts)

    @reg.tool("Whether a project is running (dev server, port) and errors in its output. 'Is Flock running', 'any errors'.",
              params={"project": PROJECT}, required=[])
    def project_running(project: str = ""):
        proj, why = pick(project)
        return why if proj is None else projects().running(proj)

    @reg.tool("Start a project's dev server in the background (e.g. npm run dev). 'Start Flock', 'run the server'.",
              params={"project": PROJECT,
                      "command": {"type": "string", "description": "Only if the user said the exact command"}},
              required=[], direct=True)
    def run_project(project: str = "", command: str = ""):
        proj, why = pick(project)
        return why if proj is None else projects().start(proj, command)

    @reg.tool("Stop a project that Sanae started. For 'stop Flock', 'kill the server'.",
              params={"project": PROJECT}, required=[], direct=True)
    def stop_project(project: str = ""):
        proj, why = pick(project)
        return why if proj is None else projects().stop(proj)

    @reg.tool("Pull a project's latest commits from GitHub. 'Pull Flock', 'update my repo'.",
              params={"project": PROJECT}, required=[], direct=True)
    def pull_project(project: str = ""):
        proj, why = pick(project)
        return why if proj is None else projects().pull(proj)

    @reg.tool("Push a project's commits to GitHub (asks first). 'Push it', 'push Flock'.",
              params={"project": PROJECT}, required=[], direct=True)
    def push_project(project: str = ""):
        proj, why = pick(project)
        if proj is None:
            return why
        branch = projects().git(proj, "rev-parse", "--abbrev-ref", "HEAD") or "its branch"
        if not ctx.confirm(f"Push {proj.name} ({branch}) to GitHub?"):
            return "Okay, I didn't push it."
        out = projects().push(proj)
        dev = getattr(ctx, "dev", None)
        job = dev.latest(proj.name) if dev is not None else None
        if job is not None and job.status == "merged" and not job.pushed and out.startswith("Pushed"):
            dev._update(job, pushed=True)
        return out

    @reg.tool("Have Claude Code change a project (or Sanae herself): fix a bug, add a feature. It works on a branch "
              "until approved. 'Ask Claude to ...', 'fix the login bug in Flock'.",
              params={"request": {"type": "string", "description": "The change, in the user's words, complete"},
                      "project": PROJECT},
              required=["request"], direct=True)
    def code_change(request: str, project: str = ""):
        dev = getattr(ctx, "dev", None)
        if dev is None:
            return "Claude Code changes are turned off (dev.enabled in config.yaml)."
        proj, why = pick(project)
        if proj is None:
            return why
        try:
            job = dev.submit(request, proj.name, proj.path)
        except (RuntimeError, ValueError) as exc:
            return str(exc)
        return (f"Okay, Claude is working on that in {job.project}, on its own branch. I'll tell you when it's ready "
                "for your OK.")

    @reg.tool("How Claude's change is going, its summary and tests. 'Is Claude done', 'what did Claude change'.",
              params={"project": PROJECT}, required=[])
    def code_change_status(project: str = ""):
        dev = getattr(ctx, "dev", None)
        if dev is None:
            return "Claude Code changes are turned off."
        name = ""
        if project:
            proj, why = pick(project)
            if proj is None:
                return why
            name = proj.name
        job = dev.latest(name)
        if job is not None and job.status in ("queued", "working", "testing", "building"):
            return describe(job)
        # Claude Code open in a terminal (Alex's own session): no way inside it, but the folder shows work
        lines = []
        p = projects()
        for proj, up in (p.claude_sessions() if p is not None else []):
            if name and proj.name != name:
                continue
            seen = p.activity(proj)
            lines.append(f"Claude Code is open in a terminal on {proj.name} (for {ago(up).removesuffix(' ago')}). "
                         f"That's your session, not one I started, so I can't see what it's doing"
                         + (f", but the folder shows: {seen}." if seen else "."))
        if job is not None and (not lines or time.time() - job.created < 86400):
            lines.append(describe(job))
        if not lines:
            return "Claude isn't working on anything right now, and hasn't made any changes through me yet."
        return " ".join(lines)

    @reg.tool("Merge Claude's finished change on the laptop (not pushed). 'Merge it', 'approve the change'.",
              params={"project": PROJECT}, required=[], direct=True)
    def approve_code_change(project: str = ""):
        dev, job, why = waiting(project)
        if job is None:
            return why
        if not job.tests_ok and not ctx.confirm(f"The tests failed for this change. Merge it into {job.project} anyway?"):
            return "Okay, I left it waiting."
        try:
            dev.approve(job.id)
        except RuntimeError as exc:
            return f"I couldn't merge it: {exc}"
        if job.is_sanae:
            return "Merged. I'll restart with the new code if I need to."
        return f"Merged into {job.project} ({job.base}). Say 'push it' when you want it on GitHub."

    @reg.tool("Reject or cancel Claude's change (deletes its branch). 'Reject it', 'throw that away'.",
              params={"project": PROJECT}, required=[], direct=True)
    def reject_code_change(project: str = ""):
        dev = getattr(ctx, "dev", None)
        if dev is None:
            return "Claude Code changes are turned off."
        job = dev.busy or waiting(project)[1]
        if job is None:
            return "There's no change to reject."
        try:
            dev.reject(job.id)
        except RuntimeError as exc:
            return str(exc)
        return f"Okay, threw away the change in {job.project}."

    def waiting(project: str):
        dev = getattr(ctx, "dev", None)
        if dev is None:
            return None, None, "Claude Code changes are turned off."
        name = ""
        if project:
            proj, why = pick(project)
            if proj is None:
                return dev, None, why
            name = proj.name
        job = dev.waiting(name)
        if job is None:
            busy = dev.busy
            return dev, None, (f"Claude is still working on it ({(busy.progress or ['starting'])[-1].lower()})." if busy
                               else "There's no finished change waiting.")
        return dev, job, ""


def describe(job) -> str:
    """A spoken status line for a change."""
    if job.status in ("queued", "working", "testing", "building"):
        step = (job.progress or ["starting"])[-1]
        return f"Claude is still on it in {job.project}: {step[0].lower() + step[1:] if step else 'working'}."
    if job.status == "ready":
        tests = "Tests passed." if job.tests_ok else "But the tests failed."
        n = len(job.files)
        return (f"Claude's change in {job.project} is ready: {first_sentences(job.summary)} "
                f"{n} file{'s' if n != 1 else ''} changed. {tests} Say 'merge it' or 'reject it'.")
    if job.status == "failed":
        return f"Claude's change in {job.project} failed: {first_sentences(job.error or job.summary, 1)}"
    if job.status == "merged":
        return f"The last change in {job.project} is merged" + (" and pushed." if job.pushed else ", not pushed yet.")
    return f"The last change in {job.project} was {job.status}."
