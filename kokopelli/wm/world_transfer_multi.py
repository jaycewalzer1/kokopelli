"""Weighted multi-control on Cosmos3-Nano-Sim-Transfer (MLX), Variant A of experiments/wm_multicontrol/BRIEF.md.

Sim-Transfer was trained with exactly one control, so this is an untrained combination. It borrows NVIDIA's base-model
trick (cosmos-framework `multi_control_two_way_attention`): each control i is its own branch, the target's attention runs
once per branch and the outputs are mixed as sum w_i * o_i before the output projection. Everything else (the causal
loop, positions, the 4 SDE steps, seeding) is world_transfer.py's, imported, never edited. Per latent frame f:

  1. for each hint i, the clean control C_f^i takes world_transfer's own control pass. It sees the text, branch i's
     history (C_0^i, R_0, C_1^i, R_1, ...) and itself, never R_f. Its K/V go to branch i's history only,
  2. the target R_f takes the 4 steps. Per layer, Q/K/V are projected once. Branch i attends to text + branch i's history
     (ending with C_f^i) + R_f itself, and the N outputs are weighted and summed. Then come one `o` and one MLP,
  3. the clean R_f goes through the same weighted path, and its K/V are cached once and shared by every branch.

With one control at weight 1 this computes exactly what world_transfer.run computes: the same ops in the same order, and
multiplying by 1.0 is exact in bf16. tests/test_wm_multicontrol_a.py checks this bit for bit on a tiny fake model.
Deviations are listed in experiments/wm_multicontrol/NOTES.md ("Variant A").

Call `transfer_video_multi(...)` from any Python. It runs this file in the cosmos3-mlx venv under a ram_share hold and
writes `<output>` plus `<output>.json`. It doesn't queue itself; wrap it in gpu.py.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from kokopelli.wm import world_transfer as wt   # stdlib-only at import time; its mlx code lives inside functions

ROOT = Path(__file__).resolve().parents[2]
# KOKO_DRY_RUN=1 (what `gpu.py run --dry-run` sets) or --dry-run: paint one latent (frame 0) to <output stem>.dryrun.mp4,
# label the sidecar, exit 0. It proves the weights load and the whole path runs before a long paint takes its turn.
DRY_RUN = os.environ.get("KOKO_DRY_RUN") == "1"


def normalize_weights(controls, weights=None):
    """Upstream transfer.py:251-259: one scalar per control, non-negative, positive sum, normalised to sum 1.
    weights None means 1.0 each. Returns {hint: w} in the order of `controls`. Missing or extra hints are errors,
    because silently giving an unnamed control weight 1 would change the mix."""
    hints = list(controls)
    if not hints:
        raise ValueError("need at least one control")
    if weights is None:
        weights = {h: 1.0 for h in hints}
    missing, extra = set(hints) - set(weights), set(weights) - set(hints)
    if missing or extra:
        raise ValueError(f"weights must name exactly the controls: missing {sorted(missing)}, extra {sorted(extra)}")
    raw = [float(weights[h]) for h in hints]
    if any(not w >= 0 for w in raw):   # `not >=` also rejects NaN
        raise ValueError(f"weights must be non-negative, got {dict(zip(hints, raw))}")
    total = sum(raw)
    if not total > 0 or total == float("inf"):
        raise ValueError(f"weights must have a positive, finite sum, got {dict(zip(hints, raw))}")
    return {h: w / total for h, w in zip(hints, raw)}


def transfer_video_multi(prompt, controls, output, weights=None, size="832x480", frames=None, seed=2025, window=51,
                         sink=1, hold_gb=20, hold_name="wmmc_transfer_a", quantize=None, model_dir=wt.MODEL_DIR,
                         decode_chunk=6, raw_prompt=False, extra=None, save_latents=None):
    """Repaint from several controls at once. controls: {hint: path} (hints from world_transfer.HINTS, each at most
    once); weights: {hint: float}, normalised to sum 1 (None = equal). Other arguments as world_transfer.transfer_video.
    Returns the output path; the sidecar is output + ".json"."""
    normalize_weights(controls, weights)          # fail here, not after the hold and the venv start
    weights = weights or {h: 1.0 for h in controls}
    output = Path(output).resolve()
    command = [str(wt.RUNNER / ".venv" / "bin" / "python"), "-m", "kokopelli.wm.world_transfer_multi", prompt,
               "--output", str(output), "--size", size, "--seed", str(seed), "--window", str(window), "--sink", str(sink),
               "--model-dir", str(model_dir), "--decode-chunk", str(decode_chunk)]
    for hint, path in controls.items():
        command += ["--control", f"{hint}={Path(path).resolve()}", "--weight", f"{hint}={float(weights[hint])!r}"]
    if frames:
        command += ["--frames", str(frames)]
    if quantize:
        command += ["--quantize", str(quantize)]
    if raw_prompt:
        command += ["--raw-prompt"]
    if save_latents:
        command += ["--save-latents", str(Path(save_latents).resolve())]
    if extra:
        command += ["--extra", json.dumps(extra)]
    if hold_gb:
        command = [sys.executable, str(ROOT / "kokopelli" / "ops" / "ram_share.py"), "hold", "--name", hold_name, "--gb", str(hold_gb),
                   "--"] + command
    result = subprocess.run(command, cwd=wt.RUNNER, capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": f"{wt.RUNNER}{os.pathsep}{ROOT}"})
    if result.returncode:
        raise RuntimeError(f"world_transfer_multi.py failed ({result.returncode}): {result.stderr[-1500:]}")
    return output


# ---------------------------------------------------------------- everything below runs in the cosmos3-mlx venv

class MultiHistory:
    """One world_transfer.History per branch. Branch i holds C_0^i, R_0, C_1^i, R_1, ...; the R entries are the same
    objects in every branch (one shared R stream, cached once), so each branch's view and window/sink eviction are
    exactly History's for a single-hint run, by construction."""

    def __init__(self, n, window, sink):
        self.branches = [wt.History(window, sink) for _ in range(n)]

    def add_control(self, i, kv):
        self.branches[i].add(kv)

    def add_target(self, kv):
        for branch in self.branches:
            branch.add(kv)

    def view(self, i, for_target):
        return self.branches[i].view(for_target)


