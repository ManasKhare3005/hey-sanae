/**
 * A speech bubble above her head: what she's saying, word by word in step with the voice (each
 * sentence's words spread over its audio), "…" while she thinks, gone ~2 s after she stops.
 * Sentences of one reply add up; only the last few lines show. Click it to dismiss.
 */
import type { Mode } from "./brain";
import "./bubble.css";
import type { LinkState } from "../avatar/link";

const HOLD_MS = 2200;        // stays up this long after the last word
const MAX_CHARS = 120;       // about three lines at this width; older words scroll off the top
const NEW_REPLY_MS = 2500;   // a sentence starting later than this after the last one ends starts a fresh bubble

export class Bubble {
  readonly el: HTMLDivElement;
  private text: HTMLDivElement;
  private done = "";                      // sentences already fully shown
  private words: string[] = [];           // the sentence being spoken
  private sentence = { id: 0, start: 0, ms: 0 };
  private lastWordAt = 0;
  private shown = false;
  private thinking = false;
  private dismissed = 0;                  // speech id the user clicked away

  constructor(parent: HTMLElement, topPx: number) {
    this.el = document.createElement("div");
    this.el.id = "bubble";
    this.el.style.setProperty("--bubble-h", `${topPx}px`);
    this.text = document.createElement("div");
    this.text.className = "text";
    this.el.appendChild(this.text);
    parent.appendChild(this.el);
  }

  get visible() { return this.shown; }

  dismiss() {
    this.dismissed = this.sentence.id;
    this.done = "";
    this.words = [];
    this.set(false);
  }

  /** Called every frame. */
  update(mode: Mode, link: LinkState, now: number) {
    const sp = link.speech;
    const thinking = mode === "thinking" && !sp;
    if (thinking && !this.thinking) { this.done = ""; this.words = []; }           // a new question: clear the old answer
    if (sp && sp.text && sp.id !== this.sentence.id) {
      if (this.sentence.id && now - this.lastWordAt > NEW_REPLY_MS) this.done = "";       // a new reply
      else if (this.words.length) this.done = (this.done + " " + this.words.join(" ")).trim();
      this.words = sp.text.trim().split(/\s+/);
      this.sentence = { id: sp.id, start: sp.startAt, ms: Math.max(400, sp.duration * 1000) };
    }
    let body = "";
    if (this.words.length) {
      const share = Math.min(1, Math.max(0, (now - this.sentence.start) / (this.sentence.ms * 0.92)));
      const n = sp && sp.id === this.sentence.id ? Math.max(1, Math.ceil(share * this.words.length)) : this.words.length;
      body = (this.done + " " + this.words.slice(0, n).join(" ")).trim();
      if (sp && sp.id === this.sentence.id) this.lastWordAt = now;
    }
    if (thinking) this.lastWordAt = now;
    const want = thinking || (!!body && this.sentence.id !== this.dismissed && now - this.lastWordAt < HOLD_MS);
    if (!want && this.shown && now - this.lastWordAt >= HOLD_MS) { this.done = ""; this.words = []; }
    if (thinking !== this.thinking) { this.thinking = thinking; this.el.classList.toggle("thinking", thinking); }
    if (want) {
      const shownText = thinking && !body ? "" : body.length > MAX_CHARS ? "…" + body.slice(body.length - MAX_CHARS).replace(/^\S*\s/, "") : body;
      if (this.text.textContent !== shownText) this.text.textContent = shownText;
    }
    this.set(want);
  }

  private set(on: boolean) {
    if (on === this.shown) return;
    this.shown = on;
    this.el.classList.toggle("on", on);
  }
}
