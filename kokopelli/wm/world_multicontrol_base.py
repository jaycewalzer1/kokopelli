"""Weighted multi-control transfer on the bidirectional base Cosmos3-Nano, in MLX (Variant B, docs/log/wm_multicontrol/2026-11-06-BRIEF.md).

This is NVIDIA's supported multi-control path (cosmos-framework `inference/transfer.py` + `multi_control_two_way_attention`):

  - one window of vision tokens laid out [ctrl_1 .. ctrl_N | target]. Every control is clean (no timestep embedding), the
    target is noise. All of them sit at the target's positions (`share_vision_temporal_positions`).
  - in every layer, Q/K/V are projected once. Then for each control i one attention pass with KV = [text | ctrl_i | target].
    ctrl_i keeps the output of its own pass; the target's output is sum_i w_i * out_i, taken before the output projection.
    With one control this is exactly the ordinary two-way attention.
  - 50 UniPC steps, each with three forwards: all controls + prompt, all controls + negative prompt, and the target alone +
    prompt. They're mixed as upstream does (`guided` below).

The text only attends to itself (causally) in two-way attention, so its K/V don't depend on the video: they're computed
once per prompt by world_transfer.text_cache, the understanding half is dropped, and only the generation half (~14 GB)
stays loaded. The 16B model at bf16 (32 GB) wouldn't fit in 36 GB.

Call `multicontrol_video(...)` from any Python; it runs this file in the cosmos3-mlx venv under a ram_share hold.
Deviations from NVIDIA's reference are listed in experiments/wm_multicontrol/NOTES.md ("Variant B").
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models" / "Cosmos3-Nano"
RUNNER = Path.home() / "cosmos3" / "cosmos3-mlx"
HINTS = ("edge", "blur", "depth", "seg")
MARGIN = 15000          # unified_3d_mrope_temporal_modality_margin (transformer/config.json)
BASE_FPS = 24.0         # base_fps; enable_fps_modulation is on
TCF = 4                 # VAE temporal compression
# NVIDIA's transfer defaults for edge/blur/depth (args.py _TRANSFER_DEFAULTS) and specs/multi_control.json.
STEPS, GUIDANCE, CONTROL_GUIDANCE, SHIFT = 50, 3.0, 1.5, 10.0
MIN_BLOCK = 32          # MLX switches SDPA kernels for <= 8 queries, which changes rounding; keep every block above that


def multicontrol_video(prompt, controls, output, weights=None, size="448x256", frames=17, steps=STEPS, guidance=GUIDANCE,
                       control_guidance=CONTROL_GUIDANCE, shift=SHIFT, seed=2025, query_chunk=4096, hold_gb=20,
                       model_dir=MODEL_DIR, emphasize=True, extra=None):
    """Render one window from several controls. controls: {hint: path} in the order given (it is the order of the
    sequence and of the hint names in the prompt). weights: {hint: w}, default 1 each, normalised to sum 1.
    Returns the output path; the sidecar is output + ".json"."""
    output = Path(output).resolve()
    command = [str(RUNNER / ".venv" / "bin" / "python"), "-m", "kokopelli.wm.world_multicontrol_base", prompt, "--output", str(output),
               "--size", size, "--frames", str(frames), "--steps", str(steps), "--guidance", str(guidance),
               "--control-guidance", str(control_guidance), "--shift", str(shift), "--seed", str(seed),
               "--query-chunk", str(query_chunk), "--model-dir", str(model_dir)]
    for hint, path in controls.items():
        command += ["--control", f"{hint}={Path(path).resolve()}"]
    for hint, w in (weights or {}).items():
        command += ["--weight", f"{hint}={w}"]
    if not emphasize:
        command += ["--no-emphasize"]
    if extra:
        command += ["--extra", json.dumps(extra)]
    if hold_gb:
        command = [sys.executable, str(ROOT / "kokopelli" / "ops" / "ram_share.py"), "hold", "--name", f"wmmc_{output.stem}", "--gb",
                   str(hold_gb), "--"] + command
    result = subprocess.run(command, cwd=RUNNER, capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": f"{RUNNER}{os.pathsep}{ROOT}"})
    if result.returncode:
        raise RuntimeError(f"world_multicontrol_base.py failed ({result.returncode}): {result.stderr[-1500:]}")
    return output


# ---------------------------------------------------------------- pure pieces (tested in tests/test_wm_multicontrol_b.py)

def normalise_weights(weights):
    """build_transfer_batch: non-negative, positive sum, divided by the sum."""
    weights = [float(w) for w in weights]
    if any(w < 0 for w in weights):
        raise ValueError(f"control weights must be non-negative, got {weights}")
    if not sum(weights) > 0:
        raise ValueError(f"control weights must have a positive sum, got {weights}")
    total = sum(weights)
    return [w / total for w in weights]


def guided(v_full, v_uncond, v_nc, guidance, control_guidance):
    """transfer.py build_control_cfg_postprocess, then text CFG. Text CFG multiplies every change to the conditional
    branch by `guidance`, so the control push is shrunk to 1 + (g_c - 1)/g first: the final control increment is then
    exactly (g + g_c - 1) * (full - no_control). Without that rescale (world_filter.guided) control CFG 1.5 at
    guidance 3 acts like 2.5, not 1.5. Arrays are the target's velocities only."""
    if v_nc is not None and control_guidance != 1.0:
        if guidance == 0.0:
            raise ValueError("control_guidance != 1 can't be combined with guidance 0: text CFG would drop it")
        effective = 1.0 + (control_guidance - 1.0) / guidance
        v_full = v_nc + effective * (v_full - v_nc)
    if v_uncond is None:
        return v_full
    return v_uncond + guidance * (v_full - v_uncond)


