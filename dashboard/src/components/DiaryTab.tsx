import { useEffect, useState } from "react";
import { api } from "../api";
import { assistantName } from "../name";
import type { DiaryData, DiaryEntry } from "../types";

const MOMENT_LABEL: Record<string, string> = { joke: "Running joke", nickname: "Nickname", memory: "Memory", date: "Date" };
const DIALS: { key: "length" | "tease" | "questions"; label: string; low: string; high: string }[] = [
  { key: "length", label: "Reply length", low: "short", high: "more detail" },
  { key: "tease", label: "Teasing", low: "gentle", high: "lots" },
  { key: "questions", label: "Questions back", low: "few", high: "usual" },
];

function dayLabel(day: string) {
  const d = new Date(`${day}T12:00:00`);
  return d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
}

/** Her diary of your days (edit or delete any day), the jokes / nicknames / dates she keeps, and how she's learned to talk to you. */
export default function DiaryTab({ revision }: { revision: number }) {
  const [data, setData] = useState<DiaryData | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const load = () => api.diary().then(setData).catch(() => {});
  useEffect(() => { load(); }, [revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (e: DiaryEntry) => {
    const text = draft.trim();
    if (!text) await api.deleteDiary(e.day);
    else if (text !== e.text) await api.editDiary(e.day, text);
    setEditing(null);
    load();
  };

  if (data && !data.enabled) {
    return <div className="drawer-body"><p className="drawer-note">The diary is off (persona.yaml: support.diary).</p></div>;
  }
  const name = assistantName();
  const entries = data?.entries ?? [];
  const moments = data?.moments ?? [];

  return (
    <div className="drawer-body">
      <p className="drawer-note">
        {name}'s diary of your days, written each morning from the day's chats (only your own voice or typing). She uses it to
        remember how things went ("last Tuesday you were stressed about…"). Click a day to fix it; ✕ deletes it.
      </p>

      {data?.taste && (
        <>
          <div className="label" style={{ margin: "4px 0 6px" }}>How she's learned to talk to you</div>
          {DIALS.map((d) => (
            <div key={d.key} className="list-row" style={{ alignItems: "center" }}>
              <div className="label dim" style={{ width: 120 }}>{d.label}</div>
              <span className="label dim">{d.low}</span>
              <div style={{ flex: 1, height: 4, margin: "0 8px", background: "rgba(34,211,238,.15)", position: "relative" }}>
                <div style={{ position: "absolute", left: `calc(${Math.round(data.taste![d.key] * 100)}% - 4px)`, top: -3,
                  width: 8, height: 10, background: "var(--accent)" }} />
              </div>
              <span className="label dim">{d.high}</span>
            </div>
          ))}
          <button className="btn ghost-sm" style={{ margin: "6px 0 12px" }} onClick={() => api.resetTaste().then(load)}>Reset to default</button>
        </>
      )}

      <div className="list">
        {entries.length === 0 && <div className="approvals-empty">No entries yet. The first one is written the morning after you talk.</div>}
        {entries.map((e) => (
          <div key={e.day} className="list-row">
            {editing === e.day ? (
              <form style={{ flex: 1 }} onSubmit={(ev) => { ev.preventDefault(); save(e); }}>
                <textarea className="field" autoFocus rows={4} value={draft} onChange={(ev) => setDraft(ev.target.value)} onBlur={() => save(e)} />
              </form>
            ) : (
              <div style={{ cursor: "text", flex: 1 }} onClick={() => { setEditing(e.day); setDraft(e.text); }}>
                <div className="label">{dayLabel(e.day)}{e.mood ? ` · felt ${e.mood}` : ""}{e.tone ? ` · ${e.tone}` : ""}</div>
                <div className="list-text">{e.text}</div>
              </div>
            )}
            <button className="icon-btn danger" title="Delete this day" onClick={() => api.deleteDiary(e.day).then(load)}>✕</button>
          </div>
        ))}
      </div>

      {moments.length > 0 && (
        <>
          <div className="label" style={{ margin: "14px 0 4px" }}>Shared moments</div>
          <div className="list">
            {moments.map((m) => (
              <div key={m.id} className="list-row">
                <div style={{ flex: 1 }}>
                  <div className="list-text">{m.text}</div>
                  <div className="label dim">
                    {MOMENT_LABEL[m.kind] ?? m.kind}{m.date ? ` · every ${m.date}` : ""} · {dayLabel(m.day)}{m.uses ? ` · brought up ${m.uses}×` : ""}
                  </div>
                </div>
                <button className="icon-btn danger" title="Forget" onClick={() => api.deleteMoment(m.id).then(load)}>✕</button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
