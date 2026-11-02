/**
 * The desktop companion as a Live2D character (pixi.js + pixi-live2d-display; Cubism Core is
 * loaded by live2d.html from /live2d/, downloaded by setup.ps1). She follows Sanae's events over the
 * dashboard WebSocket (link.ts) and brain.ts turns them into parameter values every frame.
 *
 * URL options (the desktop window, sanae/avatar, fills them in from config.yaml):
 *   ?fps=60 ?asleep_fps=15 ?busy_fps=30 ?idle_fps=30   frame caps (0 = every refresh)
 *   ?ws=...  ?lipsync_ms=80  ?standalone=1  ?debug=1  ?scale=1.5 (render pixels per screen pixel)
 *   ?model=avatar/hiyori/Hiyori.model3.json   ?frame=0.5 (share of the model's height in view, from the top)
 *   ?glow=1  ?glow_color=9fe8ff  ?bubble=84 (px strip above her for the speech bubble, 0 = no bubbles)
 * Mouse: click = talk (like the wake word), double click = open the Sanae app, drag = move the window.
 * Clicks only land on her: ten times a second her shape is worked out from the model's own meshes
 * (no GPU read-back) and handed to the window, which clips itself to it.
 */
import * as PIXI from "pixi.js";
import { GlowFilter } from "@pixi/filter-glow";
import { Live2DModel } from "pixi-live2d-display/cubism4";
import { connect } from "../avatar/link";
import { Brain, EMOTIONS, modeOf, type Emotion, type Mode } from "./brain";
import { Bubble } from "./bubble";

const params = new URLSearchParams(location.search);
// a value that isn't a number (the launcher's VRM-style frame=upper) falls back to the default: NaN would scale her to nothing
const num = (k: string, d: number) => { const v = Number(params.get(k) ?? NaN); return Number.isFinite(v) ? v : d; };
const FPS = num("fps", 60);
const ASLEEP_FPS = num("asleep_fps", 15);
const BUSY_FPS = num("busy_fps", 30);
const IDLE_FPS = num("idle_fps", 30);
const WS = params.get("ws") || "ws://127.0.0.1:8765/api/ws";
const LIPSYNC_MS = num("lipsync_ms", 80);
const STANDALONE = params.get("standalone") === "1";
const DEBUG = params.get("debug") === "1";
const SCALE = num("scale", 1.5);
const MODEL = params.get("model") || "avatar/hiyori/Hiyori.model3.json";
const FRAME = num("frame", 0.37);
const TOP = num("top", -0.17);          // where the model's canvas starts, in window heights (its top is empty space)
const GLOW = params.get("glow") !== "0";
const GLOW_COLOR = parseInt(params.get("glow_color") || "9fe8ff", 16);
const BUBBLE = num("bubble", 0);
const CLOSE_ASLEEP_S = num("close_asleep", 0);   // models asleep this long -> close the window (0 = never)
if (DEBUG) document.body.classList.add("debug");

const app = new PIXI.Application({
  backgroundAlpha: 0, antialias: true, autoStart: false, resizeTo: window, autoDensity: true,
  resolution: window.devicePixelRatio * SCALE, powerPreference: "low-power",
});
document.body.appendChild(app.view as HTMLCanvasElement);

type Api = {
  cursor?: () => Promise<[number, number, number, number] | null>;
  listen?: () => void; open_app?: () => void; reset_position?: () => void; busy?: (b: boolean) => void;
  hide?: () => void; show?: () => void;
  report?: (x: unknown) => void; activity?: (b: boolean) => void; shape?: (cols: number, rows: number, runs: number[][]) => void;
  snapshot?: (x: string, mode?: string) => void; toggle?: () => void; close?: () => void;
};
const api = (): Api | undefined => (window as unknown as { pywebview?: { api?: Api } }).pywebview?.api;

