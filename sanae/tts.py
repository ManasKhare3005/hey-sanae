"""Text-to-speech: Piper (offline), or a Microsoft natural voice (e.g. Ava) with Piper as fallback;
the built-in Windows voice if neither works."""
from __future__ import annotations

import io
import logging
import re
import threading
import wave

import numpy as np

from .config import resolve_path

log = logging.getLogger(__name__)


def clean_for_speech(text: str) -> str:
    """Strip markdown and symbols that sound awful when read aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[*_`#>|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"[^\w\s.,!?'’:;%$°/()-]", "", text)
    return re.sub(r"\s+", " ", text).strip()


# How she sounds per emotion tag: (speed factor on the length, pitch, expressiveness, volume).
# Pitch is a small resample with the length pre-stretched so the tempo stays put; noise_scale is
# Piper's "liveliness" (its default is 0.667). Tuned by ear: big changes sound like a different person.
STYLES = {
    "neutral": (1.00, 1.00, 0.667, 1.00),
    "happy": (0.95, 1.04, 0.75, 1.00),
    "laugh": (0.93, 1.05, 0.80, 1.00),
    "surprised": (0.94, 1.06, 0.75, 1.00),
    "shy": (1.05, 1.02, 0.60, 0.85),
    "thinking": (1.04, 0.99, 0.60, 0.95),
    "sad": (1.12, 0.96, 0.50, 0.85),
    "sleepy": (1.15, 0.96, 0.50, 0.80),
}


# Late at night she talks softer and a little slower and calmer (factors on a STYLES entry)
NIGHT = {"speed": 1.06, "lively": 0.85, "volume": 0.72}
# Little sounds a person makes, sometimes, at the start of a reply that has this emotion tag
SOUNDS = {"laugh": ["Hehe,", "Haha,", "Hehe!"], "thinking": ["Hmm...", "Hmm,", "Mm,"], "sad": ["Aw...", "Oh..."],
          "shy": ["Ehehe,", "Um,"]}
INTERJECTION = re.compile(r"^\W*(oh+|ah+|aw+|hm+|haha|hehe|ehe+|um+|uh+|well|ooh+|wow|mm+|yay|ugh|heh)\b", re.I)


def at_night(d, night: tuple[str, str] | None) -> bool:
    if not night:
        return False
    hm, (start, end) = f"{d:%H:%M}", night
    return start <= hm < end if start < end else (hm >= start or hm < end)


def night_style(style: tuple) -> tuple:
    speed, pitch, lively, volume = style
    return (speed * NIGHT["speed"], pitch, lively * NIGHT["lively"], volume * NIGHT["volume"])


def with_sound(text: str, emotion: str, rng, chance: float) -> str:
    """'Hehe, that's so you.' now and then for [laugh]; never on top of her own 'Oh!' / 'Hmm'."""
    options = SOUNDS.get(emotion)
    if not options or chance <= 0 or INTERJECTION.match(text) or rng.random() >= chance:
        return text
    return f"{rng.choice(options)} {text}"          # case left alone: names stay right, Piper doesn't care


def pitch_shift(audio: np.ndarray, factor: float) -> np.ndarray:
    """Higher (factor > 1) or lower pitch by resampling; the clip gets 1/factor as long."""
    if abs(factor - 1) < 0.005 or not len(audio):
        return audio
    from scipy.signal import resample_poly

    return resample_poly(audio, 100, int(round(100 * factor))).astype(np.float32)


