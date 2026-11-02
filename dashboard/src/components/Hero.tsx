import type { MutableRefObject } from "react";
import type { SanaeState, Message, OrbMode } from "../types";
import LiveFace from "./Face";

const LABELS: Record<OrbMode, [string, string]> = {
  idle: ["Here with you", "Say the wake word or type to me below"],
  listening: ["I'm listening", "Go ahead, take your time"],
  transcribing: ["Catching that", "Turning your words into text"],
  thinking: ["Hmm, let me think", "Working out what to do"],
  speaking: ["Talking", "Answering out loud"],
  alert: ["I need your OK", "Say yes or no, or tap a button on the right"],
  offline: ["Asleep", "Start me up to connect"],
};

type Props = {
  mode: OrbMode;
  emotion: string;
  level: MutableRefObject<number>;
  lastWake: number;
  state: SanaeState;
  messages: Message[];
};

export default function Hero({ mode, emotion, level, lastWake, state, messages }: Props) {
  const [title, sub] = LABELS[mode];
  const lastYou = [...messages].reverse().find((m) => m.role === "you");
  const hb = state.heartbeat || {};
  const phrase = state.wake_phrase && !state.wake_phrase.startsWith("(") ? state.wake_phrase : null;

  return (
    <section className={`hero panel mode-${mode}`}>
      <div className="face-wrap">
        <LiveFace mode={mode} emotion={emotion} level={level} wakeAt={lastWake} />
      </div>
      <div className="hero-info">
        <div className="label">right now</div>
        <h1 className="hero-title">{title}</h1>
        <p className="hero-sub">{sub}</p>

        <div className="hero-heard">
          <div className="label">you said</div>
          <div className="heard-text">{lastYou ? `“${lastYou.text}”` : "Nothing yet today"}</div>
        </div>

        <div className="hero-stats">
          <Stat k="wake word" v={phrase ? `“${phrase}”` : state.mode === "text" ? "text mode" : "—"} tint="peach" />
          <Stat k="hearing" v={state.stt || "—"} tint="mint" />
          <Stat k="mic" v={hb.expected ? `${Math.round((100 * hb.frames) / hb.expected)}% · ${hb.level_dbfs} dB` : "—"} tint="butter" />
          <Stat k="deep thinking" v={state.planner_model || "—"} tint="lavender" />
        </div>
      </div>
    </section>
  );
}

function Stat({ k, v, tint }: { k: string; v: string; tint: string }) {
  return (
    <div className={`stat tint-${tint}`}>
      <div className="label">{k}</div>
      <div className="stat-v">{v}</div>
    </div>
  );
}
