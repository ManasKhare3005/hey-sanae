/**
 * What she does, frame by frame, as Live2D parameter values: always alive (blinking, breathing,
 * a little sway, glancing around), following the mouse when it's near, the face of the emotion in
 * her last reply (tags from the model, e.g. [happy]), a pose per state (listening leans in,
 * thinking looks up and tilts, asleep closes her eyes), lip sync from the voice's loudness, and
 * small triggered motions (nod, bounce, a startled pop on the wake word), and gestures with her
 * arms from the [wave] / [cheer] / [cover_face] tags, played one after another.
 *
 * Every value is eased toward its target, so changes blend instead of snapping.
 */
import type { LinkState } from "../avatar/link";

export type Mode = "idle" | "listening" | "thinking" | "speaking" | "paused" | "asleep";
export type Emotion = "neutral" | "happy" | "shy" | "laugh" | "thinking" | "sad" | "surprised" | "sleepy";

export function modeOf(s: LinkState): Mode {
  if (!s.online || s.asleep) return "asleep";
  if (s.speech) return "speaking";
  const st = s.stage;
  if (st === "paused") return "paused";
  if (st === "speaking") return "speaking";
  if (st === "thinking") return "thinking";
  if (st === "listening to command") return s.sttBusy ? "thinking" : "listening";   // transcribing = thinking
  return "idle";
}

/** The face parts an emotion sets (anything left out stays at the neutral value). */
type Face = {
  eyeOpen: number;      // 0 closed .. 1 open (1.15 wide)
  eyeSmile: number;     // 0 .. 1: eyes curve up
  browY: number;        // -1 down .. 1 up
  browAngle: number;    // -1 .. 1
  browForm: number;     // -1 .. 1
  mouthForm: number;    // -1 frown .. 1 smile
  mouthOpen: number;    // resting mouth opening
  cheek: number;        // blush 0 .. 1
  tilt: number;         // head roll, degrees
  nodDown: number;      // head pitch, degrees (+ = down)
  gazeX: number; gazeY: number;   // where the eyes rest (-1..1)
};

const NEUTRAL: Face = { eyeOpen: 1, eyeSmile: 0, browY: 0, browAngle: 0, browForm: 0, mouthForm: 0.25, mouthOpen: 0,
                        cheek: 0, tilt: 0, nodDown: 0, gazeX: 0, gazeY: 0 };
export const EMOTIONS: Record<Emotion, Partial<Face>> = {
  neutral:   {},
  happy:     { eyeSmile: 0.55, browY: 0.35, mouthForm: 1, cheek: 0.25, tilt: 4 },
  shy:       { eyeSmile: 0.25, browY: -0.1, browAngle: -0.5, mouthForm: 0.35, cheek: 1, tilt: 7, nodDown: 6, gazeX: -0.55, gazeY: -0.45 },
  laugh:     { eyeOpen: 0.15, eyeSmile: 1, browY: 0.5, mouthForm: 1, mouthOpen: 0.45, cheek: 0.5, tilt: -3 },
  thinking:  { browY: 0.3, browAngle: 0.5, browForm: -0.5, mouthForm: -0.3, tilt: 14, gazeX: 0.8, gazeY: 0.85 },
  sad:       { eyeOpen: 0.75, browY: -0.25, browAngle: -0.8, browForm: -0.5, mouthForm: -1, tilt: -3, nodDown: 7, gazeY: -0.35 },
  surprised: { eyeOpen: 1.2, browY: 1, browForm: 0.4, mouthForm: -0.1, mouthOpen: 0.4, nodDown: -5 },
  sleepy:    { eyeOpen: 0.35, browY: -0.35, browAngle: -0.2, mouthForm: 0.1, tilt: -6, nodDown: 4 },
};
/** Each state's own touch, on top of the emotion. */
const MODES: Record<Mode, Partial<Face> & { lean?: number }> = {
  idle:      {},
  listening: { browY: 0.25, eyeOpen: 1.08, nodDown: -3, lean: 4 },   // attentive, leaning in
  thinking:  { gazeX: 0.8, gazeY: 0.85, tilt: 14, browForm: -0.4, mouthForm: -0.2 },
  speaking:  {},
  paused:    { eyeOpen: 0.85 },
  asleep:    { eyeOpen: 0, browY: -0.2, mouthForm: 0.2, tilt: -8, nodDown: 14 },
};

/**
 * Hiyori has two arm sets (pose3.json): A hangs down (resting), B is raised to the chest, with
 * ParamArmRB/LB swinging each arm out (+10) or in (-10) and ParamHandRB/LB opening (+10) or making
 * a fist (-10). Poses picked from canvas snapshots. b = how much of arm set B shows.
 */
