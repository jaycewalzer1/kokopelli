"""The optional inner voice: the agent's thoughts read aloud over its film, for viewers only.

    .venv/bin/python -m kokopelli.body.voice out/sensation/videos/<run>/starving     # writes voice.wav and voice.json
    .venv/bin/python -m kokopelli.body.voice --needs                                 # what's missing to speak; loads nothing

Each decision's "thought" is spoken at the film time it was made. If a line runs into the next one, the next waits.
Nothing here feeds back into the agent: it reads what the agent already wrote, after the run.

TTS is Kokoro-82M through mlx-audio, loaded only when this runs. mlx-audio is in the main .venv's pins, but Kokoro's
English text-to-phoneme step is not: mlx-audio imports misaki for it, and misaki needs spaCy, its en_core_web_sm model,
num2words, phonemizer and espeakng_loader (docs/log/sensations/2026-11-11-voice.md has the licences). Until those are
installed `kokoro()` refuses before it downloads or loads anything, and the films are made without a voice.
It's a small model, but still a model on the Mac's GPU, so it runs inside the queued video job (run_egg_videos.sh).
The dev panel's sensations page has the toggle: it shows overlay_voice.mp4 when the voice is on and there is one.

voice.json is the sidecar: which model, revision, licence and voice spoke (or that a stand-in did), where each line
landed, and `check`, a listen-test proxy (`check()` below). The proxy is arithmetic on the samples. Nobody has listened.
"""
import argparse
import json
import math
import wave
from collections.abc import Callable
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path

import numpy as np

MODEL = "mlx-community/Kokoro-82M-bf16"
# The repo's commit on Hugging Face when its licence was read (2026-11-10). kokoro() loads exactly this one, so the
# sidecar names what spoke. Moving it means reading the licence again.
REVISION = "a71e4d38b236d968966a2002c4c895dbd12b1c3c"
LICENCE = {"name": "Apache-2.0", "url": f"https://huggingface.co/{MODEL}", "read": "2026-11-10",
           "upstream": "hexgrad/Kokoro-82M (Apache-2.0)", "mlx_audio": "MIT"}
VOICE = "af_heart"     # American English, female: Mara
LANG = "a"             # American English in Kokoro's codes
SAMPLE_RATE = 24000
GAP_S = 0.3
ON_TIME_S = 0.5        # a line counts as on time when its sound starts this soon after its decision
DURATION_SLACK_S = 0.1
# What mlx-audio 0.6.4 imports for LANG "a", by import name. en_core_web_sm is on the list because misaki would
# otherwise pip-install it into the running environment at the first line.
NEEDS = ("mlx_audio", "misaki", "num2words", "spacy", "en_core_web_sm", "phonemizer", "espeakng_loader")


class VoiceUnavailable(RuntimeError):
    """Kokoro can't speak in this environment. The message says what's missing."""


def _clock_s(clock):
    h, m, s = (int(part) for part in clock.split(":")[:3])
    return h * 3600 + m * 60 + s


def script(run_dir: str | Path) -> list[tuple[float, str]]:
    """[(film seconds, text)] from the run's decisions. Film time 0 is the first body line's clock."""
    run = Path(run_dir).resolve()
    result = json.loads((run / "egg.json").read_text())
    first = json.loads((run / "body.jsonl").read_text().splitlines()[0])
    start = _clock_s(first["clock"])
    lines = []
    for response in result.get("responses", []):
        text = (response.get("thought") or "").strip()
        if text and text != "(couldn't decide)":
            lines.append((max(0.0, _clock_s(response["clock"]) - start), text))
    return lines


def missing() -> list[str]:
    """The packages Kokoro needs to speak English that this environment doesn't have. Imports none of them."""
    return [name for name in NEEDS if find_spec(name) is None]