class PiperTTS:
    style: tuple | None = None    # STYLES entry for the next lines (Speaker.set_emotion)

    def __init__(self, voice_path: str, speed: float = 1.0, spellings: dict | None = None, soft: dict | None = None):
        from piper import PiperVoice

        path = resolve_path(voice_path)
        if not path.exists():
            raise FileNotFoundError(f"Piper voice not found at {path}. Run setup.ps1 to download it.")
        self.voice = PiperVoice.load(str(path))
        self.length_scale = 1.0 / max(speed, 0.1)
        self.spellings, self.soft = spellings or {}, soft

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        text = respell(text, self.spellings)
        speed, pitch, lively, volume = self.style or STYLES["neutral"]
        length = self.length_scale * speed * pitch            # pitch_shift shortens it back
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            if hasattr(self.voice, "synthesize_wav"):  # piper-tts >= 1.3
                try:
                    from piper import SynthesisConfig

                    cfg = SynthesisConfig(length_scale=length, noise_scale=lively)
                    self.voice.synthesize_wav(text, wav, syn_config=cfg)
                except ImportError:
                    self.voice.synthesize_wav(text, wav)
            else:  # piper-tts 1.2
                self.voice.synthesize(text, wav, length_scale=length)
        buf.seek(0)
        with wave.open(buf, "rb") as wav:
            sr = wav.getframerate()
            data = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        audio = pitch_shift(data.astype(np.float32) / 32768.0, pitch)
        audio = soften(audio, sr, **self.soft) if self.soft is not None else audio
        return (audio * volume).astype(np.float32), sr


def respell(text: str, spellings: dict | None) -> str:
    """Swap in sound-alike spellings ({"Sanae": "Sah-nah-eh"}) so names come out right."""
    for word, sound in (spellings or {}).items():
        text = re.sub(rf"\b{re.escape(word)}\b", sound, text, flags=re.I)
    return text


def soften(audio: np.ndarray, sr: int, gain_db: float = -3.0, treble_db: float = -2.0,
           squeeze: float = 0.35) -> np.ndarray:
    """A gentler delivery: a little quieter, less sibilant (high shelf above ~6 kHz), and lightly
    compressed so soft words stay audible next to louder ones. About a millisecond per sentence."""
    x = np.asarray(audio, dtype=np.float32)
    if not len(x):
        return x
    if treble_db and sr > 13000:
        from scipy.signal import lfilter

        # RBJ high shelf, S = 1
        a_ = 10 ** (treble_db / 40)
        w0 = 2 * np.pi * 6000 / sr
        cos, alpha = np.cos(w0), np.sin(w0) / 2 * np.sqrt(2)
        sq = 2 * np.sqrt(a_) * alpha
        b = [a_ * ((a_ + 1) + (a_ - 1) * cos + sq), -2 * a_ * ((a_ - 1) + (a_ + 1) * cos),
             a_ * ((a_ + 1) + (a_ - 1) * cos - sq)]
        a = [(a_ + 1) - (a_ - 1) * cos + sq, 2 * ((a_ - 1) - (a_ + 1) * cos), (a_ + 1) - (a_ - 1) * cos - sq]
        x = lfilter(np.array(b) / a[0], np.array(a) / a[0], x).astype(np.float32)
    if squeeze > 0:
        hop = max(1, sr // 100)                                   # 10 ms loudness steps
        n = -(-len(x) // hop)
        frames = np.pad(x, (0, n * hop - len(x))).reshape(n, hop)
        rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-5
        ref = float(np.percentile(rms, 90))
        g = (rms / ref) ** -squeeze                               # quieter parts come up a bit
        g = np.convolve(np.clip(g, 0.5, 2.0), np.ones(5) / 5, mode="same")
        x = x * np.repeat(g, hop)[: len(x)].astype(np.float32)
    peak = float(np.abs(x).max()) or 1.0
    return (x * min(10 ** (gain_db / 20) * 0.9 / peak, 4.0)).astype(np.float32)


class KokoroTTS:
    """Kokoro-82M through sherpa-onnx, on the CPU. `voice` is a name ("af_heart") or a blend
    ({"af_heart": 0.7, "af_bella": 0.3}): a blend is written into the last slot of a copy of the
    voice table (data/kokoro-voices.bin)."""

    def __init__(self, model_dir: str, voice="af_heart", speed: float = 1.0, threads: int = 4,
                 spellings: dict | None = None, soft: dict | None = None):
        import sherpa_onnx

        d = resolve_path(model_dir)
        model = next((d / n for n in ("model.onnx", "model.int8.onnx") if (d / n).exists()), None)
        if model is None:
            raise FileNotFoundError(f"Kokoro model not found in {d}. Run setup.ps1 to download it.")
        names = self.speakers(model)
        voices = d / "voices.bin"
        if isinstance(voice, dict):
            voices, sid = self._blend(voices, names, voice)
        else:
            if voice not in names:
                raise ValueError(f"unknown Kokoro voice {voice!r}; try one of {', '.join(n for n in names if n[1] == 'f')}")
            sid = names.index(voice)
        lexicon = d / "lexicon-us-en.txt"
        kokoro = sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(model), voices=str(voices), tokens=str(d / "tokens.txt"), data_dir=str(d / "espeak-ng-data"),
            lexicon=str(lexicon) if lexicon.exists() else "", lang="en-us" if lexicon.exists() else "")
        cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=kokoro, num_threads=threads, provider="cpu"), max_num_sentences=1)
        self.tts = sherpa_onnx.OfflineTts(cfg)
        self.sid, self.speed = sid, speed
        self.spellings, self.soft = spellings or {}, soft
        self.name = voice if isinstance(voice, str) else "+".join(voice)

    @staticmethod
    def speakers(model) -> list[str]:
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.log_severity_level = 3
        meta = ort.InferenceSession(str(model), so, providers=["CPUExecutionProvider"]).get_modelmeta()
        return (meta.custom_metadata_map.get("speaker_names") or "").split(",")

    @staticmethod
    def _blend(voices, names: list[str], mix: dict):
        table = np.fromfile(voices, dtype=np.float32).reshape(len(names), -1)
        total = sum(mix.values()) or 1.0
        style = sum(table[names.index(n)] * (w / total) for n, w in mix.items())
        table[-1] = style
        out = resolve_path("data/kokoro-voices.bin")
        out.parent.mkdir(parents=True, exist_ok=True)
        table.tofile(out)
        return out, len(names) - 1

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        audio = self.tts.generate(respell(text, self.spellings), sid=self.sid, speed=self.speed)
        samples, sr = np.asarray(audio.samples, dtype=np.float32), audio.sample_rate
        samples = trim_silence(samples, sr)
        if self.soft is not None:
            samples = soften(samples, sr, **self.soft)
        return samples, sr