const brain = new Brain();
let micLive = false;           // conversation window: she's listening without the wake word
let micLiveUntil = 0;
const link = connect(WS, LIPSYNC_MS, {
  onWake: () => brain.wake(),
  onToggle: () => api()?.toggle?.(),
  onOfflineLong: () => { if (!STANDALONE) api()?.close?.(); },
  onReset: () => api()?.reset_position?.(),
  onHide: () => { brain.gesture("wave"); setTimeout(() => api()?.hide?.(), 1800); },   // a little wave goodbye
  onShow: () => { api()?.show?.(); brain.wake(); setTimeout(() => brain.gesture("wave"), 250); },
  onBusy: (b) => api()?.busy?.(b),
  // wave (greeting / first wake in a while), nod / shake (yes / no), bounce (a tool did something);
  // chin / tilt / shrug are the 3D model's: here the thinking pose and her emotion tags cover them
  onGesture: (name) => brain.gesture(name),
  onEmotion: (emotion, gestures) => {
    brain.setEmotion(emotion, 7000);
    setTimeout(() => gestures.forEach((g) => brain.gesture(g)), 300);      // just after the voice starts; brain.ts queues them
  },
  onListen: (mode, until) => { micLive = mode === "conversation"; micLiveUntil = until; },
  onRest: (emotion) => brain.setResting(emotion),
});

// ----- the model -----
let model: Live2DModel | null = null;
const values = new Map<string, number>();
const raw = new Map<string, number>();   // debug: values set by hand (sanaeAvatar.raw), applied last
const glow = new GlowFilter({ distance: 10, outerStrength: 1.4, innerStrength: 0, color: GLOW_COLOR, quality: 0.15 });

async function load() {
  const m = await Live2DModel.from(MODEL, { autoUpdate: false, autoHitTest: false, autoFocus: false });
  const im = m.internalModel as unknown as { eyeBlink?: unknown; breath?: unknown; pose?: unknown; on: (e: string, f: () => void) => void;
                                             coreModel: { setParameterValueById: (id: string, v: number) => void;
                                                          setPartOpacityById: (id: string, v: number) => void } };
  im.eyeBlink = undefined;       // brain.ts blinks, breathes and sways herself
  im.breath = undefined;
  im.pose = undefined;           // ...and switches between the two arm sets (pose3.json) herself
  im.on("afterMotionUpdate", () => {
    for (const [id, v] of values) {
      if (id.startsWith("Part")) im.coreModel.setPartOpacityById(id, v);
      else im.coreModel.setParameterValueById(id, v);
    }
    for (const [id, v] of raw) {
      if (id.startsWith("Part")) im.coreModel.setPartOpacityById(id, v);
      else im.coreModel.setParameterValueById(id, v);
    }
  });
  if (GLOW) m.filters = [glow];
  app.stage.addChild(m);
  model = m;
  layout();
}
load().catch((err) => { stats.textContent = `couldn't load ${MODEL}: ${err}`; document.body.classList.add("debug"); });

/** Bust framing: the top FRAME of the model fills the window height (below the bubble strip), centred. */
function layout() {
  if (!model) return;
  const w = window.innerWidth, h = window.innerHeight - BUBBLE;
  const natural = model.height / model.scale.y;
  const s = (h * 0.98) / (natural * FRAME);
  model.scale.set(s);
  model.x = (w - model.width) / 2;
  model.y = BUBBLE + h * TOP;
}
const bubble = BUBBLE > 0 ? new Bubble(document.body, BUBBLE) : null;
window.addEventListener("resize", layout);

/** Her eyes on screen (window px), for looking at the mouse. */
function eyes(): [number, number] {
  if (!model) return [window.innerWidth / 2, window.innerHeight * 0.3];
  return [model.x + model.width / 2, model.y + model.height * 0.2];
}

// ----- frame loop with a cap -----
let hidden = false;
let last = 0;
let lastT = performance.now();
let cap = FPS;
let wasActive = false;
let asleepSince = 0;
let frames = 0, fps = 0, fpsAt = performance.now(), frameMsSum = 0, statFrames = 0;
// ?mode=idle|speaking|...: hold one state (benchmarks); "speaking" also keeps the mouth going
let override: { mode?: Mode } = params.get("mode") ? { mode: params.get("mode") as Mode } : {};
if (override.mode === "speaking") {
  setInterval(() => {
    const env = Array.from({ length: 180 }, (_, i) => Math.abs(Math.sin(i / 4)) * (0.5 + Math.random() * 0.5));
    link.speech = { env, vis: [], rate: 60, duration: 3, startAt: performance.now(), text: "", id: Date.now() };
  }, 3000);
}