def vision_positions(text_len, latents, hp, wp, fps):
    """mRoPE ids [3, T*hp*wp] for one vision item: time text_len + 15000 + f * 24/fps, then row, column. The FPS
    modulation (tps = fps/4 against base 24/4) gives the 24/fps stride; cosmos3_mlx hardcodes fps 24 (stride 1)."""
    import mlx.core as mx
    t = float(text_len + MARGIN) + mx.arange(latents, dtype=mx.float32) * (BASE_FPS / fps)
    t = mx.broadcast_to(t[:, None, None], (latents, hp, wp)).reshape(-1)
    h = mx.broadcast_to(mx.arange(hp, dtype=mx.float32)[None, :, None], (latents, hp, wp)).reshape(-1)
    w = mx.broadcast_to(mx.arange(wp, dtype=mx.float32)[None, None, :], (latents, hp, wp)).reshape(-1)
    return mx.stack([t, h, w])


def shared_positions(target, items):
    """share_vision_temporal_positions: every control repeats the target's ids. [3, n] -> [3, items * n]."""
    import mlx.core as mx
    return mx.concatenate([target] * items, axis=1)


def query_blocks(n, chunk):
    """(start, end) query blocks of about `chunk`. A short tail is folded into the block before it, because MLX runs
    <= 8 queries through a different kernel, which would break bit-for-bit equality with unchunked attention."""
    if not chunk or n <= chunk:
        return [(0, n)]
    bounds = [(s, min(n, s + chunk)) for s in range(0, n, chunk)]
    if len(bounds) > 1 and bounds[-1][1] - bounds[-1][0] < MIN_BLOCK:
        bounds[-2:] = [(bounds[-2][0], n)]
    return bounds


def sdpa(q, k, v, chunk=0):
    """Attention in query blocks: rows of SDPA are independent, so this equals one call, without ever holding the
    whole [queries x keys] score matrix (15k x 30k x 32 heads would be ~29 GB in bf16)."""
    import mlx.core as mx
    scale = q.shape[-1] ** -0.5
    blocks = query_blocks(q.shape[2], chunk)
    if len(blocks) == 1:
        return mx.fast.scaled_dot_product_attention(q, k, v, scale=scale)
    return mx.concatenate([mx.fast.scaled_dot_product_attention(q[:, :, s:e], k, v, scale=scale) for s, e in blocks], axis=2)


