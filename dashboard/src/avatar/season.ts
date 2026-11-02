/**
 * Seasonal looks: small things she wears depending on the date and the time of night.
 *
 *   Oct 20-31  ghost hair clip, orange headphone rings  Dec 15-26  Santa hat, red rings
 *   Dec 30-Jan 1  party hat, gold rings                 Feb 13-14  heart hair clip, pink rings
 *   otherwise by season: spring flower clip, summer sunflower, autumn leaf, winter snowflake
 *   11 PM-5 AM  hair up in a bun (getting comfy)          midnight-5 AM  sleepy, heavy-lidded eyes
 *
 * The extras are small three.js meshes on the head bone (no new model needed) and the
 * headphone rings are recoloured (the "Sanae_Headphones_accent" material from lookalike.py).
 * URL: ?season=0 turns it off; ?date=2026-10-31T23:30 pretends it's that time (for checks).
 */
import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";

export type Hat = "santa" | "party";
export type Clip = "flower" | "sunflower" | "leaf" | "snowflake" | "heart" | "ghost";
export type Look = { name: string; hat?: Hat; clip?: Clip; rim?: number; bun: boolean; drowsy: number };

export function lookFor(d: Date): Look {
  const m = d.getMonth() + 1, day = d.getDate(), h = d.getHours();
  const md = m * 100 + day;
  const night = { bun: h >= 23 || h < 5, drowsy: h < 5 ? 1 : h === 23 ? 0.35 : 0 };
  if (md >= 1020 && md <= 1031) return { name: "halloween", clip: "ghost", rim: 0xff7a1a, ...night };
  if (md >= 1215 && md <= 1226) return { name: "christmas", hat: "santa", rim: 0xff4040, ...night };
  if (md >= 1230 || md <= 101) return { name: "new year", hat: "party", rim: 0xffcf3a, ...night };
  if (md >= 213 && md <= 214) return { name: "valentine", clip: "heart", rim: 0xff6fae, ...night };
  if (m >= 3 && m <= 5) return { name: "spring", clip: "flower", ...night };
  if (m >= 6 && m <= 8) return { name: "summer", clip: "sunflower", ...night };
  if (m >= 9 && m <= 11) return { name: "autumn", clip: "leaf", ...night };
  return { name: "winter", clip: "snowflake", ...night };
}

const toon = (color: number, emissive = 0) =>
  new THREE.MeshToonMaterial({ color, emissive, emissiveIntensity: emissive ? 0.6 : 0 });

function mesh(geo: THREE.BufferGeometry, mat: THREE.Material, pos: [number, number, number], rot: [number, number, number] = [0, 0, 0]) {
  const o = new THREE.Mesh(geo, mat);
  o.position.set(...pos);
  o.rotation.set(...rot);
  o.frustumCulled = false;
  return o;
}

// Head-bone space (VRoid, VRM0): +Y up, +Z towards her back, +X her left. The head bone sits at
// the base of the skull; the top of the hair is ~0.2 m above it and the crown's middle ~1 cm behind it
// (hats were set 3.5 cm back and tilted, so they slid off the back of her head)
const TOP = 0.205, BACK = 0.035, CROWN = 0.01;
const HAIR_MID = new THREE.Vector3(0, 0.1, 0.012);     // the middle of her hair's dome

function hat(kind: Hat): THREE.Group {
  const g = new THREE.Group();
  if (kind === "santa") {
    const red = toon(0xc0202c), white = toon(0xf4f1ea);
    g.add(mesh(new THREE.ConeGeometry(0.088, 0.14, 32), red, [0, 0.06, 0.025], [0.7, 0, 0]));
    g.add(mesh(new THREE.TorusGeometry(0.098, 0.024, 12, 40), white, [0, 0, 0], [Math.PI / 2, 0, 0]));
    g.add(mesh(new THREE.SphereGeometry(0.026, 16, 12), white, [0.03, 0.095, 0.085]));
    g.position.set(0, TOP - 0.03, CROWN + 0.005);
    g.rotation.set(-0.12, 0, 0.08);
  } else {
    const gold = toon(0xffcf3a, 0x4a3500), cyan = toon(0x22d3ee, 0x0a3a44);
    g.add(mesh(new THREE.ConeGeometry(0.05, 0.13, 28), gold, [0, 0.065, 0]));
    g.add(mesh(new THREE.TorusGeometry(0.036, 0.007, 8, 28), cyan, [0, 0.04, 0], [Math.PI / 2, 0, 0]));
    g.add(mesh(new THREE.SphereGeometry(0.018, 12, 10), cyan, [0, 0.135, 0]));
    g.position.set(0.045, TOP - 0.025, CROWN);
    g.rotation.set(-0.15, 0, -0.4);
  }
  return g;
}