def kokoro() -> Callable[[str], np.ndarray]:
    """A function text -> float32 samples at SAMPLE_RATE, backed by Kokoro on MLX."""
    absent = missing()
    if absent:
        raise VoiceUnavailable(f"Kokoro can't speak here: {', '.join(absent)} not installed (nothing was downloaded or loaded)")
    from mlx_audio.tts.utils import load_model
    model = load_model(MODEL, revision=REVISION)  # pyright: ignore[reportArgumentType]  # mlx-audio annotates a Path but takes a Hugging Face repo id

    def speak(text):
        parts = [np.asarray(result.audio, dtype=np.float32).reshape(-1) for result in model.generate(text=text, voice=VOICE, speed=1.0, lang_code=LANG)]  # pyright: ignore[reportOptionalCall]  # generate is the Kokoro model's own method; nn.Module doesn't declare it
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)
    return speak


def about_model() -> dict:
    """What spoke, for the sidecar. Only true of a track kokoro() made."""
    return {"model": MODEL, "revision": REVISION, "licence": LICENCE, "parameters": "82M",
            "precision": "bf16 as published, not quantized", "voice": VOICE, "lang_code": LANG,
            "mlx_audio": metadata.version("mlx-audio")}


def place(lines: list[tuple[float, str]], seconds: float, speak: Callable[[str], np.ndarray],
          rate: int = SAMPLE_RATE) -> tuple[np.ndarray, list[dict]]:
    """One mono track `seconds` long with each line at its time, or after the previous line ends. Not clipped: the
    peak of what comes back is what check() measures. Every line that isn't where it was asked to be says why."""
    track = np.zeros(int(seconds * rate) + 1, np.float32)
    free_at, placed = 0, []
    for at, text in lines:
        audio = np.asarray(speak(text), np.float32).reshape(-1)
        entry: dict = {"at": round(at, 3), "text": text}
        placed.append(entry)
        wanted = int(at * rate)
        start = max(wanted, free_at)
        if len(audio) == 0:
            entry["dropped"] = "no audio came back for this line"
            continue
        if start >= len(track):
            entry["dropped"] = ("past the end of the film" if wanted >= len(track)
                                else "the line before it ran to the end of the film")
            continue
        end = min(start + len(audio), len(track))
        track[start:end] += audio[: end - start]
        entry.update(starts=round(start / rate, 3), seconds=round((end - start) / rate, 3))
        if start > wanted:
            entry["delayed"] = f"waited {(start - wanted) / rate:.2f} s for the line before it to finish"
        if end - start < len(audio):
            entry["cut"] = f"the film ended {(len(audio) - (end - start)) / rate:.2f} s before the line did"
        free_at = end + int(GAP_S * rate)
    return track, placed


def render(lines: list[tuple[float, str]], seconds: float, speak: Callable[[str], np.ndarray],
           rate: int = SAMPLE_RATE) -> tuple[np.ndarray, list[dict]]:
    """place(), clipped to what a wav can hold."""
    track, placed = place(lines, seconds, speak, rate)
    return np.clip(track, -1, 1), placed