class MultiGenerator(wt.Generator):
    """world_transfer.Generator plus a target forward that attends once per branch and mixes the outputs."""

    def control(self, tokens, cos, sin, context):
        """A control's clean pass is the unmodified single-control forward: text + its own history + itself."""
        return self(tokens, cos, sin, context, store=True)[1]

    def target(self, tokens, cos, sin, contexts, weights, sigma=None, store=False):
        """Generator.__call__ line for line, except the attention: one SDPA per branch over [context_i..., own] (the
        same concat order as the single path), then sum w_i * o_i in bf16 before `o`, as upstream sums before the
        output projection. Keep this in step with world_transfer.Generator.__call__; the N=1 test catches drift."""
        import mlx.core as mx
        g = self.g
        N = tokens.shape[1]
        h = tokens.astype(mx.bfloat16) @ g["proj_in.weight"].T + g["proj_in.bias"]
        if sigma is not None:
            h = h + self.time_embed(sigma)[:, None, :]
        kept = []
        for i, layer in enumerate(self.layers):
            x = mx.fast.rms_norm(h, layer["ln1"], wt.EPS)
            q = wt.rotate(mx.fast.rms_norm(layer["q"](x).reshape(1, N, 32, 128), layer["qn"], wt.EPS), cos, sin)
            k = wt.rotate(mx.fast.rms_norm(layer["k"](x).reshape(1, N, 8, 128), layer["kn"], wt.EPS), cos, sin)
            v = layer["v"](x).reshape(1, N, 8, 128)
            q, k, v = (t.transpose(0, 2, 1, 3) for t in (q, k, v))
            if store:
                kept.append((k, v))
                if i == 35:
                    break
            o = None
            for w, context in zip(weights, contexts):
                ks = [c[0] for c in context[i]] + [k]
                vs = [c[1] for c in context[i]] + [v]
                part = w * mx.fast.scaled_dot_product_attention(q, mx.concatenate(ks, axis=2),
                                                                mx.concatenate(vs, axis=2), scale=128 ** -0.5)
                o = part if o is None else o + part
            h = h + layer["o"](o.transpose(0, 2, 1, 3).reshape(1, N, 4096))
            x = mx.fast.rms_norm(h, layer["ln2"], wt.EPS)
            a = layer["gate"](x)
            h = h + layer["down"](a * mx.sigmoid(a) * layer["up"](x))
            if i % 6 == 5:
                mx.eval(h)
        if store:
            mx.eval(*[t for kv in kept for t in kv])
            return None, kept
        h = mx.fast.rms_norm(h, g["norm_moe_gen.weight"], wt.EPS)
        return (h @ g["proj_out.weight"].T + g["proj_out.bias"]).astype(mx.float32), None