function currentCap(mode: Mode): number {
  if (mode === "asleep") return ASLEEP_FPS;
  if (link.sttBusy) return BUSY_FPS;
  if (mode === "idle" && !micLive) return IDLE_FPS;
  return FPS;
}

function frame(now: number) {
  requestAnimationFrame(frame);
  const mode = override.mode ?? modeOf(link);
  cap = currentCap(mode);
  const minGap = cap > 0 ? 1000 / cap : 0;
  if (hidden || document.hidden || (minGap && now - last < minGap - 1)) return;
  last = now;
  const t0 = performance.now();
  const dt = Math.min((now - lastT) / 1000, 0.1);
  lastT = now;
  if (micLive && Date.now() > micLiveUntil) micLive = false;
  // "go to sleep": she dozes off, then (avatar.close_when_asleep) the window closes to free its memory;
  // Sanae opens it again when the models wake up
  if (CLOSE_ASLEEP_S > 0 && link.online && link.asleep && !override.mode) {
    asleepSince ||= now;
    if (now - asleepSince > CLOSE_ASLEEP_S * 1000) { asleepSince = Infinity; api()?.close?.(); }
  } else if (asleepSince !== Infinity) asleepSince = 0;
  bubble?.update(mode, link, now);
  // tell the window when she's busy (talking, listening, thinking, a bubble or gesture): tucked in at a screen edge she peeks out
  const active = (mode !== "idle" && mode !== "asleep") || micLive || !!bubble?.visible || !!brain.gesturePlaying;
  if (active !== wasActive) { wasActive = active; api()?.activity?.(active); }
  if (model) {
    brain.update(mode, link, dt, (id, v) => values.set(id, v));
    model.update(dt * 1000);
    if (GLOW) {        // the glow breathes a little; brighter while the mic is open without the wake word
      const live = micLive || mode === "listening";
      glow.outerStrength = (live ? 2.4 : 1.2) + Math.sin(now / (live ? 260 : 900)) * (live ? 0.6 : 0.25);
    }
  }
  app.render();
  if (captureLabel) { api()?.snapshot?.((app.view as HTMLCanvasElement).toDataURL("image/png"), captureLabel); captureLabel = ""; }
  if (model && now - shapeAt > SHAPE_EVERY) sendShape(now);
  frameMsSum += performance.now() - t0;
  statFrames++;
  frames++;
  if (now - fpsAt >= 1000) { fps = (frames * 1000) / (now - fpsAt); frames = 0; fpsAt = now; }
}
requestAnimationFrame(frame);

// ----- the mouse: she looks at it when it's near -----
let cursorBusy = false;
let lookOverride: [number, number] | null = null;
const POLL_CURSOR = params.get("cursor") !== "0";
setInterval(async () => {
  if (hidden || cursorBusy || !POLL_CURSOR) return;
  if (lookOverride) { brain.setCursor(lookOverride[0], lookOverride[1]); return; }
  const a = api();
  if (!a?.cursor) return;
  cursorBusy = true;
  try {
    const c = await a.cursor();
    if (!c) { brain.setCursor(null); return; }
    const [cx, cy, , h] = c;
    const [ex, ey] = eyes();
    const x = (cx - ex) / h, y = (cy - ey) / h;
    brain.setCursor(Math.hypot(x, y) < 3.5 ? x : null, y);
  } catch { /* closing */ } finally { cursorBusy = false; }
}, 50);

// ----- clicks: one = talk, two = open the app; a drag (the window moves) is neither -----
let down: { x: number; y: number; at: number } | null = null;
let clickTimer = 0;
window.addEventListener("mousedown", (e) => { if (e.button === 0) down = { x: e.screenX, y: e.screenY, at: performance.now() }; });
window.addEventListener("mouseup", (e) => {
  if (e.button !== 0 || !down) return;
  const moved = Math.hypot(e.screenX - down.x, e.screenY - down.y);
  const quick = performance.now() - down.at < 400;
  down = null;
  if (moved > 4 || !quick) return;
  if (bubble?.visible && (e.target as HTMLElement | null)?.closest?.("#bubble")) { bubble.dismiss(); return; }   // click the bubble: away
  if (clickTimer) { clearTimeout(clickTimer); clickTimer = 0; api()?.open_app?.(); return; }
  clickTimer = window.setTimeout(() => {
    clickTimer = 0;
    brain.setEmotion("surprised", 900);          // a little "oh!" then she listens
    brain.wake();
    api()?.listen?.();
  }, 280);
});

