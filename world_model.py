"""Utility functions for calling the world model. Cosmos runs from its own environment."""
import subprocess
from pathlib import Path

from settings import WORLD_MODEL_RUNNER, WORLD_MODEL_WEIGHTS


def _generate(script, prompt, output, size, frames, steps, seed, extra=()):
    # The generator runs from its own directory, so a relative path would land elsewhere.
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(WORLD_MODEL_RUNNER / ".venv" / "bin" / "python"), script, prompt,
        "--model-dir", str(WORLD_MODEL_WEIGHTS), "-q", "--no-cache",
        "--size", size, "--frames", str(frames), "--steps", str(steps),
        "--output", str(output), *extra,
    ]
    if seed is not None:
        command += ["--seed", str(seed)]
    result = subprocess.run(command, cwd=WORLD_MODEL_RUNNER, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{script} failed: {result.stderr[-800:]}")
    return output


def text_to_video(prompt, output, size="448x256", frames=16, steps=30, seed=None):
    """Generate a clip from a prompt. Frames must be a multiple of 4, size multiples of 16."""
    return _generate("txt2video.py", prompt, output, size, frames, steps, seed)


def image_to_video(prompt, image, output, size="448x256", frames=16, steps=30, seed=None):
    """Generate a clip that starts from an image."""
    extra = ("--image", str(Path(image).resolve()))
    return _generate("img2video.py", prompt, output, size, frames, steps, seed, extra)


def continue_video(prompt, video, output, size="448x256", frames=16, steps=30, seed=None, cond_frames=5):
    """Generate a clip whose first cond_frames (1 + 4n) repeat the end of a video, carrying on its motion."""
    extra = ("--video", str(Path(video).resolve()), "--cond-frames", str(cond_frames))
    return _generate("img2video.py", prompt, output, size, frames, steps, seed, extra)