def loudness_envelope(audio: np.ndarray, sr: int, rate: int = 60) -> list[float]:
    """How loud the voice is, `rate` times a second, 0-1 (the avatar's mouth follows it)."""
    hop = max(1, sr // rate)
    n = len(audio) // hop
    if n == 0:
        return []
    frames = np.asarray(audio[: n * hop], dtype=np.float32).reshape(n, hop)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    peak = float(np.percentile(rms, 95)) or 1.0
    return [round(float(v), 2) for v in np.clip(rms / peak, 0, 1)]


VISEMES = ("aa", "ih", "ou", "ee", "oh")
# Each mouth shape's spot on two voice features (in standard deviations from this sentence's
# average): "open" = energy around F1 of open vowels (600-1100 Hz) vs closed ones (200-500 Hz);
# "front" = F2 of i/e (1700-3200 Hz) vs rounded o/u (500-1200 Hz).
_VISEME_SPOT = {"aa": (1.1, 0.0), "ee": (0.2, 1.0), "ih": (-0.7, 1.1), "oh": (0.3, -1.0), "ou": (-0.9, -1.0)}


def viseme_track(audio: np.ndarray, sr: int, rate: int = 60) -> list[list[float]]:
    """Mouth shape per frame, `rate` times a second: weights for VISEMES (aa ih ou ee oh), each 0-1.

    A cheap formant guess, not phoneme recognition: two band-energy ratios (how open, how front
    the vowel sounds), measured against the sentence's own average so they suit any voice, pick a
    blend of shapes; loudness sets how far the mouth opens, and hiss (s, f, sh: energy above 4 kHz)
    mostly closes it. A few ms per sentence.
    """
    hop = max(1, sr // rate)
    n = len(audio) // hop
    if n == 0:
        return []
    size = 1 << int(np.ceil(np.log2(max(hop * 2, 256))))
    x = np.pad(np.asarray(audio, dtype=np.float32), (0, size))
    idx = np.arange(n)[:, None] * hop + np.arange(size)[None, :]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(size), axis=1)) ** 2
    freqs = np.fft.rfftfreq(size, 1 / sr)

    def band(lo, hi):
        return 10 * np.log10(spec[:, (freqs >= lo) & (freqs < hi)].sum(axis=1) + 1e-10)

    open_f = band(600, 1100) - band(200, 500)
    front_f = band(1700, 3200) - band(500, 1200)
    e_voice = spec[:, (freqs >= 150) & (freqs < 4000)].sum(axis=1)
    e_hiss = spec[:, freqs >= 4000].sum(axis=1)
    hiss = e_hiss / (e_voice + e_hiss + 1e-10)
    env = loudness_envelope(audio, sr, rate)
    loud = np.asarray((env + [0.0] * n)[:n])
    voiced = (loud > 0.25) & (hiss < 0.5)
    if voiced.sum() < 3:
        voiced = loud > 0
    if not voiced.any():
        return [[0.0] * len(VISEMES) for _ in range(n)]

    def z(f):
        return (f - f[voiced].mean()) / (f[voiced].std() + 1e-6)

    zo, zf = z(open_f), z(front_f)
    amount = loud * np.clip(1.3 - 1.6 * hiss, 0.15, 1.0)
    spots = np.array([_VISEME_SPOT[k] for k in VISEMES])                     # (5, 2)
    d2 = (zo[:, None] - spots[None, :, 0]) ** 2 + (zf[:, None] - spots[None, :, 1]) ** 2
    w = np.exp(-d2 / 0.8)
    w = w / (w.sum(axis=1, keepdims=True) + 1e-9)
    return np.round(w * amount[:, None], 2).tolist()