function clip(kind: Clip): THREE.Group {
  const g = new THREE.Group();
  const s = (r: number, mat: THREE.Material, p: [number, number, number], scale: [number, number, number] = [1, 1, 1]) => {
    const o = mesh(new THREE.SphereGeometry(r, 14, 10), mat, p);
    o.scale.set(...scale);
    g.add(o);
  };
  if (kind === "flower" || kind === "sunflower") {
    const petal = toon(kind === "flower" ? 0xffa6c9 : 0xffcc22), mid = toon(kind === "flower" ? 0xffe27a : 0x6b3b12);
    const n = kind === "flower" ? 5 : 9, r = kind === "flower" ? 0.016 : 0.021;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      s(r * 0.75, petal, [Math.cos(a) * r, Math.sin(a) * r, 0], [1, 1, 0.45]);
    }
    s(r * 0.6, mid, [0, 0, -0.004], [1, 1, 0.6]);
  } else if (kind === "leaf") {
    s(0.026, toon(0xd9631e), [0, 0, 0], [0.6, 1, 0.25]);
    s(0.02, toon(0xe8902a), [0.012, -0.012, -0.002], [0.55, 0.9, 0.25]);
  } else if (kind === "heart") {
    const pink = toon(0xff5f9e, 0x40102a);
    s(0.014, pink, [-0.009, 0.004, 0], [1, 1, 0.5]);
    s(0.014, pink, [0.009, 0.004, 0], [1, 1, 0.5]);
    g.add(mesh(new THREE.ConeGeometry(0.019, 0.026, 16), pink, [0, -0.012, 0], [0, 0, Math.PI]));
  } else if (kind === "ghost") {
    // a flat ghost cut-out (like an enamel hair clip): round head, wavy hem, dot eyes and a little "o"
    const white = toon(0xf7f4ff, 0x2a2638), dark = toon(0x2a2230), blush = toon(0xff9fb8, 0x401020);
    const w = 0.011, hem = -0.013, tips = [w, w / 3, -w / 3, -w];
    const shape = new THREE.Shape();
    shape.moveTo(-w, hem);
    shape.lineTo(-w, 0.004);
    shape.absarc(0, 0.004, w, Math.PI, 0, true);          // over the top
    shape.lineTo(w, hem);
    for (let i = 0; i < 3; i++)                             // three hem waves, arching up between the tips
      shape.quadraticCurveTo((tips[i] + tips[i + 1]) / 2, hem + 0.008, tips[i + 1], hem);
    const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.002, bevelEnabled: true, bevelThickness: 0.0008,
      bevelSize: 0.0006, bevelSegments: 2, curveSegments: 12 });
    geo.translate(0, 0, -0.001);
    g.add(mesh(geo, white, [0, 0, 0]));
    for (const side of [-1, 1]) {
      s(0.0016, dark, [side * 0.0042, 0.0035, -0.0022], [1, 1.35, 0.5]);
      s(0.0014, blush, [side * 0.0075, 0.0005, -0.0021], [1.3, 0.8, 0.4]);
    }
    s(0.0012, dark, [0, -0.0008, -0.0022], [1, 1.2, 0.5]);
  } else {
    const white = toon(0xeaf6ff, 0x203040);
    for (let i = 0; i < 3; i++) g.add(mesh(new THREE.BoxGeometry(0.044, 0.006, 0.004), white, [0, 0, 0], [0, 0, (i * Math.PI) / 3]));
  }
  // above her right temple, in front of the headphone band
  g.position.set(-0.075, TOP - 0.06, BACK - 0.085);
  g.rotation.set(-0.3, -0.5, 0.2);
  if (kind === "ghost") {
    // a flat cut-out lies on the hair like a real clip: on the side of her head above the right temple,
    // facing straight out of the hair there, upright. (Facing the camera, it stuck out of her head.)
    // HAIR_MID / the 0.112 m reach were measured from the model's hair mesh in this direction
    const out = new THREE.Vector3(-0.76, 0.51, -0.41).normalize();
    const up = new THREE.Vector3(0, 1, 0).addScaledVector(out, -out.y).normalize();
    const back = out.clone().negate();                 // the clip's +Z (its face is -Z)
    g.setRotationFromMatrix(new THREE.Matrix4().makeBasis(new THREE.Vector3().crossVectors(up, back), up, back));
    g.position.copy(HAIR_MID).addScaledVector(out, 0.112);
    g.scale.setScalar(1.5);
  }
  return g;
}

