import { assistantName } from "../name";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Fact, Reminder, RoutineTask, Todo } from "../types";
import { relative, whenLabel } from "../format";
import AboutTab from "./AboutTab";
import DiaryTab from "./DiaryTab";
import NotesTab from "./NotesTab";
import PhoneTab from "./PhoneTab";
import PrivacyTab from "./PrivacyTab";
import AccuracyTab from "./AccuracyTab";

export type Tab = "memory" | "about" | "diary" | "reminders" | "notes" | "phone" | "privacy" | "accuracy";
type Props = { open: Tab | null; onClose: () => void; onTab: (t: Tab) => void; revision: number };

export default function Drawer({ open, onClose, onTab, revision }: Props) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  return (
    <>
      <div className={`scrim ${open ? "show" : ""}`} onClick={onClose} />
      <aside className={`drawer panel ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="drawer-head">
          <div className="tabs">
            <button className={open === "memory" ? "active" : ""} onClick={() => onTab("memory")}>✦ Memory</button>
            <button className={open === "about" ? "active" : ""} onClick={() => onTab("about")}>♡ About you</button>
            <button className={open === "diary" ? "active" : ""} onClick={() => onTab("diary")}>❖ Diary</button>
            <button className={open === "reminders" ? "active" : ""} onClick={() => onTab("reminders")}>⏰ Reminders, todos & routine</button>
            <button className={open === "notes" ? "active" : ""} onClick={() => onTab("notes")}>✍ Notes</button>
            <button className={open === "phone" ? "active" : ""} onClick={() => onTab("phone")}>▯ Phone</button>
            <button className={open === "privacy" ? "active" : ""} onClick={() => onTab("privacy")}>⛨ Privacy</button>
            <button className={open === "accuracy" ? "active" : ""} onClick={() => onTab("accuracy")}>◎ Accuracy</button>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {open === "memory" && <MemoryTab revision={revision} />}
        {open === "about" && <AboutTab revision={revision} />}
        {open === "diary" && <DiaryTab revision={revision} />}
        {open === "reminders" && <RemindersTab revision={revision} />}
        {open === "reminders" && <TodosSection revision={revision} />}
        {open === "reminders" && <RoutineSection revision={revision} />}
        {open === "notes" && <NotesTab revision={revision} />}
        {open === "phone" && <PhoneTab />}
        {open === "privacy" && <PrivacyTab />}
        {open === "accuracy" && <AccuracyTab />}
      </aside>
    </>
  );
}

function MemoryTab({ revision }: { revision: number }) {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [q, setQ] = useState("");
  const [draft, setDraft] = useState("");
  const load = () => api.facts(q).then(setFacts).catch(() => {});
  useEffect(() => {
    const t = window.setTimeout(load, q ? 250 : 0);
    return () => window.clearTimeout(t);
  }, [q, revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const add = async () => {
    if (!draft.trim()) return;
    await api.addFact(draft.trim());
    setDraft("");
    load();
  };

  return (
    <div className="drawer-body">
      <p className="drawer-note">What {assistantName()} remembers about you. Relevant facts are attached to your requests automatically. Say “remember …” or add one here.</p>
      <input className="field" placeholder="Search by meaning… (e.g. “exam”)" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="list">
        {facts.length === 0 && <div className="approvals-empty">{q ? "Nothing matches." : "Nothing saved yet."}</div>}
        {facts.map((f) => (
          <div key={f.id} className="list-row">
            <div>
              <div className="list-text">{f.text}</div>
              <div className="label dim">{q && f.score !== undefined ? `match ${(f.score * 100).toFixed(0)}% · ` : ""}{new Date(f.created).toLocaleDateString()}</div>
            </div>
            <button className="icon-btn danger" title="Forget" onClick={() => api.deleteFact(f.id).then(load)}>✕</button>
          </div>
        ))}
      </div>
      <form className="add-row" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <input className="field" placeholder="New fact, e.g. My exam is on Friday" value={draft} onChange={(e) => setDraft(e.target.value)} />
        <button className="btn primary" disabled={!draft.trim()}>Remember</button>
      </form>
    </div>
  );
}

function RemindersTab({ revision }: { revision: number }) {
  const [items, setItems] = useState<Reminder[]>([]);
  const [text, setText] = useState("");
  const [when, setWhen] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => api.reminders().then(setItems).catch(() => {});
  useEffect(() => {
    load();
    const t = window.setInterval(load, 30000);
    return () => window.clearInterval(t);
  }, [revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const add = async () => {
    try {
      const r = await api.addReminder(text.trim(), when.trim());
      setMsg(`Set for ${r.spoken}.`);
      setText("");
      setWhen("");
      load();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Couldn't set it");
    }
  };

  return (
    <div className="drawer-body">
      <p className="drawer-note">{assistantName()} says these out loud and shows a Windows notification when they're due. Missed ones are announced when {assistantName()} next starts.</p>
      <div className="list">
        {items.length === 0 && <div className="approvals-empty">No reminders. Try “remind me about my exam Friday at 9”.</div>}
        {items.map((r) => (
          <div key={r.id} className="list-row">
            <div>
              <div className="list-text">{r.text}</div>
              <div className="label dim">{r.repeat ? `🔁 ${r.spoken} · ` : `${whenLabel(r.due)} · `}{relative(r.due)}</div>
            </div>
            <button className="icon-btn danger" title="Cancel" onClick={() => api.cancelReminder(r.id).then(load)}>✕</button>
          </div>
        ))}
      </div>
      <form className="add-grid" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <input className="field" placeholder="What (e.g. CS 101 exam)" value={text} onChange={(e) => setText(e.target.value)} />
        <input className="field" placeholder="When (e.g. Thursday 7pm, in 2 hours, the 5th of every month)" value={when} onChange={(e) => setWhen(e.target.value)} />
        <button className="btn primary" disabled={!text.trim() || !when.trim()}>Set reminder</button>
      </form>
      {msg && <div className="drawer-note">{msg}</div>}
    </div>
  );
}

function TodosSection({ revision }: { revision: number }) {
  const [items, setItems] = useState<Todo[]>([]);
  const [draft, setDraft] = useState("");
  const load = () => api.todos().then(setItems).catch(() => {});
  useEffect(() => {
    load();
  }, [revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const add = async () => {
    if (!draft.trim()) return;
    await api.addTodo(draft.trim()).catch(() => {});
    setDraft("");
    load();
  };
  const done = items.filter((t) => t.done).length;

  return (
    <div className="drawer-body">
      <p className="drawer-note">Todo list: no alarm, just things to get done. It's on your phone and its home-screen widget too. Say “add milk to my list” or “check off laundry”.</p>
      <div className="list">
        {items.length === 0 && <div className="approvals-empty">Nothing on your list.</div>}
        {items.map((t) => (
          <div key={t.uid} className="list-row">
            <label className="todo-row">
              <input type="checkbox" checked={t.done} onChange={(e) => api.tickTodo(t.uid, e.target.checked).then(load)} />
              <span className={`list-text ${t.done ? "todo-done" : ""}`}>{t.text}</span>
            </label>
            <button className="icon-btn danger" title="Remove" onClick={() => api.deleteTodo(t.uid).then(load)}>✕</button>
          </div>
        ))}
      </div>
      <form className="add-row" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <input className="field" placeholder="New todo (commas for several: milk, eggs)" value={draft} onChange={(e) => setDraft(e.target.value)} />
        <button className="btn primary" disabled={!draft.trim()}>Add</button>
      </form>
      {done > 0 && <button className="btn" onClick={() => api.clearDoneTodos().then(load)}>Clear {done} done</button>}
    </div>
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function RoutineSection({ revision }: { revision: number }) {
  const [items, setItems] = useState<RoutineTask[]>([]);
  const [draft, setDraft] = useState("");
  const [kind, setKind] = useState<"daily" | "weekdays" | "weekly" | "monthly">("daily");
  const [weekday, setWeekday] = useState((new Date().getDay() + 6) % 7);
  const [monthDay, setMonthDay] = useState(new Date().getDate());
  const load = () => api.routine().then(setItems).catch(() => {});
  useEffect(() => {
    load();
  }, [revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const freq = kind === "weekly" ? `weekly:${weekday}` : kind === "monthly" ? `monthly:${monthDay}` : kind;
  const add = async () => {
    if (!draft.trim()) return;
    await api.addRoutine(draft.trim(), freq).catch(() => {});
    setDraft("");
    load();
  };
  const today = items.filter((t) => t.due_today);
  const other = items.filter((t) => !t.due_today);
  const row = (t: RoutineTask) => (
    <div key={t.uid} className="list-row">
      <label className="todo-row">
        {t.due_today && <input type="checkbox" checked={t.done} onChange={(e) => api.tickRoutine(t.uid, e.target.checked).then(load)} />}
        <span className={`list-text ${t.done ? "todo-done" : ""}`}>{t.text} <span className="list-meta">· {t.label}</span></span>
      </label>
      <button className="icon-btn danger" title="Remove from routine" onClick={() => api.deleteRoutine(t.uid).then(load)}>✕</button>
    </div>
  );

  return (
    <div className="drawer-body">
      <p className="drawer-note">Routine: things that come back every day, week or month. Today's are in the morning briefing, and your phone tells you in the evening if one is still unticked. Say “add water the plants to my routine every day” or “I did the laundry”.</p>
      <div className="list">
        {items.length === 0 && <div className="approvals-empty">No routine yet.</div>}
        {today.length > 0 && <div className="list-meta">Today</div>}
        {today.map(row)}
        {other.length > 0 && <div className="list-meta">Other days</div>}
        {other.map(row)}
      </div>
      <form className="add-row" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <input className="field" placeholder="New routine task (water the plants)" value={draft} onChange={(e) => setDraft(e.target.value)} />
        <select className="field" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="daily">Every day</option>
          <option value="weekdays">Weekdays</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
        </select>
        {kind === "weekly" && (
          <select className="field" value={weekday} onChange={(e) => setWeekday(Number(e.target.value))}>
            {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
          </select>
        )}
        {kind === "monthly" && (
          <select className="field" value={monthDay} onChange={(e) => setMonthDay(Number(e.target.value))}>
            {Array.from({ length: 31 }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}
          </select>
        )}
        <button className="btn primary" disabled={!draft.trim()}>Add</button>
      </form>
    </div>
  );
}