def causal_loop(gen, lat_cs, weights, text_kv, n_text, rope, sigmas, seed, window, sink, stride, log=print):
    """world_transfer.run's per-latent loop with N control streams. lat_cs: N control latents [1, T, h, w, 48];
    weights: N normalised floats. Returns the list of T denoised latents [1, 1, h, w, 48] bf16."""
    import mlx.core as mx
    T, h_lat, w_lat = lat_cs[0].shape[1:4]
    hp, wp = (h_lat + 1) // 2, (w_lat + 1) // 2
    hh = mx.broadcast_to(mx.arange(hp, dtype=mx.float32)[:, None], (hp, wp)).reshape(-1)
    ww = mx.broadcast_to(mx.arange(wp, dtype=mx.float32)[None, :], (hp, wp)).reshape(-1)
    history = MultiHistory(len(lat_cs), window, sink)
    branches = range(len(lat_cs))
    layers = lambda entries: [[text_kv[i]] + [e[i] for e in entries] for i in range(36)]
    out = []
    for f in range(T):
        tf = time.time()
        t_pos = float(n_text + wt.MARGIN) + f * stride
        cos, sin = rope.tables(mx.stack([mx.full(hh.shape, t_pos), hh, ww]))
        # 1. each clean control C_f^i -> its own branch
        for b in branches:
            tokens_c = wt.patchify(lat_cs[b][:, f:f + 1].astype(mx.bfloat16))
            history.add_control(b, gen.control(tokens_c, cos, sin, layers(history.view(b, False))))
        # 2. denoise R_f through the weighted branches
        ctxs = [layers(history.view(b, True)) for b in branches]
        mx.random.seed(seed + f)
        x = mx.random.normal((1, 1, h_lat, w_lat, 48)).astype(mx.float32)
        for step, (s, s_next) in enumerate(zip(sigmas[:-1], sigmas[1:])):
            v, _ = gen.target(wt.patchify(x.astype(mx.bfloat16)), cos, sin, ctxs, weights, sigma=s)
            x0 = x - s * wt.unpatchify(v, h_lat, w_lat)
            if s_next == 0.0:
                x = x0
            else:
                mx.random.seed(seed + f * 1_000_003 + (step + 1) * 9_176)
                x = (1 - s_next) * x0 + s_next * mx.random.normal(x.shape).astype(mx.float32)
            mx.eval(x)
        del ctxs
        out.append(x.astype(mx.bfloat16))
        # 3. clean R_f -> one shared cache entry (skipped for the last frame: nothing reads it)
        if f < T - 1:
            ctxs = [layers(history.view(b, True)) for b in branches]
            _, kv = gen.target(wt.patchify(out[-1]), cos, sin, ctxs, weights, store=True)
            del ctxs
            history.add_target(kv)
        mx.clear_cache()
        log(json.dumps({"latent": f, "of": T, "seconds": round(time.time() - tf, 2),
                        "peak_gb": round(mx.get_peak_memory() / 2 ** 30, 2)}))
    return out


