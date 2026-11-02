import { useEffect, useRef, type MutableRefObject } from "react";
import type { OrbMode } from "../types";

const FACES = new Set(["happy", "laugh", "neutral", "sad", "shy", "sleepy", "surprised", "thinking"]);

/** Path of her face picture for an emotion (falls back to happy). */
export const faceSrc = (emotion?: string) => `/faces/${emotion && FACES.has(emotion) ? emotion : "happy"}.webp`;

/** Her face in a soft circle (no motion): headers, chat bubbles. */
export function FaceAvatar({ emotion, size = 36 }: { emotion?: string; size?: number }) {
  return (
    <span className="face-avatar" style={{ width: size, height: size }}>
      <img src={faceSrc(emotion)} alt="" draggable={false} />
    </span>
  );
}

type Props = { mode: OrbMode; emotion: string; level: MutableRefObject<number>; wakeAt: number };

/** The big live face: breathes, glows with the mic, a spinning arc while she thinks, pulses while she talks. */
export default function LiveFace({ mode, emotion, level, wakeAt }: Props) {
  const root = useRef<HTMLDivElement>(null);

  // mic level -> CSS variable, smoothed, without re-rendering
  useEffect(() => {
    let raf = 0;
    let shown = 0;
    const tick = () => {
      const target = mode === "listening" ? level.current : mode === "speaking" ? 0.35 + 0.25 * Math.sin(Date.now() / 140) : 0;
      shown += (target - shown) * 0.18;
      root.current?.style.setProperty("--lvl", shown.toFixed(3));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [mode, level]);

  const face = mode === "offline" ? "sleepy" : mode === "thinking" || mode === "transcribing" ? "thinking" : emotion;

  // a little hop when the wake word is heard
  useEffect(() => {
    const el = root.current;
    if (!el || !wakeAt) return;
    el.classList.remove("lf-wake");
    void el.offsetWidth;
    el.classList.add("lf-wake");
    const t = window.setTimeout(() => el.classList.remove("lf-wake"), 1200);
    return () => window.clearTimeout(t);
  }, [wakeAt]);

  return (
    <div ref={root} className={`live-face lf-${mode}`}>
      <div className="lf-halo" />
      <div className="lf-ring" />
      <div className="lf-arc" />
      <div className="lf-disc">
        <img key={face} src={faceSrc(face)} alt="" draggable={false} />
      </div>
      <span className="lf-spark s1">✦</span>
      <span className="lf-spark s2">✧</span>
      <span className="lf-spark s3">✦</span>
    </div>
  );
}