type Arms = { b: number; rb: number; lb: number; hrb: number; hlb: number };
const REST_ARMS: Arms = { b: 0, rb: 0, lb: 0, hrb: 10, hlb: 10 };
type Pose = { arms: Partial<Arms>; face?: Partial<Face> };
export const GESTURES: Record<string, { seconds: number; pose: (t: number) => Pose; bounces?: number[] }> = {
  // right hand up beside her face, swinging out and back ~2 times a second
  wave: { seconds: 2.1, pose: (t) => ({ arms: { b: 1, rb: t < 0.3 ? 9 : 7 + 3 * Math.sin((t - 0.3) * Math.PI * 2 * 2.2), lb: -3 },
                                        face: { eyeSmile: 0.45, mouthForm: 1, tilt: 6, cheek: 0.2 } }) },
  // both fists up, two little hops
  cheer: { seconds: 1.6, pose: () => ({ arms: { b: 1, rb: 10, lb: 10, hrb: -10, hlb: -10 },
                                        face: { eyeSmile: 0.8, eyeOpen: 0.6, mouthForm: 1, mouthOpen: 0.3, browY: 0.5 } }),
           bounces: [0.1, 0.75] },
  // hands clasped under her chin, head down, eyes squeezed shut, blushing (Hiyori's arms don't reach higher)
  cover_face: { seconds: 2.6, pose: () => ({ arms: { b: 1, rb: -10, lb: -10 },
                                             face: { eyeOpen: 0.2, eyeSmile: 1, cheek: 1, nodDown: 11, mouthForm: 0.4, gazeY: -0.5, tilt: 5 } }) },
};

export type ParamSink = (id: string, value: number) => void;

const ease = (cur: number, target: number, rate: number, dt: number) => cur + (target - cur) * (1 - Math.exp(-rate * dt));
const rand = (a: number, b: number) => a + Math.random() * (b - a);

export class Brain {
  face: Face = { ...NEUTRAL };
  emotion: Emotion = "neutral";
  emotionUntil = 0;              // ms (performance.now) when the emotion fades back to the resting one
  resting: Emotion = "neutral";  // mood between replies
  private t = 0;
  private blinkAt = rand(1.5, 4);
  private blink = 0;             // 0 open .. 1 shut
  private saccade = { x: 0, y: 0, at: 0 };
  private gaze = { x: 0, y: 0 };
  private head = { x: 0, y: 0, z: 0 };
  private body = { x: 0, z: 0 };
  private cursor: { x: number; y: number } | null = null;
  private pop = 0;               // wake-word startle, decays
  private nods: number[] = [];   // start times (s) of queued nods
  private bounceAt = -10;
  private shakeAt = -10;         // "no": a little head shake
  private peekSide = 0;          // tucked in at the left (+1: lean right, into the screen) / right (-1) edge
  private peekLean = 0;
  private mouth = 0;
  private mouthForm = 0;
  private lastSpeechId = 0;
  private talkGlance = 0;
  private arms: Arms = { ...REST_ARMS };
  private queue: string[] = [];                                       // arm gestures waiting their turn
  private playing: { name: string; start: number } | null = null;

  /** Pointer relative to her eyes, in window heights (null = far away / unknown). */
  setCursor(x: number | null, y = 0) { this.cursor = x === null ? null : { x, y }; }

  /** Her mood: the face she relaxes back to between replies. */
  setResting(e: string) {
    const name = (e in EMOTIONS ? e : "neutral") as Emotion;
    if (this.emotion === this.resting) this.emotion = name;
    this.resting = name;
  }

  setEmotion(e: string, holdMs = 6000) {
    const name = (e in EMOTIONS ? e : "neutral") as Emotion;
    this.emotion = name;
    this.emotionUntil = performance.now() + holdMs;
    if (name === "laugh" || name === "happy") this.bounceAt = this.t;
    if (name === "surprised") this.pop = 1;
  }

  /** nod plays at once; arm gestures (wave, cheer, cover_face) queue up and play one after another. */
  gesture(name: string) {
    if (name === "nod") { this.nods.push(this.t + 0.15); return; }
    if (name === "bounce") { this.bounceAt = this.t; return; }
    if (name === "shake") { this.shakeAt = this.t; return; }
    if (!(name in GESTURES)) return;
    const last = this.queue.length ? this.queue[this.queue.length - 1] : this.playing?.name;
    if (last === name || this.queue.length >= 3) return;              // no stutter, no pile-up
    this.queue.push(name);
    if (name === "cover_face" && this.emotion !== "shy") this.setEmotion("shy", 4000);
  }