def trim_silence(audio: np.ndarray, sr: int, threshold: float = 0.01, keep_s: float = 0.06) -> np.ndarray:
    """Cut the silence some voices pad around every sentence (gaps between streamed sentences)."""
    loud = np.flatnonzero(np.abs(audio) > threshold)
    if not len(loud):
        return audio[:0]
    keep = int(keep_s * sr)
    return audio[max(0, loud[0] - keep): loud[-1] + keep]


class NaturalVoice:
    """Microsoft's natural voices (e.g. "Microsoft Ava Online") through Windows speech (SAPI),
    made available by the NaturalVoiceSAPIAdapter add-on. The "Online" voices send the text of
    each reply to Microsoft to be spoken; everything else stays on the laptop. Falls back to the
    local Piper voice when offline, slow, or broken."""

    def __init__(self, name: str = "Microsoft Ava Online", speed: float = 1.0, fallback=None, timeout_s: float = 5.0):
        import concurrent.futures as cf

        self.name = name
        self.rate = max(-10, min(10, round((speed - 1.0) * 10)))
        self.fallback = fallback
        self.timeout_s = timeout_s
        self._local = threading.local()
        self._pool = cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="natural-voice")
        audio, _ = self._pool.submit(self._speak, "Hello.").result(timeout=20)   # fails now if the voice is missing
        if not len(audio):
            raise RuntimeError(f"{name} returned no audio")

    def _voice(self):
        v = getattr(self._local, "voice", None)
        if v is None:
            import comtypes
            import comtypes.client

            comtypes.CoInitialize()                       # COM objects belong to the thread that made them
            v = comtypes.client.CreateObject("SAPI.SpVoice")
            for tok in v.GetVoices():
                desc = tok.GetDescription()
                if desc == self.name or desc.startswith(self.name + " "):
                    v.Voice = tok
                    break
            else:
                raise RuntimeError(f"voice {self.name!r} not found (is NaturalVoiceSAPIAdapter installed?)")
            v.Rate = self.rate
            self._local.voice = v
        return v

    def _speak(self, text: str) -> tuple[np.ndarray, int]:
        import comtypes.client

        voice = self._voice()
        stream = comtypes.client.CreateObject("SAPI.SpMemoryStream")
        fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
        fmt.Type = 26                                     # 24 kHz, 16-bit, mono
        stream.Format = fmt
        voice.AudioOutputStream = stream
        voice.Speak(text)
        audio = np.frombuffer(bytes(stream.GetData()), dtype=np.int16).astype(np.float32) / 32768.0
        return trim_silence(audio, 24000), 24000

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        try:
            audio, sr = self._pool.submit(self._speak, text).result(timeout=self.timeout_s)
            if len(audio):
                return audio, sr
            log.warning("%s returned silence; using the local voice", self.name)
        except Exception as exc:
            log.warning("%s unavailable (%s); using the local voice", self.name, exc)
        if self.fallback is None:
            raise RuntimeError(f"{self.name} failed and there is no fallback voice")
        return self.fallback.synthesize(text)