function bun(hair: number): THREE.Group {
  const g = new THREE.Group();
  const mat = toon(hair);
  g.add(mesh(new THREE.SphereGeometry(0.06, 20, 16), mat, [0, 0, 0]));
  g.add(mesh(new THREE.SphereGeometry(0.035, 14, 10), mat, [0.03, 0.025, 0.02]));
  g.add(mesh(new THREE.TorusGeometry(0.045, 0.012, 10, 28), toon(0x22d3ee, 0x0a3a44), [0, -0.035, -0.012], [1.2, 0, 0]));
  g.position.set(0, TOP - 0.005, BACK + 0.07);
  return g;
}

export class Season {
  private head: THREE.Object3D | null;
  private parts: THREE.Object3D[] = [];
  private rims: { mat: THREE.Material & { color?: THREE.Color; emissive?: THREE.Color }; color: THREE.Color; emissive?: THREE.Color }[] = [];
  private key = "";
  look: Look | null = null;

  constructor(vrm: VRM, private enabled = true, private fixedDate: Date | null = null) {
    this.head = vrm.humanoid.getRawBoneNode("head");
    vrm.scene.traverse((o) => {
      const mats = (o as THREE.Mesh).material;
      for (const mat of (Array.isArray(mats) ? mats : mats ? [mats] : []) as (THREE.Material & { color?: THREE.Color; emissive?: THREE.Color })[]) {
        if (mat.name.includes("Headphones_accent") && mat.color)
          this.rims.push({ mat, color: mat.color.clone(), emissive: mat.emissive?.clone() });
      }
    });
  }

  /** For checks: dress for this date from now on (null = the real date). */
  setDate(d: Date | null) {
    this.enabled = true;
    this.fixedDate = d;
  }

  /** Re-check the date (call now and then); rebuilds only when the look changes. */
  update(now: Date = new Date()): Look | null {
    const look = this.enabled ? lookFor(this.fixedDate ?? now) : null;
    const key = JSON.stringify(look);
    if (key === this.key) return look;
    this.key = key;
    this.look = look;
    for (const p of this.parts) p.removeFromParent();
    this.parts = [];
    for (const r of this.rims) {
      r.mat.color?.copy(r.color);
      if (r.emissive) r.mat.emissive?.copy(r.emissive);
    }
    if (!look) return null;
    const add = (bone: THREE.Object3D | null, o: THREE.Object3D) => { if (bone) { bone.add(o); this.parts.push(o); } };
    if (look.hat) add(this.head, hat(look.hat));
    if (look.clip && !look.hat) add(this.head, clip(look.clip));
    if (look.bun && look.hat !== "santa") add(this.head, bun(0x1d1719));
    if (look.rim !== undefined) {
      for (const r of this.rims) {
        r.mat.color?.setHex(look.rim);
        r.mat.emissive?.setHex(look.rim).multiplyScalar(0.9);
      }
    }
    return look;
  }
}
