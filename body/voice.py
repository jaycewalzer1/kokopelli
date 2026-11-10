"""The optional inner voice: the agent's thoughts read aloud over its film, for viewers only.

    .venv/bin/python -m body.voice out/sensation/videos/<run>/starving     # writes voice.wav and voice.json

Each decision's "thought" is spoken at the film time it was made. If a line runs into the next one, the next waits.
Nothing here feeds back into the agent: it reads what the agent already wrote, after the run.

TTS is Kokoro-82M through mlx-audio (both in the main .venv's pins), loaded only when this runs. It's a small model, but
still a model on the Mac's GPU, so it runs inside the queued video job (run_egg_videos.sh), not on its own.
The dev panel's sensations page has the toggle: it shows overlay_voice.mp4 when the voice is on and there is one.
"""
import argparse
import json
import wave
from pathlib import Path

import numpy as np

MODEL = "mlx-community/Kokoro-82M-bf16"
VOICE = "af_heart"     # American English, female: Mara
SAMPLE_RATE = 24000
GAP_S = 0.3


def _clock_s(clock):
    h, m, s = (int(part) for part in clock.split(":")[:3])
    return h * 3600 + m * 60 + s


def script(run_dir):
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


def kokoro():
    """A function text -> float32 samples at SAMPLE_RATE, backed by Kokoro on MLX."""
    from mlx_audio.tts.utils import load_model
    model = load_model(MODEL)

    def speak(text):
        parts = [np.asarray(result.audio, dtype=np.float32) for result in model.generate(text=text, voice=VOICE, speed=1.0, lang_code="a")]
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)
    return speak


def render(lines, seconds, speak, rate=SAMPLE_RATE):
    """One mono track `seconds` long with each line placed at its time (or after the previous line ends)."""
    track = np.zeros(int(seconds * rate) + 1, np.float32)
    free_at, placed = 0, []
    for at, text in lines:
        audio = speak(text)
        start = max(int(at * rate), free_at)
        end = min(start + len(audio), len(track))
        if start >= len(track):
            placed.append({"at": round(at, 2), "text": text, "dropped": "past the end of the film"})
            continue
        track[start:end] += audio[: end - start]
        free_at = end + int(GAP_S * rate)
        placed.append({"at": round(at, 2), "starts": round(start / rate, 2), "seconds": round((end - start) / rate, 2), "text": text})
    return np.clip(track, -1, 1), placed


def write_wav(path, samples, rate=SAMPLE_RATE):
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes((samples * 32767).astype("<i2").tobytes())


def make(run_dir, speak=None):
    """voice.wav and voice.json next to the run's film. `speak` is swappable so tests don't need the model."""
    from body.overlay import probe
    run = Path(run_dir).resolve()
    w, h, fps, frames = probe(run / "world_model.mp4")
    seconds = frames / fps if fps else 0
    samples, placed = render(script(run), seconds, speak or kokoro())
    write_wav(run / "voice.wav", samples)
    (run / "voice.json").write_text(json.dumps({"model": MODEL if speak is None else "test", "voice": VOICE, "rate": SAMPLE_RATE,
                                               "seconds": round(seconds, 2), "lines": placed, "for": "viewers only"}, indent=1))
    return run / "voice.wav"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    print(make(ap.parse_args().run))


if __name__ == "__main__":
    main()
