import { useEffect, useState } from "react";
import type { SanaeState } from "../types";
import { FaceAvatar } from "./Face";

type Props = { state: SanaeState; connected: boolean; stage: string; emotion: string };

function Pill({ label, value, ok, title }: { label: string; value: string; ok: boolean | null; title?: string }) {
  return (
    <div className={`pill ${ok === null ? "" : ok ? "ok" : "bad"}`} title={title}>
      <span className="dot" />
      <span className="pill-label">{label}</span>
      <span className="pill-value">{value}</span>
    </div>
  );
}

function greeting(h: number) {
  if (h < 5) return "Up late";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  if (h < 22) return "Good evening";
  return "Good night";
}

export default function TopBar({ state, connected, stage, emotion }: Props) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const s = state.services || {};
  const models = Array.isArray(s.models) ? s.models : [];
  const gpu = s.gpu && "vram_used_mb" in s.gpu ? s.gpu : null;
  const fast = models.find((m) => m.name.startsWith((state.fast_model || "").split(":")[0]));
  const onGpu = fast ? Math.round((fast.vram_mb / Math.max(1, fast.size_mb)) * 100) : 0;
  const name = state.name || "Sanae";
  const down = Object.keys(s.down || {});

  return (
    <header className="topbar panel">
      <div className="brand">
        <FaceAvatar emotion={connected ? emotion : "sleepy"} size={44} />
        <div>
          <div className="brand-name">{name}</div>
          <div className="brand-sub">{greeting(now.getHours())}{state.user ? `, ${state.user}` : ""} ♡</div>
        </div>
        <div className={`status-chip ${connected ? "on" : "off"}`}>
          <span className="dot" />
          {connected ? stage || "online" : "asleep"}
        </div>
      </div>

      <div className="pills">
        <Pill label="brain" value={fast ? `${fast.name} · ${onGpu}% gpu` : state.fast_model ? "resting" : "…"} ok={connected ? !!fast || null : false}
          title="Language model loaded in Ollama and how much of it is on the GPU" />
        <Pill label="vram" value={gpu ? `${(gpu.vram_used_mb / 1024).toFixed(1)} / ${(gpu.vram_total_mb / 1024).toFixed(0)} GB` : "–"} ok={gpu ? gpu.vram_used_mb / gpu.vram_total_mb < 0.95 : null} />
        <Pill label="web" value={`${s.searxng === true ? "searxng" : "duckduckgo"} · browser ${s.browser ? "open" : "closed"}`}
          ok={s.searxng === true || s.browser ? true : null} title="Search (private SearXNG in Docker, or the DuckDuckGo fallback) and her Chrome window" />
        <Pill label="memory" value={s.memory ? "on" : "off"} ok={!!s.memory} />
        {down.length > 0 && (
          <Pill label="down" value={down.join(", ")} ok={false} title={down.map((d) => `${d}: ${s.down?.[d] ?? ""}`).join("\n")} />
        )}
      </div>

      <div className="clock">
        <div className="clock-time">{now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</div>
        <div className="clock-date">{now.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" })}</div>
      </div>
    </header>
  );
}
