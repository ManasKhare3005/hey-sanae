import { useEffect, useState } from "react";
import { api } from "../api";
import { assistantName } from "../name";
import type { AboutData, AboutFact } from "../types";

const KIND_LABEL: Record<string, string> = {
  like: "Likes", dislike: "Dislikes", person: "People", plan: "Plans", project: "Projects", routine: "Routines", other: "Other",
};
const ORDER = ["like", "project", "plan", "person", "routine", "dislike", "other"];
const MOOD_LABEL: Record<string, string> = { happy: "in a great mood", sleepy: "sleepy", sad: "a little down", neutral: "doing fine" };

/** What she has picked up about you in conversations (edit or delete anything), what she means to ask about, her mood. */
export default function AboutTab({ revision }: { revision: number }) {
  const [data, setData] = useState<AboutData | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const load = () => api.about().then(setData).catch(() => {});
  useEffect(() => { load(); }, [revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (f: AboutFact) => {
    const text = draft.trim();
    if (!text) await api.deleteAbout(f.id);
    else if (text !== f.text) await api.editAbout(f.id, text);
    setEditing(null);
    load();
  };

  if (data && !data.enabled) {
    return <div className="drawer-body"><p className="drawer-note">Friend memory is off (persona.yaml: learn).</p></div>;
  }
  const facts = data?.facts ?? [];
  const groups = ORDER.map((k) => [k, facts.filter((f) => f.kind === k)] as const).filter(([, list]) => list.length);
  const name = assistantName();

  return (
    <div className="drawer-body">
      <p className="drawer-note">
        What {name} has picked up about you while talking (a few minutes after each conversation). It helps her ask about your
        day and remember what you're into. Click a line to fix it; ✕ forgets it. Health, money, passwords, religion and
        politics are never kept.
      </p>
      {data?.mood && (
        <div className="label dim" style={{ margin: "0 0 10px" }}>
          {name} is {MOOD_LABEL[data.mood.resting] ?? "doing fine"} · energy {Math.round(data.mood.energy * 100)}% · cheer {Math.round(data.mood.cheer * 100)}%
        </div>
      )}
      <div className="list">
        {facts.length === 0 && <div className="approvals-empty">Nothing yet. Just talk to her.</div>}
        {groups.map(([kind, list]) => (
          <div key={kind}>
            <div className="label" style={{ margin: "10px 0 4px" }}>{KIND_LABEL[kind]}</div>
            {list.map((f) => (
              <div key={f.id} className="list-row">
                {editing === f.id ? (
                  <form style={{ flex: 1 }} onSubmit={(e) => { e.preventDefault(); save(f); }}>
                    <input className="field" autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={() => save(f)} />
                  </form>
                ) : (
                  <div style={{ cursor: "text", flex: 1 }} onClick={() => { setEditing(f.id); setDraft(f.text); }}>
                    <div className="list-text">{f.text}</div>
                    <div className="label dim">{new Date(f.updated).toLocaleDateString()}{f.mentions > 1 ? ` · came up ${f.mentions}×` : ""}</div>
                  </div>
                )}
                <button className="icon-btn danger" title="Forget" onClick={() => api.deleteAbout(f.id).then(load)}>✕</button>
              </div>
            ))}
          </div>
        ))}
      </div>
      {(data?.pending?.length ?? 0) > 0 && (
        <>
          <div className="label" style={{ margin: "14px 0 4px" }}>Did she hear this right?</div>
          <div className="list">
            {data!.pending!.map((p) => (
              <div key={p.id} className="list-row">
                <div className="list-text">{p.text}</div>
                <button className="icon-btn" title="Yes, keep it" onClick={() => api.confirmPending(p.id).then(load)}>✓</button>
                <button className="icon-btn danger" title="No, drop it" onClick={() => api.rejectPending(p.id).then(load)}>✕</button>
              </div>
            ))}
          </div>
        </>
      )}
      {(data?.threads.length ?? 0) > 0 && (
        <>
          <div className="label" style={{ margin: "14px 0 4px" }}>She'll ask about</div>
          <div className="list">
            {data!.threads.map((t) => (
              <div key={t.id} className="list-row">
                <div>
                  <div className="list-text">{t.about}</div>
                  <div className="label dim">after {new Date(t.ask_after).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}</div>
                </div>
                <button className="icon-btn danger" title="Don't ask" onClick={() => api.dropThread(t.id).then(load)}>✕</button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
