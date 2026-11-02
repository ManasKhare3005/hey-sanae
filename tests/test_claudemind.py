"""Claude as her whole mind (claudemind.py): routing, secrets staying local, tool calls, fallback."""
import json

from sanae.claudemind import ClaudeMind, Privacy, chat_prompt, make_mind, split
from sanae.llm import ChatReply, ToolCall
from sanae.memory import MemoryStore
from tests.test_journal import Embed

TOOLS = [{"type": "function", "function": {"name": "set_reminder", "description": "Set a reminder.",
          "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "what"},
                                                          "when": {"type": "string", "description": "when"}},
                         "required": ["text", "when"]}}},
         {"type": "function", "function": {"name": "think_harder", "description": "x", "parameters": {}}}]


class Runner:
    def __init__(self, answers):
        self.answers, self.sent = list(answers), []

    def run(self, system, prompt, schema, keep_warm=False):
        self.sent.append({"system": system, "prompt": prompt, "schema": schema, "warm": keep_warm})
        got = self.answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got

    def prewarm(self, system, schema):
        pass


class Local:
    def __init__(self):
        self.calls, self.preloaded, self.unloaded = [], [], []

    def chat(self, model, messages, tools=None, options=None, on_text=None, fmt=None, keep_alive=None):
        self.calls.append({"model": model, "messages": messages, "keep_alive": keep_alive})
        return ChatReply(content="[happy] local answer")

    def preload(self, model, keep_alive=None):
        self.preloaded.append(model)

    def unload(self, model):
        self.unloaded.append(model)


def chat(text, history=()):
    return [{"role": "system", "content": "You are Sanae.\n/no_think"}, *history, {"role": "user", "content": f"[Thu 7:02 PM] {text}"}]


def test_claude_answers_with_tools_and_after_line():
    runner = Runner([{"reply": "", "tool_calls": [{"name": "set_reminder", "arguments": {"text": "call mom", "when": "8 PM"}},
                                                  {"name": "rm_rf", "arguments": {}}],
                      "after": "[happy] I'll remind you at 8 PM!"}])
    local = Local()
    mind = ClaudeMind(local, runner=runner)
    history = [{"role": "user", "content": "[7:00 PM] hi"}, {"role": "assistant", "content": "[happy] hey!"},
               {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "list_todos", "arguments": {}}}]},
               {"role": "tool", "content": "1 open: milk", "tool_name": "list_todos"}]
    reply = mind.chat("qwen", chat("remind me to call mom at 8", history), TOOLS)
    assert reply.tool_calls == [ToolCall("set_reminder", {"text": "call mom", "when": "8 PM"})]   # unknown tools dropped
    assert reply.raw["after"] == "[happy] I'll remind you at 8 PM!" and local.calls == []
    sent = runner.sent[0]
    assert "/no_think" not in sent["system"] and "tool_calls" in sent["system"] and sent["warm"]
    assert "- set_reminder: Set a reminder." in sent["prompt"] and "think_harder" not in sent["prompt"]
    assert "YOU CALLED list_todos {}" in sent["prompt"] and "RESULT of list_todos: 1 open: milk" in sent["prompt"]
    assert sent["prompt"].rstrip().endswith("THEM: [Thu 7:02 PM] remind me to call mom at 8")
    assert mind.calls_today() == 1


def test_background_json_and_plain_calls():
    schema = {"type": "object", "properties": {"facts": {"type": "array"}}}
    runner = Runner([{"facts": ["likes tea"]}, {"reply": "A short summary.", "tool_calls": []}])
    mind = ClaudeMind(Local(), runner=runner)
    got = mind.chat("qwen", [{"role": "user", "content": "Find facts in: I like tea"}], fmt=schema)
    assert json.loads(got.content) == {"facts": ["likes tea"]} and runner.sent[0]["prompt"] == "Find facts in: I like tea"
    assert runner.sent[0]["schema"] == schema
    spoken = []
    got = mind.chat("qwen", [{"role": "user", "content": "Summarise this chat."}], on_text=spoken.append)
    assert got.content == "A short summary." and spoken == ["A short summary."] and not runner.sent[1]["warm"]