def parse_pairs(pairs, flag, cast=str):
    out = {}
    for pair in pairs or []:
        hint, sep, value = pair.partition("=")
        if not sep or hint not in wt.HINTS:
            raise SystemExit(f"{flag} wants hint=value with hint in {wt.HINTS}, got {pair!r}")
        if hint in out:
            raise SystemExit(f"{flag} names {hint} twice")
        out[hint] = cast(value)
    return out


def run(args):
    import mlx.core as mx
    import numpy as np
    from cosmos3_mlx.encode_vae import encode_video

    controls = parse_pairs(args.control, "--control")
    raw_weights = parse_pairs(args.weight, "--weight", float) if args.weight else {h: 1.0 for h in controls}
    weights = normalize_weights(controls, raw_weights)
    mx.set_default_device(mx.gpu)
    started = time.time()
    clock = {}
    model_dir = Path(args.model_dir)
    cfg = json.loads((model_dir / "config.json").read_text())["cosmos3_nano_sim_bimanual"]
    sigmas = list(cfg["fixed_step_sampler_config"]["t_list"]) + [0.0]
    width, height = (int(n) for n in args.size.split("x"))
    if width % 16 or height % 16:
        raise ValueError("width and height must be multiples of 16")
    hints = list(controls)
    fps = wt.probe_fps(controls[hints[0]])
    videos = [wt.read_video(controls[h], width, height, h, args.frames) for h in hints]
    frames = len(videos[0])
    if any(len(v) != frames for v in videos):
        raise ValueError(f"controls differ in length: {dict(zip(hints, map(len, videos)))}; pass --frames")
    latents_t = 1 + -(-(frames - 1) // wt.TCF)
    text = args.prompt if args.raw_prompt else wt.format_prompt(args.prompt, frames, fps, width, height)
    ids = wt.tokenize(model_dir, text)
    rope = wt.Rope()

    t0 = time.time()
    lat_cs = []
    for video in videos:
        video = wt.reflect_pad(video, 1 + (latents_t - 1) * wt.TCF)
        lat_cs.append(encode_video(video.astype(np.float32) / 255.0, str(model_dir / "vae")))   # [1, T, h, w, 48]
        mx.eval(lat_cs[-1])
        mx.clear_cache()
    del videos
    h_lat, w_lat = lat_cs[0].shape[2:4]
    clock["encode_s"] = time.time() - t0

    t0 = time.time()
    arrays = wt.shard_arrays(model_dir)
    text_kv = wt.text_cache(arrays, ids, rope)
    clock["text_s"] = time.time() - t0
    del arrays
    mx.clear_cache()
    t0 = time.time()
    gen = MultiGenerator(wt.shard_arrays(model_dir), bits=args.quantize)
    mx.clear_cache()
    clock["load_s"] = time.time() - t0
    print(json.dumps({"stage": "loaded", "controls": hints, "weights": weights, "text_tokens": len(ids),
                      "latents": latents_t, "grid": [(h_lat + 1) // 2, (w_lat + 1) // 2],
                      "peak_gb": round(mx.get_peak_memory() / 2 ** 30, 2), **{k: round(v, 1) for k, v in clock.items()}}),
          flush=True)

    t_loop = time.time()
    out = causal_loop(gen, lat_cs, [weights[h] for h in hints], text_kv, len(ids), rope, sigmas, args.seed,
                      args.window, args.sink, wt.BASE_FPS / fps, log=lambda s: print(s, flush=True))
    clock["denoise_s"] = time.time() - t_loop

    del gen, text_kv, lat_cs
    mx.clear_cache()
    t0 = time.time()
    latents = mx.concatenate(out, axis=1)
    if args.save_latents:
        np.save(args.save_latents, np.array(latents.astype(mx.float32)))
    video = wt.decode_chunked(latents, str(model_dir / "vae"), args.decode_chunk)[:frames]
    clock["decode_s"] = time.time() - t0
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    wt.save_mp4((video * 255).round().clip(0, 255).astype(np.uint8), output, fps)
    seconds = time.time() - started
    peak = mx.get_peak_memory() / 2 ** 30
    from kokopelli.wm.manifest import manifest   # commit, dirty, weight hashes: see kokopelli/wm/manifest.py
    sidecar = {
        "variant": "A", "model": model_dir.name, "model_dir": str(model_dir), "checkpoint_id": cfg["checkpoint_id"],
        "runtime": "MLX port (world_transfer_multi.py over world_transfer.py), bf16, weighted per-control attention"
                   + (f", gen weights {args.quantize}-bit" if args.quantize else ""),
        "prompt": args.prompt, "formatted_prompt": text, "controls": {h: str(controls[h]) for h in hints},
        "weights": weights, "raw_weights": raw_weights,
        "size": f"{width}x{height}", "frames": int(len(video)), "latent_frames": latents_t, "fps": fps, "seed": args.seed,
        "steps": len(sigmas) - 1, "sigmas": sigmas, "guidance": 1.0, "window": args.window, "sink": args.sink,
        "seconds": round(seconds, 1), "seconds_per_output_second": round(seconds / (len(video) / fps), 1),
        "timing": {k: round(v, 1) for k, v in clock.items()}, "peak_gb": round(peak, 2),
        "ru_maxrss_gb": round(__import__("resource").getrusage(__import__("resource").RUSAGE_SELF).ru_maxrss / 2 ** 30, 2),
        "manifest": manifest(weights=model_dir, seed=args.seed, prompt=args.prompt, quantize=args.quantize,
                             controls={h: {"path": str(controls[h]), "weight": weights[h]} for h in hints},
                             resolution=f"{width}x{height}", fake=False),
        **(json.loads(args.extra) if args.extra else {}),
    }
    Path(str(output) + ".json").write_text(json.dumps(sidecar, indent=1))
    print(json.dumps({"done": str(output), "seconds": sidecar["seconds"], "peak_gb": sidecar["peak_gb"]}), flush=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("prompt", help="caption text, or a JSON-object caption like NVIDIA's upsampled prompts")
    p.add_argument("--control", action="append", required=True, metavar="HINT=PATH", help="repeat once per control")
    p.add_argument("--weight", action="append", metavar="HINT=W", help="one per control; omitted = equal weights")
    p.add_argument("--output", required=True)
    p.add_argument("--size", default="832x480")
    p.add_argument("--frames", type=int)
    p.add_argument("--seed", type=int, default=2025)
    p.add_argument("--window", type=int, default=51, help="history window in latent frames, 0 = full history")
    p.add_argument("--sink", type=int, default=1)
    p.add_argument("--quantize", type=int, choices=(4, 8))
    p.add_argument("--decode-chunk", type=int, default=6)
    p.add_argument("--model-dir", default=str(wt.MODEL_DIR))
    p.add_argument("--save-latents", help="also write the denoised latents to this .npy (equivalence checks)")
    p.add_argument("--raw-prompt", action="store_true", help="skip the reference's duration/fps/resolution metadata")
    p.add_argument("--extra", help="JSON merged into the sidecar")
    p.add_argument("--dry-run", action="store_true", default=DRY_RUN, help="one latent only, written beside --output (KOKO_DRY_RUN=1)")
    return p


def dry_run_args(args):
    """The same job cut to one latent chunk (latent 0 is frame 0), written beside the real output so it never replaces it."""
    output = Path(args.output)
    args.output = str(output.with_name(f"{output.stem}.dryrun{output.suffix or '.mp4'}"))
    args.frames, args.save_latents = 1, None
    args.extra = json.dumps({**(json.loads(args.extra) if args.extra else {}),
                             "dry_run": "dry run, 1 chunk", "dry_run_of": str(output)})
    return args


def main(argv=None):
    args = parser().parse_args(argv)
    if args.window and not 0 <= args.sink < args.window:
        raise SystemExit("need 0 <= sink < window")
    run(dry_run_args(args) if args.dry_run else args)


if __name__ == "__main__":
    main()
