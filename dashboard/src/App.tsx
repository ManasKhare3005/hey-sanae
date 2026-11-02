import { assistantName } from "./name";
import { useCallback, useState } from "react";
import Conversation from "./components/Conversation";
import Drawer, { type Tab } from "./components/Drawer";
import Hero from "./components/Hero";
import { Activity, Approvals } from "./components/SidePanels";
import TopBar from "./components/TopBar";
import { relative } from "./format";
import { useSanae } from "./useSanae";

export default function App() {
  const sanae = useSanae();
  const [drawer, setDrawer] = useState<Tab | null>(null);
  const close = useCallback(() => setDrawer(null), []);
  const next = sanae.state.next_reminder;
  const hb = sanae.state.heartbeat || {};

  return (
    <div className={`app mode-${sanae.orbMode}`}>
      <div className="backdrop" aria-hidden />
      <TopBar state={sanae.state} connected={sanae.connected} stage={sanae.stage} emotion={sanae.emotion} />

      <main className="main">
        <div className="center">
          <Hero mode={sanae.orbMode} emotion={sanae.emotion} level={sanae.level} lastWake={sanae.lastWake} state={sanae.state} messages={sanae.messages} />
          <Conversation messages={sanae.messages} connected={sanae.connected} userName={sanae.state.user} emotion={sanae.emotion} />
        </div>
        <div className="right">
          <Approvals approvals={sanae.approvals} />
          <Activity events={sanae.activity} />
        </div>
      </main>

      <footer className="bottombar panel">
        <BarTile icon="◷" tint="butter" label="next reminder" onClick={() => setDrawer("reminders")}
          value={next ? `${next.text} · ${relative(next.due)}` : "none"} />
        <BarTile icon="✦" tint="lavender" label="memory" value="what I know ›" onClick={() => setDrawer("memory")} />
        <BarTile icon="✎" tint="peach" label="notes" rec={!!sanae.recording} onClick={() => setDrawer("notes")}
          value={sanae.recording ? `● recording ${sanae.recording}` : "meetings & lectures ›"} />
        <BarTile icon="✓" tint="mint" label="accuracy" value="test results ›" onClick={() => setDrawer("accuracy")} />
        <BarTile icon="⛉" tint="accent" label="privacy" value="your data ›" onClick={() => setDrawer("privacy")} />
        <BarTile icon="☏" tint="mint" label="phone" value="pair ›" onClick={() => setDrawer("phone")} />
        <div className="bar-spacer" />
        <div className="bar-btn static">
          <span className="label">listener</span>
          <span className={`bar-value ${hb.ok === false ? "warn" : ""}`}>
            {hb.expected ? (hb.ok === false ? "falling behind" : "healthy") : sanae.state.mode === "text" ? "text mode" : "—"}
          </span>
        </div>
        <div className="bar-btn static">
          <span className="label">api</span>
          <span className="bar-value"><a href="/api/docs" target="_blank" rel="noreferrer">/api/docs</a></span>
        </div>
      </footer>

      {!sanae.connected && (
        <div className="offline-banner">{assistantName()} is asleep. Start her with <code>start_sanae.bat</code> (reconnecting by itself)…</div>
      )}
      <Drawer open={drawer} onClose={close} onTab={setDrawer} revision={sanae.revision} />
    </div>
  );
}

function BarTile({ icon, tint, label, value, rec, onClick }: { icon: string; tint: string; label: string; value: string; rec?: boolean; onClick: () => void }) {
  return (
    <button className={`bar-btn ${rec ? "rec" : ""}`} onClick={onClick}>
      <span className={`bar-icon tint-${tint}`}>{icon}</span>
      <span className="bar-text">
        <span className="label">{label}</span>
        <span className="bar-value">{value}</span>
      </span>
    </button>
  );
}