def multi_control_attention(q, k, v, text_k, text_v, n_ctrl, weights, chunk=0):
    """q/k/v [1, heads, (n_ctrl + 1) * n, D] for [ctrl_1 .. ctrl_N | target]; text K/V [1, kv_heads, L, D].
    Pass i: ctrl_i and the target attend to [text | ctrl_i | target]. ctrl_i keeps pass i; the target gets
    sum w_i * out_i. With 0 or 1 controls it is plain two-way attention, which is where upstream routes N=1 too.
    ctrl_i's and the target's queries share a KV, so they go through one SDPA call (upstream makes two; rows are
    independent, so the result is the same)."""
    import mlx.core as mx
    if n_ctrl <= 1:
        return sdpa(q, mx.concatenate([text_k, k], axis=2), mx.concatenate([text_v, v], axis=2), chunk)
    n = q.shape[2] // (n_ctrl + 1)
    t0 = n_ctrl * n
    outs, target = [], None
    for i in range(n_ctrl):
        s, e = i * n, (i + 1) * n
        kk = mx.concatenate([text_k, k[:, :, s:e], k[:, :, t0:]], axis=2)
        vv = mx.concatenate([text_v, v[:, :, s:e], v[:, :, t0:]], axis=2)
        o = sdpa(mx.concatenate([q[:, :, s:e], q[:, :, t0:]], axis=2), kk, vv, chunk)
        outs.append(o[:, :, :n])
        part = weights[i] * o[:, :, n:]          # bf16 accumulation, as upstream
        target = part if target is None else target + part
    return mx.concatenate(outs + [target], axis=2)


def forward(gen, tokens, cos, sin, text_kv, n_ctrl, weights, sigma, chunk=0, heads=32, kv_heads=8):
    """Generation half over [ctrl_1 .. ctrl_N | target] patch tokens [1, (N+1)*n, 192]. gen is a world_transfer.Generator
    (its weights and time embedding). cos/sin are one item's tables [1, n, 1, D]; every item reuses them. Only the
    target gets the timestep. Returns the target's velocity [1, n, 192] in fp32 (the controls' would be masked anyway)."""
    import mlx.core as mx
    from kokopelli.wm.world_transfer import EPS, rotate
    g = gen.g
    M = tokens.shape[1]
    n = M // (n_ctrl + 1)
    h = tokens.astype(mx.bfloat16) @ g["proj_in.weight"].T + g["proj_in.bias"]
    if sigma is not None:
        stamp = mx.concatenate([mx.zeros((1, M - n, 1), mx.bfloat16), mx.ones((1, n, 1), mx.bfloat16)], axis=1)
        h = h + stamp * gen.time_embed(sigma)[:, None, :]
    cos, sin = mx.concatenate([cos] * (n_ctrl + 1), axis=1), mx.concatenate([sin] * (n_ctrl + 1), axis=1)
    hidden = h.shape[-1]
    for i, layer in enumerate(gen.layers):
        dim = layer["qn"].shape[0]
        x = mx.fast.rms_norm(h, layer["ln1"], EPS)
        q = rotate(mx.fast.rms_norm(layer["q"](x).reshape(1, M, heads, dim), layer["qn"], EPS), cos, sin)
        k = rotate(mx.fast.rms_norm(layer["k"](x).reshape(1, M, kv_heads, dim), layer["kn"], EPS), cos, sin)
        v = layer["v"](x).reshape(1, M, kv_heads, dim)
        q, k, v = (t.transpose(0, 2, 1, 3) for t in (q, k, v))
        o = multi_control_attention(q, k, v, text_kv[i][0], text_kv[i][1], n_ctrl, weights, chunk)
        h = h + layer["o"](o.transpose(0, 2, 1, 3).reshape(1, M, hidden))
        x = mx.fast.rms_norm(h, layer["ln2"], EPS)
        a = layer["gate"](x)
        h = h + layer["down"](a * mx.sigmoid(a) * layer["up"](x))
        if i % 6 == 5:
            mx.eval(h)
    h = mx.fast.rms_norm(h[:, M - n:], g["norm_moe_gen.weight"], EPS)
    return (h @ g["proj_out.weight"].T + g["proj_out.bias"]).astype(mx.float32)