// ----- outline from the meshes: the window only takes clicks where she's drawn -----
const SHAPE_CELL = 4, SHAPE_GROW = 2, SHAPE_EVERY = 100;
let shapeAt = 0;
let lastShape = "-";

type Core = {
  getDrawableCount(): number; getDrawableVertexIndices(i: number): Uint16Array;
  getDrawableOpacity(i: number): number; getDrawableDynamicFlagIsVisible(i: number): boolean;
};

function sendShape(now: number) {
  shapeAt = now;
  const a = api();
  if (!model) return;
  const cols = Math.ceil(window.innerWidth / SHAPE_CELL), rows = Math.ceil(window.innerHeight / SHAPE_CELL);
  const solid = new Uint8Array(cols * rows);
  const im = model.internalModel as unknown as { coreModel: Core; getDrawableVertices(i: number): Float32Array; localTransform: PIXI.Matrix };
  const core = im.coreModel;
  const m = model.worldTransform.clone().append(im.localTransform);
  const res = 1 / SHAPE_CELL;
  for (let d = 0; d < core.getDrawableCount(); d++) {
    if (!core.getDrawableDynamicFlagIsVisible(d) || core.getDrawableOpacity(d) < 0.1) continue;
    const v = im.getDrawableVertices(d);
    const idx = core.getDrawableVertexIndices(d);
    const px = new Float32Array(v.length);
    for (let i = 0; i < v.length; i += 2) {
      px[i] = (m.a * v[i] + m.c * v[i + 1] + m.tx) * res;
      px[i + 1] = (m.b * v[i] + m.d * v[i + 1] + m.ty) * res;
    }
    for (let t = 0; t < idx.length; t += 3) fillTriangle(px, idx[t] * 2, idx[t + 1] * 2, idx[t + 2] * 2, solid, cols, rows);
  }
  if (bubble?.visible) {          // the bubble takes clicks (and is drawn) too
    const r = bubble.el.getBoundingClientRect();
    for (let y = Math.max(0, Math.floor(r.top * res)); y < Math.min(rows, Math.ceil(r.bottom * res) + 2); y++)
      for (let x = Math.max(0, Math.floor(r.left * res)); x < Math.min(cols, Math.ceil(r.right * res)); x++) solid[y * cols + x] = 1;
  }
  const grown = new Uint8Array(cols * rows);
  for (let y = 0; y < rows; y++)
    for (let x = 0; x < cols; x++) {
      if (!solid[y * cols + x]) continue;
      for (let dy = -SHAPE_GROW; dy <= SHAPE_GROW; dy++)
        for (let dx = -SHAPE_GROW; dx <= SHAPE_GROW; dx++) {
          const yy = y + dy, xx = x + dx;
          if (yy >= 0 && yy < rows && xx >= 0 && xx < cols) grown[yy * cols + xx] = 1;
        }
    }
  const runs: number[][] = [];
  for (let y = 0; y < rows; y++) {
    let start = -1;
    for (let x = 0; x <= cols; x++) {
      const on = x < cols && grown[y * cols + x] === 1;
      if (on && start < 0) start = x;
      if (!on && start >= 0) { runs.push([y, start, x]); start = -1; }
    }
  }
  shapeCells = grown;
  shapeDims = [cols, rows];
  const key = runs.join(";");
  if (key === lastShape || !a?.shape) return;
  lastShape = key;
  a.shape(cols, rows, runs);
}
let shapeCells = new Uint8Array(0);
let shapeDims = [0, 0];