  /** The gesture playing now (for checks), or null. */
  get gesturePlaying() { return this.playing?.name ?? null; }

  wake() { this.pop = 1; this.blinkAt = this.t + 0.05; }

  /** Docked at a screen edge ("left" / "right") or not (""): she leans in toward the screen. */
  setPeek(side: string) { this.peekSide = side === "left" ? 1 : side === "right" ? -1 : 0; }

  update(mode: Mode, link: LinkState, dt: number, set: ParamSink) {
    this.t += dt;
    const now = performance.now();
    if (now > this.emotionUntil && this.emotion !== this.resting && mode !== "speaking") this.emotion = this.resting;

    // ----- arm gestures: the next one in the queue starts when the last has finished -----
    if (mode === "asleep") { this.queue = []; this.playing = null; }
    if (this.playing && this.t - this.playing.start > GESTURES[this.playing.name].seconds) this.playing = null;
    if (!this.playing && this.queue.length) {
      this.playing = { name: this.queue.shift()!, start: this.t };
      (GESTURES[this.playing.name].bounces ?? []).forEach((d) => setTimeout(() => { this.bounceAt = this.t; }, d * 1000));
    }
    const pose: Pose | null = this.playing ? GESTURES[this.playing.name].pose(this.t - this.playing.start) : null;
    const armTarget: Arms = { ...REST_ARMS, ...(pose?.arms ?? {}) };
    // arms swing in quickly; set B fades in only once they're on the way (no ghosting of both sets)
    for (const k of ["rb", "lb", "hrb", "hlb"] as const) this.arms[k] = ease(this.arms[k], armTarget[k], pose ? 14 : 8, dt);
    this.arms.b = ease(this.arms.b, armTarget.b, 16, dt);

    // ----- the face: emotion, then the state's touch, then the gesture's, eased -----
    const emo = mode === "asleep" ? {} : EMOTIONS[this.emotion];
    const m = MODES[mode];
    const target: Face = { ...NEUTRAL, ...emo };
    for (const [k, v] of Object.entries(m)) {
      if (k === "lean") continue;
      const key = k as keyof Face;
      // gaze / tilt from the state win over the emotion's; the rest add up
      target[key] = key.startsWith("gaze") || key === "tilt" || mode === "asleep" ? (v as number) : target[key] + (v as number) - NEUTRAL[key];
    }
    if (pose?.face) Object.assign(target, pose.face);
    const rate = mode === "asleep" ? 1.5 : 6;
    for (const k of Object.keys(target) as (keyof Face)[]) this.face[k] = ease(this.face[k], target[k], rate, dt);
    const f = this.face;

    // ----- blinking (none while asleep or laughing with eyes shut) -----
    if (this.t >= this.blinkAt) {
      this.blink = 1;
      this.blinkAt = this.t + (Math.random() < 0.15 ? 0.25 : rand(2, 5.5));     // sometimes a double blink
    }
    this.blink = Math.max(0, this.blink - dt / 0.13);
    const blinkShut = Math.sin(Math.min(1, this.blink) * Math.PI / 2);
    const eyeOpen = Math.max(0, f.eyeOpen * (1 - blinkShut) + this.pop * 0.25);

    // ----- where she looks: the mouse if near, else little glances; thinking looks up and away -----
    if (this.t > this.saccade.at) {
      const wide = mode === "thinking" ? 0.25 : mode === "idle" ? 0.45 : 0.18;
      this.saccade = { x: rand(-wide, wide), y: rand(-wide * 0.6, wide * 0.6), at: this.t + rand(0.8, 3.2) };
    }
    let gx = f.gazeX + this.saccade.x, gy = f.gazeY + this.saccade.y;
    if (this.cursor && mode !== "asleep" && mode !== "thinking") {
      gx = Math.max(-1, Math.min(1, this.cursor.x * 1.6));
      gy = Math.max(-1, Math.min(1, -this.cursor.y * 1.6));
    }
    if (mode === "speaking" && link.speech) {
      if (link.speech.id !== this.lastSpeechId) {           // new sentence: sometimes glance away first
        this.lastSpeechId = link.speech.id;
        this.talkGlance = Math.random() < 0.35 ? this.t + 0.7 : 0;
        if (Math.random() < 0.5) this.nods.push(this.t + rand(0.3, 1.2));
      }
      if (this.t < this.talkGlance) { gx += 0.5; gy += 0.3; }
    }
    this.peekLean = ease(this.peekLean, this.peekSide, 3, dt);
    if (!this.cursor) gx += this.peekLean * 0.35;
    this.gaze.x = ease(this.gaze.x, gx, 14, dt);
    this.gaze.y = ease(this.gaze.y, gy, 14, dt);

    // ----- head and body follow the eyes a little, plus breathing sway -----
    const breath = 0.5 + 0.5 * Math.sin(this.t * 2 * Math.PI / (mode === "asleep" ? 5 : 3.6));
    let nod = 0;
    this.nods = this.nods.filter((s) => this.t - s < 0.6);
    for (const s of this.nods) if (this.t >= s) nod += Math.sin(((this.t - s) / 0.6) * Math.PI) * 9;
    const bounce = this.t - this.bounceAt < 0.7 ? Math.sin(((this.t - this.bounceAt) / 0.7) * Math.PI * 2) * Math.exp(-(this.t - this.bounceAt) * 3) : 0;
    this.pop = Math.max(0, this.pop - dt * 1.6);
    const sway = Math.sin(this.t * 0.7) * 2.2 + Math.sin(this.t * 0.31) * 1.3;
    const st = this.t - this.shakeAt;
    const shake = st < 0.8 ? Math.sin(st * Math.PI * 2 * 2.5) * 11 * (1 - st / 0.8) : 0;
    this.head.x = ease(this.head.x, this.gaze.x * 22 + sway * 0.6 + shake, st < 0.8 ? 25 : 5, dt);
    this.head.y = ease(this.head.y, this.gaze.y * 14 - f.nodDown - (m.lean ?? 0) + this.pop * 8, 5, dt);
    this.head.z = ease(this.head.z, f.tilt + Math.sin(this.t * 0.45) * 1.5 - this.peekLean * 9, 4, dt);
    this.body.x = ease(this.body.x, this.gaze.x * 4 + sway + this.peekLean * 6, 3, dt);
    this.body.z = ease(this.body.z, Math.sin(this.t * 0.5) * 1.5 + bounce * 3 - this.peekLean * 7, 4, dt);

    // ----- lip sync: loudness opens the mouth, vowel shape changes its form -----
    let open = f.mouthOpen, form = f.mouthForm;
    const sp = link.speech;
    if (sp && sp.env.length) {
      const i = Math.floor(((now - sp.startAt) / 1000) * sp.rate);
      if (i >= 0 && i < sp.env.length) {
        open = Math.max(open, Math.min(1, sp.env[i] * 1.05));
        const v = sp.vis[i];                                   // aa ih ou ee oh
        if (v) form += (v[1] + v[3]) * 0.6 - (v[2] + v[4]) * 0.8;
      }
    }
    this.mouth = ease(this.mouth, open, 30, dt);
    this.mouthForm = ease(this.mouthForm, Math.max(-1, Math.min(1, form)), 12, dt);

    // ----- out to the model -----
    set("ParamAngleX", this.head.x);
    set("ParamAngleY", this.head.y + nod * -1);
    set("ParamAngleZ", this.head.z);
    set("ParamBodyAngleX", this.body.x);
    set("ParamBodyAngleY", bounce * 6 - (m.lean ?? 0) * 0.5);
    set("ParamBodyAngleZ", this.body.z);
    set("ParamBreath", breath);
    set("ParamEyeLOpen", eyeOpen);
    set("ParamEyeROpen", eyeOpen);
    set("ParamEyeLSmile", f.eyeSmile);
    set("ParamEyeRSmile", f.eyeSmile);
    set("ParamEyeBallX", this.gaze.x);
    set("ParamEyeBallY", this.gaze.y);
    set("ParamBrowLY", f.browY);
    set("ParamBrowRY", f.browY);
    set("ParamBrowLAngle", f.browAngle);
    set("ParamBrowRAngle", f.browAngle);
    set("ParamBrowLForm", f.browForm);
    set("ParamBrowRForm", f.browForm);
    set("ParamMouthForm", this.mouthForm);
    set("ParamMouthOpenY", this.mouth);
    set("ParamCheek", f.cheek);
    set("ParamShoulder", bounce * 0.6 + (breath - 0.5) * 0.15);
    const b = this.arms.b < 0.02 ? 0 : this.arms.b > 0.98 ? 1 : this.arms.b;
    set("PartArmA", 1 - b);
    set("PartArmB", b);
    set("ParamArmRB", this.arms.rb);
    set("ParamArmLB", this.arms.lb);
    set("ParamHandRB", this.arms.hrb);
    set("ParamHandLB", this.arms.hlb);
  }
}