def test_secrets_stay_local(tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"), Embed())
    clock = [1000.0]
    privacy = Privacy(store, secret_s=1800, clock=lambda: clock[0])
    runner = Runner([{"reply": "[happy] hi", "tool_calls": []}] * 5)
    local = Local()
    mind = ClaudeMind(local, runner=runner, privacy=privacy, clock=lambda: clock[0])
    mind.heard("let this be a secret between us, I have a crush on my lab partner")
    mind.chat("qwen", chat("let this be a secret between us, I have a crush on my lab partner"))
    assert runner.sent == [] and local.calls[-1]["keep_alive"] == "5m"           # local, and it leaves soon
    clock[0] += 600
    mind.heard("what should I do")                                              # still inside the secret
    mind.chat("qwen", chat("what should I do"))
    assert runner.sent == [] and mind.status()["secret"]
    clock[0] += 1300                                                            # 31 min: over
    mind.heard("anyway, what's the weather")
    mind.chat("qwen", chat("anyway, what's the weather"))
    assert len(runner.sent) == 1
    # a summary or diary that quotes the secret stays local, and what the local model writes is private too
    diary = [{"role": "user", "content": "Write the diary. Chat: I have a crush on my lab partner"}]
    mind.chat("qwen", diary)
    assert len(runner.sent) == 1 and local.calls[-1]["messages"] == diary
    assert Privacy(store).touches("so, I have a crush on my lab partner!")     # kept across restarts
    assert not Privacy(store).touches("what should I do about my lab report")
    mind.heard("ok secret between us again")
    mind.heard("secret's over, you can tell Claude")
    assert not mind.private_active


def test_comfort_photos_failures_and_limits():
    hard = [False]
    runner = Runner([RuntimeError("offline")] * 3 + [{"reply": "x", "tool_calls": []}] * 3)
    local = Local()
    clock = [0.0]
    mind = ClaudeMind(local, {"chat_daily_calls": 5}, runner=runner,
                      privacy=Privacy(comfort_now=lambda: hard[0], clock=lambda: clock[0]), clock=lambda: clock[0])
    hard[0] = True
    mind.chat("qwen", chat("I feel awful"))
    assert runner.sent == []
    hard[0] = False
    mind.chat("gemma", [{"role": "user", "content": "look", "images": ["abc"]}])
    assert runner.sent == []
    for _ in range(3):
        assert mind.chat("qwen", chat("hey")).content == "[happy] local answer"  # Claude failed: local answers
    assert mind.why_local(chat("hey")) == "Claude failing" and "offline" in mind.status()["error"]
    clock[0] += 301
    for _ in range(2):
        mind.chat("qwen", chat("hey"))
    assert mind.why_local(chat("hey")) == "daily limit"                         # 3 failed + 2 = 5 today


def test_local_model_isnt_preloaded_and_config():
    local = Local()
    mind = ClaudeMind(local, runner=Runner([]))
    mind.preload("qwen3:4b-instruct")
    mind.unload("qwen3:4b-instruct")
    assert local.preloaded == [] and local.unloaded == ["qwen3:4b-instruct"]
    assert make_mind(local, {"chat": True}) is None                             # never the real Claude in tests
    assert make_mind(local, {"chat": False}) is None
    system, rest = split(chat("hi"))
    assert system == "You are Sanae." and "THEM: [Thu 7:02 PM] hi" in chat_prompt(rest, None)


def test_agent_uses_claudes_after_line(tmp_path):
    from tests.test_sanae import FakeLLM, make_agent, make_registry

    class Mindful(FakeLLM):
        def __init__(self, replies):
            super().__init__(replies)
            self.heard_texts = []

        def heard(self, text):
            self.heard_texts.append(text)

    reg = make_registry(tmp_path)
    llm = Mindful([ChatReply(content="", tool_calls=[ToolCall("take_note", {"text": "bike is blue"})],
                             raw={"after": "Noted, your bike is blue!"})])
    agent = make_agent(reg, llm)
    assert agent.handle("note that my bike is blue") == "Noted, your bike is blue!"
    assert len(llm.calls) == 1 and llm.heard_texts == ["note that my bike is blue"]   # one call, not two


def test_private_now_reads_comfort_as_a_property():
    from types import SimpleNamespace

    from sanae.cloudbrain import private_now
    from sanae.comfort import Comfort

    assert isinstance(Comfort.serious, property)                    # .serious, not .serious()
    calm = SimpleNamespace(comfort=SimpleNamespace(serious=False), mind=None)
    assert private_now(calm) is False                               # this raised and read as "private" before
    assert private_now(SimpleNamespace(comfort=SimpleNamespace(serious=True), mind=None)) is True
    secret = ClaudeMind(Local(), runner=Runner([]))
    secret.heard("between you and me, I failed the quiz")
    assert private_now(SimpleNamespace(comfort=None, mind=secret)) is True


def test_after_the_secret_the_chat_goes_on_with_claude_without_it():
    clock = [0.0]
    runner = Runner([{"reply": "[happy] 12!", "tool_calls": []}] * 3)
    local = Local()
    mind = ClaudeMind(local, runner=runner, privacy=Privacy(secret_s=1800, clock=lambda: clock[0]), clock=lambda: clock[0])
    mind.heard("between you and me, I'm thinking of quitting my job soon")
    mind.heard("secret's over, you can tell Claude")
    history = [{"role": "user", "content": "[7:00 PM] between you and me, I'm thinking of quitting my job soon"},
               {"role": "assistant", "content": "[sad] That's a big step."},
               {"role": "user", "content": "[7:01 PM] remind me about rent"},
               {"role": "assistant", "content": "[happy] Done."}]
    new = {"role": "user", "content": "[7:05 PM] what's 15% of 80?"}
    summary = {"role": "user", "content": new["content"] + "\n(Earlier in this chat: thinking of quitting my job soon, so tired)"}
    mind.chat("qwen", [{"role": "system", "content": "s"}, *history, summary], TOOLS)
    sent = runner.sent[-1]["prompt"]
    assert "quitting" not in sent and "remind me about rent" in sent and "15% of 80" in sent and local.calls == []
    mind.chat("qwen", [{"role": "system", "content": "s"}, {"role": "user", "content": "I'm thinking of quitting my job soon, help"}], TOOLS)
    assert len(local.calls) == 1                                          # their new words touch it: local
    mind.chat("qwen", [{"role": "user", "content": "Diary: between you and me, I'm thinking of quitting my job soon"}])
    assert len(local.calls) == 2                                          # background work about it: local