/** Marks the cells whose centres fall inside a triangle (cell coordinates). */
function fillTriangle(p: Float32Array, a: number, b: number, c: number, out: Uint8Array, cols: number, rows: number) {
  const ax = p[a], ay = p[a + 1], bx = p[b], by = p[b + 1], cx = p[c], cy = p[c + 1];
  const minX = Math.max(0, Math.floor(Math.min(ax, bx, cx))), maxX = Math.min(cols - 1, Math.ceil(Math.max(ax, bx, cx)));
  const minY = Math.max(0, Math.floor(Math.min(ay, by, cy))), maxY = Math.min(rows - 1, Math.ceil(Math.max(ay, by, cy)));
  if (minX > maxX || minY > maxY) return;
  const area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
  if (Math.abs(area) < 1e-6) { out[Math.round(ay) * cols + Math.round(ax)] = 1; return; }
  for (let y = minY; y <= maxY; y++)
    for (let x = minX; x <= maxX; x++) {
      const qx = x + 0.5, qy = y + 0.5;
      const w0 = (bx - ax) * (qy - ay) - (by - ay) * (qx - ax);
      const w1 = (cx - bx) * (qy - by) - (cy - by) * (qx - bx);
      const w2 = (ax - cx) * (qy - cy) - (ay - cy) * (qx - cx);
      if ((w0 >= 0 && w1 >= 0 && w2 >= 0) || (w0 <= 0 && w1 <= 0 && w2 <= 0)) out[y * cols + x] = 1;
    }
}

// ----- hooks: the window hides her for games; checks drive her directly -----
let captureLabel = "";
(window as unknown as { sanaeAvatar: unknown }).sanaeAvatar = {
  setHidden: (h: boolean) => { hidden = h; },
  peek: (side: string) => brain.setPeek(side),
  emotion: (e: Emotion, ms = 60000) => brain.setEmotion(e, ms),
  emotions: Object.keys(EMOTIONS),
  gesture: (g: string) => brain.gesture(g),
  mode: (m: Mode | null) => { override = m ? { mode: m } : {}; },
  look: (x: number | null, y = 0) => { lookOverride = x === null ? null : [x, y]; },
  speak: (env: number[], vis: number[][] = [], text = "") => {
    link.speech = { env, vis, rate: 60, duration: env.length / 60, startAt: performance.now(), text, id: Date.now() };
    setTimeout(() => { link.speech = null; }, (env.length / 60) * 1000 + 100);
  },
  micLive: (on: boolean) => { micLive = on; micLiveUntil = Date.now() + 60000; },
  capture: (label: string) => { captureLabel = label; },
  png: () => { app.render(); return (app.view as HTMLCanvasElement).toDataURL("image/png"); },
  shape: () => ({ dims: shapeDims, cells: Array.from(shapeCells) }),
  layout: (frameShare: number) => { (window as unknown as { _f: number })._f = frameShare; },
  state: () => ({ mode: modeOf(link), emotion: brain.emotion, gesture: brain.gesturePlaying, fps, loaded: !!model,
                  bubble: bubble ? { on: bubble.visible, text: bubble.el.textContent } : null, speech: !!link.speech }),
  raw: (v: Record<string, number> | null) => { if (!v) raw.clear(); else for (const [k, x] of Object.entries(v)) raw.set(k, x); },
  info: () => {
    const c = (model?.internalModel as unknown as { coreModel?: { _model?: { parameters: { ids: string[]; minimumValues: number[];
      maximumValues: number[]; defaultValues: number[] } } } })?.coreModel?._model?.parameters;
    return c ? c.ids.map((id, i) => [id, c.minimumValues[i], c.maximumValues[i], c.defaultValues[i]]) : [];
  },
};

// ----- stats (on screen with ?debug=1; handed to the window for the benchmark) -----
const stats = document.getElementById("stats")!;
function gpuName(): string {
  const gl = (app.renderer as PIXI.Renderer).gl;
  const ext = gl.getExtension("WEBGL_debug_renderer_info");
  return ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : "unknown";
}
const gpu = gpuName();
let reported = 0;
setInterval(() => {
  const s = {
    fps: hidden ? 0 : Math.round(fps * 10) / 10, hidden, cap, mode: modeOf(link), online: link.online,
    cpu_ms_per_frame: Math.round((frameMsSum / Math.max(1, statFrames)) * 100) / 100,
    gpu, loaded: !!model, emotion: brain.emotion, renderer: "live2d",
    size: [window.innerWidth, window.innerHeight, app.renderer.resolution],
  };
  frameMsSum = 0;
  statFrames = 0;
  stats.textContent = `fps ${s.fps}/${s.cap || "refresh"}  ${s.cpu_ms_per_frame} ms cpu  ${s.mode} ${s.emotion}${s.online ? "" : " (offline)"}\n${gpu}`;
  const a = api();
  if (a?.report && performance.now() - reported > 1900) { reported = performance.now(); a.report(s); }
}, 500);