def emphasize_controls(prompt, hints):
    """emphasize_control_in_prompt (on by default in the Framework's transfer defaults): one sentence naming the hints,
    appended after the metadata. The system prompt is untouched."""
    names = ", ".join(hints)
    return (prompt.rstrip() + f" Follow the {names} control video precisely: shape, contour, silhouette,"
            f" position, and motion of every visible structure must align with the {names}"
            f" signal at every frame.")


def parse_pairs(values, kind):
    out = {}
    for item in values or []:
        if "=" not in item:
            raise SystemExit(f"--{kind} takes hint=value, got {item!r}")
        hint, value = item.split("=", 1)
        if hint not in HINTS:
            raise SystemExit(f"unknown hint {hint!r}; use one of {HINTS}")
        if hint in out:
            raise SystemExit(f"--{kind} {hint} given twice")
        out[hint] = value
    return out


def read_prompt(args):
    """The positional prompt, or --prompt-file (a kokopelli/wm/controls/prompts JSON with `variants`, picked by --variant, or plain text)."""
    if args.prompt_file:
        text = Path(args.prompt_file).read_text()
        if args.variant:
            variants = {v["id"]: v for v in json.loads(text)["variants"]}
            return variants[args.variant]["prompt"]
        return text.strip()
    if not args.prompt:
        raise SystemExit("give a prompt or --prompt-file")
    return args.prompt


# ---------------------------------------------------------------- everything below runs in the cosmos3-mlx venv