def make_voice(cfg_tts):
    """The configured voice as an object with synthesize(text) -> (audio, sample_rate)."""
    if (cfg_tts.get("engine") or "piper") == "kokoro":
        k = cfg_tts.get("kokoro") or {}
        try:
            voice = KokoroTTS(k.get("model_dir", "models/kokoro/kokoro-multi-lang-v1_0"), k.get("voice", "af_heart"),
                              cfg_tts.get("speed", 1.0), k.get("threads", 4), cfg_tts.get("spellings"),
                              cfg_tts.get("soft"))
            log.info("voice: Kokoro %s", voice.name)
            return voice
        except Exception as exc:
            log.warning("Kokoro unavailable (%s); using Piper", exc)
    piper = None
    try:
        piper = PiperTTS(cfg_tts.get("piper_voice", ""), cfg_tts.get("speed", 1.0), cfg_tts.get("spellings"),
                         cfg_tts.get("soft"))
    except Exception as exc:
        log.warning("Piper unavailable (%s)", exc)
    if (cfg_tts.get("engine") or "piper") == "natural":
        try:
            voice = NaturalVoice(cfg_tts.get("natural_voice", "Microsoft Ava Online"), cfg_tts.get("speed", 1.0), fallback=piper)
            log.info("voice: %s (falls back to Piper)", voice.name)
            return voice
        except Exception as exc:
            log.warning("natural voice unavailable (%s); using Piper", exc)
    return piper


class SapiTTS:
    """Windows built-in voice. Zero setup, more robotic."""

    def __init__(self, speed: float = 1.0):
        import pyttsx3

        self.engine = pyttsx3.init()
        self.engine.setProperty("rate", int(185 * speed))

    def say(self, text: str):
        self.engine.say(text)
        self.engine.runAndWait()