def check(track: np.ndarray, placed: list[dict], film_seconds: float, rate: int = SAMPLE_RATE,
          wav: str | Path | None = None) -> dict:
    """The listen-test proxy. `track` is place()'s, before clipping, or the clip would hide the peak.

    duration   the voice is as long as the film (the written wav's own length when `wav` is given)
    clipping   no sample beyond full scale before the clip
    timing     each line's sound is heard within ON_TIME_S of its decision, or the line says why it was delayed or
               dropped. "Heard" is measured in the track (the first sample at a tenth of that line's own peak), so
               silence at the front of what the model returned counts as lateness.
    """
    if wav is not None:
        with wave.open(str(wav), "rb") as file:
            voice_seconds = file.getnframes() / file.getframerate()
    else:
        voice_seconds = len(track) / rate
    off = voice_seconds - film_seconds
    duration = {"film_s": round(film_seconds, 3), "voice_s": round(voice_seconds, 3), "off_by_s": round(off, 3),
                "slack_s": DURATION_SLACK_S, "ok": film_seconds > 0 and abs(off) <= DURATION_SLACK_S}

    peak = float(np.max(np.abs(track))) if len(track) else 0.0
    clipping = {"peak": round(peak, 4), "peak_db": round(20 * math.log10(peak), 2) if peak > 0 else None,
                "samples_over": int(np.sum(np.abs(track) > 1.0)), "measured": "before the clip", "ok": peak <= 1.0}

    counts = {"on_time": 0, "delayed": 0, "dropped": 0}
    unexplained, worst, cut = [], 0.0, 0
    for k, entry in enumerate(placed):
        if "dropped" in entry:
            counts["dropped"] += 1
            continue
        cut += "cut" in entry
        span = np.abs(track[int(entry["starts"] * rate): int((entry["starts"] + entry["seconds"]) * rate)])
        loudest = float(span.max()) if len(span) else 0.0
        if loudest < 1e-4:
            unexplained.append({"line": k, "at": entry["at"], "why": "placed, but its part of the track is silent"})
            continue
        heard = entry["starts"] + int(np.argmax(span >= 0.1 * loudest)) / rate
        late = heard - entry["at"]
        entry["heard"] = round(heard, 3)
        worst = max(worst, late)
        if -0.02 <= late <= ON_TIME_S:
            counts["on_time"] += 1
        elif late > ON_TIME_S and "delayed" in entry:
            counts["delayed"] += 1
        else:
            unexplained.append({"line": k, "at": entry["at"], "heard": round(heard, 3),
                                "why": "heard before its decision" if late < 0 else
                                       f"heard {late:.2f} s after its decision with nothing in its way"})
    timing = {"on_time_within_s": ON_TIME_S, "lines": len(placed), **counts, "cut_short": cut,
              "worst_late_s": round(worst, 3), "unexplained": unexplained, "ok": not unexplained}
    return {"passed": bool(duration["ok"] and clipping["ok"] and timing["ok"]), "duration": duration,
            "clipping": clipping, "timing": timing,
            "what_this_is": "a proxy computed from the samples; nobody has listened to this track"}


def write_wav(path: str | Path, samples: np.ndarray, rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes((samples * 32767).astype("<i2").tobytes())


def make(run_dir: str | Path, speak: Callable[[str], np.ndarray] | None = None) -> Path:
    """voice.wav and voice.json next to the run's film. `speak` is swappable so tests don't need the model; a track
    made that way is marked a stand-in in the sidecar and never carries the model's name."""
    from kokopelli.body.overlay import probe
    run = Path(run_dir).resolve()
    w, h, fps, frames = probe(run / "world_model.mp4")
    seconds = frames / fps if fps else 0
    lines = script(run)
    speaker = speak or kokoro()   # refuses here, before anything is written, if Kokoro can't speak
    spoke = about_model() if speak is None else {"model": None, "stand_in": "a test function spoke, not Kokoro", "voice": None}
    track, placed = place(lines, seconds, speaker)
    write_wav(run / "voice.wav", np.clip(track, -1, 1))
    sidecar = {"made_by": "kokopelli/body/voice.py", **spoke, "rate": SAMPLE_RATE, "seconds": round(seconds, 2),
               "lines": placed, "check": check(track, placed, seconds, wav=run / "voice.wav"), "for": "viewers only"}
    dry = json.loads((run / "egg.json").read_text()).get("dry_run")
    if dry:
        sidecar["dry_run"] = dry   # the run itself was made with fakes; say so wherever its voice goes
    (run / "voice.json").write_text(json.dumps(sidecar, indent=1))
    return run / "voice.wav"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", nargs="?")
    ap.add_argument("--needs", action="store_true", help="print what this environment lacks to speak, and exit (0 if nothing)")
    args = ap.parse_args()
    if args.needs:
        absent = missing()
        print(f"missing: {', '.join(absent)}" if absent else f"nothing missing for {MODEL} at {REVISION[:12]}")
        raise SystemExit(1 if absent else 0)
    if not args.run:
        ap.error("give a run folder, or --needs")
    try:
        made = make(args.run)
    except VoiceUnavailable as why:
        raise SystemExit(str(why)) from None
    result = json.loads(made.with_name("voice.json").read_text())["check"]
    print(made)
    print(f"listen-test proxy {'passed' if result['passed'] else 'FAILED'}: peak {result['clipping']['peak']}, "
          f"off by {result['duration']['off_by_s']} s, {result['timing']['on_time']} on time, "
          f"{result['timing']['delayed']} delayed, {result['timing']['dropped']} dropped of {result['timing']['lines']}")


if __name__ == "__main__":
    main()