def run(args):
    import resource
    import mlx.core as mx
    import numpy as np
    from cosmos3_mlx.encode_vae import encode_video
    from cosmos3_mlx.scheduler import UniPCScheduler
    from kokopelli.wm.world_transfer import (Generator, Rope, decode_chunked, format_prompt, patchify, probe_fps, read_video,
                                reflect_pad, save_mp4, shard_arrays, text_cache, tokenize, unpatchify)

    mx.set_default_device(mx.gpu)
    started, clock = time.time(), {}
    model_dir = Path(args.model_dir)
    controls = parse_pairs(args.control, "control")
    if not controls:
        raise SystemExit("give at least one --control hint=path")
    raw_weights = {h: float(w) for h, w in parse_pairs(args.weight, "weight").items()}
    if set(raw_weights) - set(controls):
        raise SystemExit(f"weights for hints without a control: {sorted(set(raw_weights) - set(controls))}")
    hints = list(controls)
    weights = normalise_weights([raw_weights.get(h, 1.0) for h in hints])
    width, height = (int(n) for n in args.size.split("x"))
    if width % 16 or height % 16:
        raise SystemExit("width and height must be multiples of 16")
    if args.frames > args.max_frames:
        raise SystemExit(f"{args.frames} frames is more than one window (--max-frames {args.max_frames}); chunking in time"
                         " with conditional frames isn't implemented in Variant B yet")

    fps = probe_fps(controls[hints[0]])
    videos = [read_video(controls[h], width, height, h, args.frames) for h in hints]
    frames = len(videos[0])
    if any(len(v) != frames for v in videos) or frames < args.frames:
        raise SystemExit(f"controls have {[len(v) for v in videos]} frames, need {args.frames} each")
    latents_t = 1 + -(-(frames - 1) // TCF)
    padded = 1 + (latents_t - 1) * TCF          # the VAE takes 1 + 4n frames; the output keeps `frames`
    videos = [reflect_pad(v, padded) for v in videos]

    prompt = read_prompt(args)
    text = format_prompt(prompt, padded, fps, width, height)
    if not args.no_emphasize:
        text = emphasize_controls(text, hints)
    negative = json.dumps(json.loads((model_dir / "assets" / "negative_prompt.json").read_text()))
    ids, neg_ids = tokenize(model_dir, text), tokenize(model_dir, negative)
    rope = Rope()

    t0 = time.time()
    encoded = []
    for video in videos:
        lat = encode_video(video.astype(np.float32) / 255.0, str(model_dir / "vae"))   # [1, T, h, w, 48]
        mx.eval(lat)
        encoded.append(lat)
        mx.clear_cache()
    h_lat, w_lat = encoded[0].shape[2:4]
    hp, wp = (h_lat + 1) // 2, (w_lat + 1) // 2
    ctrl_tokens = mx.concatenate([patchify(lat.astype(mx.bfloat16)) for lat in encoded], axis=1)
    mx.eval(ctrl_tokens)
    del encoded
    clock["encode_s"] = time.time() - t0

    t0 = time.time()
    use_uncond, use_nc = args.guidance != 1.0, args.control_guidance != 1.0
    arrays = shard_arrays(model_dir)
    text_kv = text_cache(arrays, ids, rope)
    neg_kv = text_cache(arrays, neg_ids, rope) if use_uncond else None
    del arrays
    mx.clear_cache()
    clock["text_s"] = time.time() - t0
    t0 = time.time()
    gen = Generator(shard_arrays(model_dir))
    mx.clear_cache()
    clock["load_s"] = time.time() - t0
    print(json.dumps({"stage": "loaded", "text_tokens": len(ids), "negative_tokens": len(neg_ids), "latents": latents_t,
                      "grid": [hp, wp], "vision_tokens": (len(hints) + 1) * latents_t * hp * wp,
                      "peak_gb": round(mx.get_peak_memory() / 2 ** 30, 2), **{k: round(v, 1) for k, v in clock.items()}}),
          flush=True)

    tables = lambda length: rope.tables(vision_positions(length, latents_t, hp, wp, fps))
    cos, sin = tables(len(ids))
    neg_cos, neg_sin = tables(len(neg_ids))
    scheduler = UniPCScheduler(use_karras_sigmas=False, flow_shift=args.shift) if args.shift else UniPCScheduler()
    scheduler.set_timesteps(args.steps)
    sigmas = [float(s) for s in np.array(scheduler.sigmas)]
    mx.random.seed(args.seed)
    latents = mx.random.normal((1, latents_t, h_lat, w_lat, 48)).astype(mx.float32)
    n_ctrl, chunk = len(hints), args.query_chunk

    t_loop = time.time()
    for step in range(args.steps):
        ts = time.time()
        sigma = sigmas[step]
        target = patchify(latents.astype(mx.bfloat16))
        both = mx.concatenate([ctrl_tokens, target], axis=1)
        v_full = forward(gen, both, cos, sin, text_kv, n_ctrl, weights, sigma, chunk)
        v_uncond = forward(gen, both, neg_cos, neg_sin, neg_kv, n_ctrl, weights, sigma, chunk) if use_uncond else None
        v_nc = forward(gen, target, cos, sin, text_kv, 0, [], sigma, chunk) if use_nc else None
        v = guided(v_full, v_uncond, v_nc, args.guidance, args.control_guidance)
        velocity = unpatchify(v, h_lat, w_lat)
        latents = scheduler.step(velocity, mx.array([sigma * scheduler.num_train_timesteps]), latents)
        mx.eval(latents)
        print(json.dumps({"step": step, "of": args.steps, "sigma": round(sigma, 4), "seconds": round(time.time() - ts, 2),
                          "peak_gb": round(mx.get_peak_memory() / 2 ** 30, 2)}), flush=True)
    clock["denoise_s"] = time.time() - t_loop

    del gen, text_kv, neg_kv, ctrl_tokens
    mx.clear_cache()
    t0 = time.time()
    video = decode_chunked(latents.astype(mx.bfloat16), str(model_dir / "vae"), args.decode_chunk)[:frames]
    clock["decode_s"] = time.time() - t0
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_mp4((video * 255).round().clip(0, 255).astype(np.uint8), output, fps)
    seconds = time.time() - started
    sidecar = {
        "variant": "B", "model": model_dir.name, "model_dir": str(model_dir),
        "runtime": "MLX (world_multicontrol_base.py), bf16, generation half only, query-chunked SDPA",
        "prompt": prompt, "formatted_prompt": text, "negative_prompt": negative,
        "controls": {h: str(controls[h]) for h in hints}, "weights_raw": {h: raw_weights.get(h, 1.0) for h in hints},
        "weights": dict(zip(hints, weights)), "size": f"{width}x{height}", "frames": int(len(video)),
        "latent_frames": latents_t, "fps": fps, "seed": args.seed, "steps": args.steps, "sampler": "UniPC bh2 order 2",
        "shift": args.shift, "sigmas": [round(s, 6) for s in sigmas], "guidance": args.guidance,
        "control_guidance": args.control_guidance,
        "effective_control_guidance": 1.0 + (args.control_guidance - 1.0) / args.guidance if args.guidance else None,
        "query_chunk": chunk, "text_tokens": len(ids), "negative_tokens": len(neg_ids),
        "seconds": round(seconds, 1), "timing": {k: round(v, 1) for k, v in clock.items()},
        "peak_gb": round(mx.get_peak_memory() / 2 ** 30, 2),
        "ru_maxrss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 30, 2),   # bytes on macOS
        **(json.loads(args.extra) if args.extra else {}),
    }
    Path(str(output) + ".json").write_text(json.dumps(sidecar, indent=1))
    print(json.dumps({"done": str(output), "seconds": sidecar["seconds"], "peak_gb": sidecar["peak_gb"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prompt", nargs="?", help="caption text, or a JSON-object caption like NVIDIA's upsampled prompts")
    parser.add_argument("--prompt-file", help="read the prompt from a file instead (with --variant: a prompts JSON)")
    parser.add_argument("--variant", help="id in the prompt file's `variants` list, e.g. b_light")
    parser.add_argument("--control", action="append", help="hint=path, repeatable; order = sequence order")
    parser.add_argument("--weight", action="append", help="hint=w (default 1 each); normalised to sum 1")
    parser.add_argument("--output", required=True)
    parser.add_argument("--size", default="448x256")
    parser.add_argument("--frames", type=int, default=17)
    parser.add_argument("--max-frames", type=int, default=93, help="one window at most (NVIDIA's chunk is 93)")
    parser.add_argument("--steps", type=int, default=STEPS)
    parser.add_argument("--guidance", type=float, default=GUIDANCE)
    parser.add_argument("--control-guidance", type=float, default=CONTROL_GUIDANCE)
    parser.add_argument("--shift", type=float, default=SHIFT, help="UniPC flow shift; 0 = cosmos3_mlx's Karras default")
    parser.add_argument("--seed", type=int, default=2025)
    parser.add_argument("--query-chunk", type=int, default=4096, help="queries per SDPA block, 0 = one call")
    parser.add_argument("--decode-chunk", type=int, default=6)
    parser.add_argument("--model-dir", default=str(MODEL_DIR))
    parser.add_argument("--no-emphasize", action="store_true", help="skip the Framework's control-emphasis sentence")
    parser.add_argument("--extra", help="JSON merged into the sidecar")
    args = parser.parse_args()
    if args.query_chunk and args.query_chunk < MIN_BLOCK:
        raise SystemExit(f"--query-chunk must be 0 or at least {MIN_BLOCK}")
    run(args)


if __name__ == "__main__":
    main()
