"""Run manifests: one call that says exactly what produced an output, for every sidecar.

    from kokopelli.wm.manifest import manifest
    sidecar = {..., "manifest": manifest(weights=model_dir, seed=7, prompt=p, quantize=8, controls=c, resolution="832x480")}

Fields: commit, dirty (bool + sha256 of `git diff HEAD` + untracked count), weights (path, sha256 of every
*.safetensors.index.json and config.json, size of every *.safetensors), seed, prompt, quantize, controls, resolution,
fake. Weight files are never read (they are many GB): only the small index files are hashed and the big ones stat'ed.
A fake world model is labeled "fake": True and gets no weights, so it can't pass for the real one.
"""
import functools
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _git(root, *args):
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


@functools.lru_cache(maxsize=4)
def git_state(root=ROOT):
    """commit and dirty state, once per process: a run's code doesn't change under it, and sidecars are rewritten every step."""
    head = _git(root, "rev-parse", "HEAD")
    if head is None:
        return {"commit": None, "dirty": None}
    diff = _git(root, "diff", "HEAD", "--binary") or b""
    untracked = [line for line in (_git(root, "ls-files", "--others", "--exclude-standard") or b"").splitlines() if line]
    return {"commit": head.decode().strip(),
            "dirty": {"dirty": bool(diff or untracked), "diff_sha256": hashlib.sha256(diff).hexdigest() if diff else None,
                      "untracked": len(untracked)}}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _visible(path, base):
    return not any(part.startswith(".") for part in path.relative_to(base).parts)


@functools.lru_cache(maxsize=8)
def weights_info(path):
    """Identity of a weights folder (or single file) without reading the weights: hashes of the index/config files
    and the byte size of each .safetensors file, keyed by path relative to the folder."""
    p = Path(path)
    if not p.exists():
        return {"path": str(p), "exists": False}
    if p.is_file():
        return {"path": str(p), "exists": True, "sizes": {p.name: p.stat().st_size}}
    index = sorted(f for f in p.rglob("*.safetensors.index.json") if _visible(f, p))
    config = [p / "config.json"] if (p / "config.json").is_file() else []
    sizes = sorted((f.relative_to(p).as_posix(), f.stat().st_size) for f in p.rglob("*.safetensors") if _visible(f, p))
    return {"path": str(p), "exists": True,
            "sha256": {f.relative_to(p).as_posix(): _sha256(f) for f in index + config},
            "sizes": dict(sizes), "total_bytes": sum(s for _, s in sizes)}


def manifest(*, weights=None, seed=None, prompt=None, quantize=None, controls=None, resolution=None, fake=False,
             root=ROOT, **extra):
    """The manifest dict for a sidecar. `weights` is a folder or file (or a dict name -> path for several models);
    pass fake=True for any run whose world model is faked, and weights is then left out for it."""
    if isinstance(weights, dict):
        w = {k: weights_info(str(v)) for k, v in weights.items() if v is not None}
    else:
        w = weights_info(str(weights)) if weights is not None else None
    return {**git_state(Path(root)), "weights": w, "seed": seed, "prompt": prompt, "quantize": quantize,
            "controls": controls, "resolution": resolution, "fake": bool(fake), **extra}