class Speaker:
    """Speaks text, muting the microphone meanwhile so Sanae doesn't hear itself."""

    def __init__(self, engine: str = "piper", voice_path: str = "", speed: float = 1.0, device=None, mic=None,
                 natural_voice: str = "Microsoft Ava Online", cfg_tts: dict | None = None):
        self.device = device
        self.mic = mic
        self.piper = None     # any voice with synthesize(text) -> (audio, rate): Kokoro, Piper or a natural voice
        self.sapi = None
        if engine in ("piper", "natural", "kokoro"):
            self.piper = make_voice(cfg_tts or {"engine": engine, "piper_voice": voice_path, "speed": speed,
                                                "natural_voice": natural_voice})
        if self.piper is None:
            self.sapi = SapiTTS(speed)

    interrupts = None   # wakeword.InterruptSpotter: lets "stop" / "Hey Sanae" cut Sanae off
    emotion = "neutral"
    _mmhm = None
    night: tuple[str, str] | None = ("23:00", "06:00")   # softer and slower then (tts.night in config.yaml)
    sounds = 0.35       # chance of a little "hehe" / "hmm" / "aw" starting a reply (tts.sounds; 0 = never)
    _fresh = False      # the next line starts a reply (a sound may go in front)
    _rng = None
    clock = None        # () -> datetime, for tests

    def set_emotion(self, emotion: str | None):
        """The tone for the next lines (from her emotion tag); "neutral" after each reply."""
        self.emotion = emotion if emotion in STYLES else "neutral"
        self._fresh = self.emotion != "neutral"
        if self.piper is not None and hasattr(self.piper, "style"):
            self.piper.style = STYLES[self.emotion]

    def _dress(self, text: str) -> str:
        """Right before speaking: the night voice if it's late, and maybe a little sound in front."""
        import datetime as dt
        import random

        if self.piper is not None and hasattr(self.piper, "style"):
            base = STYLES.get(self.emotion, STYLES["neutral"])
            now = self.clock() if self.clock else dt.datetime.now()
            self.piper.style = night_style(base) if at_night(now, self.night) else base
        if self._fresh:
            self._fresh = False
            self._rng = self._rng or random.Random()
            text = with_sound(text, self.emotion, self._rng, self.sounds)
        return text

    def backchannel(self, volume: float = 0.45):
        """A soft "mm-hm" while the user pauses mid-thought. The mic is muted for the half second
        it plays, so neither her voice nor its echo ends up in their recording."""
        if self.piper is None:
            return
        import time

        from .audio import play

        if self._mmhm is None:
            old, self.piper.style = getattr(self.piper, "style", None), STYLES["thinking"]
            try:
                audio, sr = self.piper.synthesize("Mm-hm.")
            finally:
                self.piper.style = old
            self._mmhm = (audio * volume, sr)
        audio, sr = self._mmhm
        if self.mic:
            self.mic.muted.set()
        try:
            play(audio, sr, self.device)
            time.sleep(0.12)                          # the room's echo
        finally:
            if self.mic:
                self.mic.muted.clear()
    on_speech = None    # (action, data): "start" with loudness + mouth shapes just before playing, then "end"

    def _tell(self, action: str, data: dict):
        if self.on_speech is not None:
            try:
                self.on_speech(action, data)
            except Exception as exc:                   # the avatar must never break speech
                log.debug("on_speech failed: %s", exc)

    def _starting(self, audio, sr: int, text: str = ""):
        if self.on_speech is None:
            return
        try:
            vis = viseme_track(audio, sr)
        except Exception as exc:
            log.debug("viseme track failed: %s", exc)
            vis = []
        self._tell("start", {"env": loudness_envelope(audio, sr), "vis": vis, "rate": 60,
                             "duration": round(len(audio) / sr, 2), "text": text})

    def say(self, text: str) -> str | None:
        """Speak `text`. Returns "stop" or "wake" if the user interrupted, else None."""
        text = clean_for_speech(text)
        if not text:
            return None
        text = self._dress(text)
        log.info("saying: %s", text[:160])          # what was really spoken (a reply once sounded doubled)
        if self.piper and self.mic and self.interrupts is not None:
            return self._say_interruptible(text)
        if self.mic:
            self.mic.muted.set()
        try:
            if self.piper:
                from .audio import play

                audio, sr = self.piper.synthesize(text)
                self._starting(audio, sr, text)
                play(audio, sr, self.device)
            else:
                self._tell("start", {"env": [], "rate": 60, "duration": 0, "text": text})  # no audio: a generic mouth
                self.sapi.say(text)
        finally:
            self._tell("end", {"cut": False})
            if self.mic:
                self.mic.flush()
                self.mic.muted.clear()
        return None

    def _say_interruptible(self, text: str) -> str | None:
        """Play without blocking and keep the mic open for "stop" / "Hey Sanae" meanwhile."""
        import sounddevice as sd

        from .speech import watch_for_interrupt

        audio, sr = self.piper.synthesize(text)
        self.mic.flush()
        self.interrupts.reset()
        self._starting(audio, sr, text)
        sd.play(audio, sr, device=self.device)
        try:
            heard = watch_for_interrupt(self.mic.read, self.interrupts, len(audio) / sr + 0.15, text)
        finally:
            if heard:
                sd.stop()
            else:
                sd.wait()
            self._tell("end", {"cut": bool(heard)})
            self.mic.flush()
        return heard
