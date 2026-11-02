import { assistantName } from "../name";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Message } from "../types";
import { clock, toolLabel } from "../format";
import { FaceAvatar } from "./Face";

type Props = { messages: Message[]; connected: boolean; userName?: string; emotion: string };

const SUGGESTIONS = ["what's the weather in Austin?", "what reminders do I have?", "open youtube", "what time is it?"];

export default function Conversation({ messages, connected, userName, emotion }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, busy]);

  const send = async (value = text) => {
    const cmd = value.trim();
    if (!cmd || busy) return;
    setBusy(true);
    setError("");
    setText("");
    try {
      await api.command(cmd); // the exchange itself arrives over the live event stream
    } catch (e) {
      setError(e instanceof Error ? e.message : `Couldn't reach ${assistantName()}`);
      setText(cmd);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="conversation panel">
      <div className="panel-head">
        <span className="label">our chat</span>
        <span className="label dim">{messages.length ? `${messages.length} messages` : ""}</span>
      </div>

      <div className="messages" ref={list}>
        {messages.length === 0 && (
          <div className="empty">
            <FaceAvatar emotion="happy" size={64} />
            <div className="empty-title">Nothing said yet</div>
            <div className="empty-sub">Say the wake word, or try one of these:</div>
            <div className="chips">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" onClick={() => send(s)} disabled={!connected}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={m.key} className={`msg ${m.role}`}>
            {m.role === "sanae" && <FaceAvatar emotion={i === messages.length - 1 ? emotion : "happy"} size={34} />}
            <div className="msg-body">
            <div className="msg-meta">
              <span>{m.role === "you" ? m.guest || userName || "you" : assistantName()}</span>
              {m.guest && <span className="src">{m.role === "you" ? "guest" : `to ${m.guest}`}</span>}
              {m.source && m.source !== "voice" && <span className="src">{m.source === "dashboard" ? "typed" : m.source}</span>}
              <span className="dim">{clock(m.ts)}</span>
            </div>
            {m.tools && m.tools.length > 0 && (
              <div className="tool-chips">
                {m.tools.map((t, i) => (
                  <span key={i} className="tool-chip" title={t.result || ""}>⚙ {toolLabel(t)}</span>
                ))}
              </div>
            )}
            <div className="bubble">{m.text}</div>
            </div>
          </div>
        ))}
        {busy && (
          <div className="msg sanae">
            <FaceAvatar emotion="thinking" size={34} />
            <div className="bubble typing"><span /><span /><span /></div>
          </div>
        )}
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <span className="prompt">♡</span>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={connected ? `Say something to ${assistantName()}… (she answers quietly here)` : `${assistantName()} is offline`}
          disabled={!connected}
          aria-label="Command"
        />
        <button className="btn primary" disabled={!connected || busy || !text.trim()}>Send</button>
      </form>
      {error && <div className="error-line">{error}</div>}
    </section>
  );
}
