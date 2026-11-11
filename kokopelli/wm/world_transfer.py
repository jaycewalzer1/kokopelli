"""Cosmos3-Nano-Sim-Transfer on the Mac (MLX): repaint a sim control video (depth, seg, edge or blur) as photoreal RGB.

This is a port of NVIDIA's causal Sim-Transfer inference (cosmos-framework `omni_mot_causal_model.py`,
`iter_samples_from_batch_autoregressive`, mode `video_transfer`), not the base-model hack in world_filter.py.
The model makes one latent frame at a time (4 video frames, the first one alone):

  1. the clean control latent C_f goes through the generation pathway and its keys/values are cached,
  2. the target latent R_f starts as noise and takes NVIDIA's 4 fixed stochastic steps [1, 15/16, 5/6, 5/8] -> 0,
     each looking at the text, the cached history and C_f,
  3. the finished R_f goes through once more, clean, so the next frames read it from the cache.

Control and target share temporal positions; text is cached once. Guidance is baked into the distilled weights (1.0).
Every deviation from the reference is listed in docs/SIM_TRANSFER_MLX.md.

Call `transfer_video(...)` from any Python; it runs this file in the cosmos3-mlx venv under a ram_share hold and
writes `<output>` plus `<output>.json`.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models" / "Cosmos3-Nano-Sim-Transfer"
RUNNER = Path.home() / "cosmos3" / "cosmos3-mlx"
HINTS = ("depth", "seg", "edge", "blur")
SYSTEM_PROMPT = ("You are a helpful assistant that generates images or videos following the user's instructions"
                 " and control signals (edge maps, blur, depth, or segmentation).")
MARGIN = 15000          # unified_3d_mrope_temporal_modality_margin
BASE_FPS = 24.0         # diffusion_expert_config.base_fps
TCF = 4                 # VAE temporal compression
EPS = 1e-6


def transfer_video(prompt, controls, output, size="832x480", frames=None, seed=2025, window=51, sink=1,
                   hold_gb=20, quantize=None, model_dir=MODEL_DIR, decode_chunk=6, raw_prompt=False, save_latents=None, extra=None,
                   labels=None):
    """Repaint one control video. controls: {"depth"|"seg"|"edge"|"blur": path}, exactly one (the causal checkpoint
    takes one control per request). size "WxH" (832x480 is the native 16:9 canvas). frames: first N frames of the
    control (None = all). window/sink: history window in latent frames and pinned initial frames (config: 51/1;
    NVIDIA's 600-frame example uses 30/3). labels: optional object labels (kokopelli/wm/labels.py),
    {"file": labels.json, "frames": the clip's labels/ folder} plus any of steps, tau, mode, beta, store, max.
    Returns the output path; the sidecar is output + ".json"."""
    if len(controls) != 1:
        raise ValueError(f"Sim-Transfer takes exactly one control per request, got {sorted(controls)}")
    (hint, path), = controls.items()
    output = Path(output).resolve()
    command = [str(RUNNER / ".venv" / "bin" / "python"), "-m", "kokopelli.wm.world_transfer", prompt,
               "--hint", hint, "--control", str(Path(path).resolve()), "--output", str(output), "--size", size,
               "--seed", str(seed), "--window", str(window), "--sink", str(sink), "--model-dir", str(model_dir),
               "--decode-chunk", str(decode_chunk)]
    if frames:
        command += ["--frames", str(frames)]
    if quantize:
        command += ["--quantize", str(quantize)]
    if raw_prompt:
        command += ["--raw-prompt"]
    if save_latents:
        command += ["--save-latents", str(save_latents)]
    if extra:
        command += ["--extra", json.dumps(extra)]
    if labels:
        command += ["--labels", str(Path(labels["file"]).resolve()), "--label-frames", str(Path(labels["frames"]).resolve())]
        for key in ("steps", "tau", "mode", "beta", "max"):
            if labels.get(key) is not None:
                command += [f"--label-{key}", str(labels[key])]
        if labels.get("store"):
            command += ["--label-store"]
    if hold_gb:
        command = [sys.executable, str(ROOT / "kokopelli" / "ops" / "ram_share.py"), "hold", "--name", "sim_transfer", "--gb", str(hold_gb),
                   "--"] + command
    result = subprocess.run(command, cwd=RUNNER, capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": f"{RUNNER}{os.pathsep}{ROOT}"})
    if result.returncode:
        raise RuntimeError(f"world_transfer.py failed ({result.returncode}): {result.stderr[-1500:]}")
    return output


# ---------------------------------------------------------------- everything below runs in the cosmos3-mlx venv

def probe_fps(path):
    rate = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                           "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True).stdout.strip()
    num, den = rate.split("/")
    return float(num) / float(den)


def read_video(path, width, height, hint, frames=None):
    """Direct resize to the canvas (no crop): nearest for seg, bilinear (area-filtered when shrinking) otherwise."""
    import numpy as np
    flags = "neighbor" if hint == "seg" else "bilinear"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={width}:{height}:flags={flags}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
    video = np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3)
    return video[:frames] if frames else video


def reflect_pad(video, target):
    """cosmos_framework.inference.vision.pad_temporal_frames: append the clip played backwards from its last frame."""
    import numpy as np
    while len(video) < target:
        n = min(len(video) - 1, target - len(video))
        if n <= 0:
            return np.concatenate([video, np.repeat(video[-1:], target - len(video), 0)])
        video = np.concatenate([video, video[::-1][:n]])
    return video


def aspect_label(width, height):
    ratio = width / height
    for label, value in (("1,1", 1.0), ("4,3", 4 / 3), ("3,4", 3 / 4), ("16,9", 16 / 9), ("9,16", 9 / 16)):
        if abs(ratio / value - 1) <= 0.03:
            return label
    return None


def format_prompt(prompt, frames, fps, width, height):
    """Training's metadata: JSON prompts get duration/fps/resolution/aspect fields, plain prompts two sentences."""
    try:
        obj = json.loads(prompt)
    except (ValueError, TypeError):
        obj = None
    if isinstance(obj, dict):
        obj.update({"duration": f"{int(frames / fps)}s", "fps": float(round(fps))})
        obj["resolution"] = {"H": height, "W": width}
        if aspect_label(width, height):
            obj["aspect_ratio"] = aspect_label(width, height)
        return json.dumps(obj)
    text = prompt.strip()
    text = text.rstrip(".") + ". " + f"The video is {frames / round(fps):.1f} seconds long and is of {round(fps):.0f} FPS."
    return text.rstrip(".") + ". " + f"This video is of {height}x{width} resolution."


def chat_text(tokenizer, text):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}]
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def tokenize(model_dir, text):
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(Path(model_dir) / "text_tokenizer"))
    chat = chat_text(tokenizer, text)
    ids = tokenizer.encode(chat, add_special_tokens=False)
    # Training truncated chat ids at 4096 (imaginaire4 _MAX_NUM_TOKENS; SGLang TEXT_TOKENS_TRAINING_MAX). The config's
    # text_cache_max_len=512 is only the paged/static-compile engine's buffer size, not a training limit.
    ids = list(ids)[:4096]
    # Text split = chat ids + EOS + start-of-generation (no BOS for Qwen); compute_text_split_length.
    return list(ids) + [tokenizer.eos_token_id, tokenizer.convert_tokens_to_ids("<|vision_start|>")]


def token_offsets(model_dir, text):
    """The chat string `tokenize` encodes and each of its tokens' (start, end) characters in it, cut at the same 4096.
    Token i here is id i of `tokenize` (whose two closing ids have no text). Object labels use it to find which text
    keys carry a label's words (labels.find_spans)."""
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(Path(model_dir) / "text_tokenizer"))
    chat = chat_text(tokenizer, text)
    offsets = tokenizer(chat, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"]
    return chat, [tuple(o) for o in offsets][:4096]


def attention_mask(text_mask, n_keys):
    """labels.text_mask's [N, L_text] bias, widened to the target's whole key list: [1, 1, N, n_keys] bf16. The text
    keys come first in Generator.__call__'s concatenation, so text column j is key j; the history's keys and the
    frame's own get 0 (never masked)."""
    import mlx.core as mx
    if text_mask is None:
        return None
    n, n_text = text_mask.shape
    return mx.concatenate([mx.array(text_mask), mx.zeros((n, n_keys - n_text))], axis=1)[None, None].astype(mx.bfloat16)


class Rope:
    """Interleaved 3D mRoPE (Qwen3-VL): dims 1,4,..,58 take height, 2,5,..,59 width, the rest time."""

    def __init__(self, theta=5_000_000.0, head_dim=128, section=(24, 20, 20)):
        import mlx.core as mx
        half = head_dim // 2
        self.inv = 1.0 / (theta ** (mx.arange(0, head_dim, 2, dtype=mx.float32) / head_dim))
        axis = [0] * half
        for offset, a in ((1, 1), (2, 2)):
            for d in range(offset, min(section[a] * 3, half), 3):
                axis[d] = a
        self.axis = mx.array(axis)

    def tables(self, pos):
        """pos [3, N] float -> cos, sin [1, N, 1, head_dim]."""
        import mlx.core as mx
        f = pos[:, :, None] * self.inv[None, None, :]                # [3, N, 64]
        f = mx.where(self.axis == 0, f[0], mx.where(self.axis == 1, f[1], f[2]))
        f = mx.concatenate([f, f], axis=-1)[None, :, None, :]
        return mx.cos(f), mx.sin(f)


def rotate(x, cos, sin):
    import mlx.core as mx
    half = x.shape[-1] // 2
    rot = mx.concatenate([-x[..., half:], x[..., :half]], axis=-1)
    return (x.astype(mx.float32) * cos + rot.astype(mx.float32) * sin).astype(x.dtype)


def shard_arrays(model_dir):
    import mlx.core as mx
    out = {}
    for shard in sorted((Path(model_dir) / "transformer").glob("*.safetensors")):
        out.update(mx.load(str(shard)))  # pyright: ignore[reportCallIssue, reportArgumentType]  # a .safetensors load is a dict; lazy: nothing is read until an array is evaluated
    return out


def linear_fn(w, bits):
    """x @ w.T, optionally through an MLX-quantized copy of w."""
    import mlx.core as mx
    if not bits:
        w = w.astype(mx.bfloat16)
        mx.eval(w)
        return lambda x: x @ w.T
    wq, scales, biases = mx.quantize(w.astype(mx.bfloat16), group_size=64, bits=bits)
    mx.eval(wq, scales, biases)
    return lambda x: mx.quantized_matmul(x, wq, scales, biases, transpose=True, group_size=64, bits=bits)


def text_cache(arrays, ids, rope):
    """Understanding pathway over the caption, one layer at a time; returns per-layer (K, V) [1, 8, L, 128]."""
    import mlx.core as mx
    L = len(ids)
    h = arrays["embed_tokens.weight"][mx.array(ids)][None].astype(mx.bfloat16)
    pos = mx.broadcast_to(mx.arange(L, dtype=mx.float32)[None], (3, L))
    cos, sin = rope.tables(pos)
    mask = mx.triu(mx.full((L, L), -mx.inf, dtype=mx.bfloat16), k=1)
    cache = []
    for i in range(36):
        p = f"layers.{i}."
        g = lambda n, p=p: arrays[p + n].astype(mx.bfloat16)
        x = mx.fast.rms_norm(h, g("input_layernorm.weight"), EPS)
        q = mx.fast.rms_norm((x @ g("self_attn.to_q.weight").T).reshape(1, L, 32, 128), g("self_attn.norm_q.weight"), EPS)
        k = mx.fast.rms_norm((x @ g("self_attn.to_k.weight").T).reshape(1, L, 8, 128), g("self_attn.norm_k.weight"), EPS)
        v = (x @ g("self_attn.to_v.weight").T).reshape(1, L, 8, 128)
        q, k = rotate(q, cos, sin), rotate(k, cos, sin)
        q, k, v = (t.transpose(0, 2, 1, 3) for t in (q, k, v))
        cache.append((k, v))
        if i < 35:
            o = mx.fast.scaled_dot_product_attention(q, k, v, scale=128 ** -0.5, mask=mask)
            h = h + o.transpose(0, 2, 1, 3).reshape(1, L, 4096) @ g("self_attn.to_out.weight").T
            x = mx.fast.rms_norm(h, g("post_attention_layernorm.weight"), EPS)
            h = h + (mx.fast.silu if hasattr(mx.fast, "silu")  # pyright: ignore[reportAttributeAccessIssue]  # guarded by hasattr
                      else (lambda a: a * mx.sigmoid(a)))(
                x @ g("mlp.gate_proj.weight").T) * (x @ g("mlp.up_proj.weight").T) @ g("mlp.down_proj.weight").T
        mx.eval(h, k, v)
    return cache


class Generator:
    """The generation pathway (the 'moe_gen' half of each layer), held in memory for the whole clip."""

    def __init__(self, arrays, bits=None):
        import mlx.core as mx
        bf = lambda n: arrays[n].astype(mx.bfloat16)
        self.layers = []
        for i in range(36):
            p = f"layers.{i}."
            layer = {name: linear_fn(arrays[p + key], bits) for name, key in (
                ("q", "self_attn.add_q_proj.weight"), ("k", "self_attn.add_k_proj.weight"),
                ("v", "self_attn.add_v_proj.weight"), ("o", "self_attn.to_add_out.weight"),
                ("gate", "mlp_moe_gen.gate_proj.weight"), ("up", "mlp_moe_gen.up_proj.weight"),
                ("down", "mlp_moe_gen.down_proj.weight"))}
            for name, key in (("ln1", "input_layernorm_moe_gen.weight"), ("ln2", "post_attention_layernorm_moe_gen.weight"),
                              ("qn", "self_attn.norm_added_q.weight"), ("kn", "self_attn.norm_added_k.weight")):
                layer[name] = bf(p + key)
                mx.eval(layer[name])
            self.layers.append(layer)
        self.g = {n: bf(n) for n in ("proj_in.weight", "proj_in.bias", "proj_out.weight", "proj_out.bias", "norm_moe_gen.weight",
                                     "time_embedder.linear_1.weight", "time_embedder.linear_1.bias",
                                     "time_embedder.linear_2.weight", "time_embedder.linear_2.bias")}
        mx.eval(*self.g.values())

    def time_embed(self, sigma):
        """Timesteps are sigma*1000, scaled by timestep_scale 0.001 -> sigma; sinusoid [cos, sin], 256 channels."""
        import math
        import mlx.core as mx
        freqs = mx.exp(-math.log(10000.0) * mx.arange(128, dtype=mx.float32) / 128)
        args = mx.array([sigma], dtype=mx.float32)[:, None] * freqs[None]
        e = mx.concatenate([mx.cos(args), mx.sin(args)], axis=-1).astype(mx.bfloat16)
        g = self.g
        e = e @ g["time_embedder.linear_1.weight"].T + g["time_embedder.linear_1.bias"]
        e = e * mx.sigmoid(e)
        return e @ g["time_embedder.linear_2.weight"].T + g["time_embedder.linear_2.bias"]   # [1, 4096]

    def __call__(self, tokens, cos, sin, context, sigma=None, store=False, mask=None):
        """tokens [1, N, 192] patch latents. context: per layer list of (K, V) to attend to besides the tokens
        themselves. mask: additive attention bias [1, 1, N, keys] over [context... | own] (object labels,
        attention_mask), None = every token reads every key. Returns velocity [1, N, 192] (or None when store) and,
        when store, per-layer (K, V)."""
        import mlx.core as mx
        g = self.g
        N = tokens.shape[1]
        h = tokens.astype(mx.bfloat16) @ g["proj_in.weight"].T + g["proj_in.bias"]
        if sigma is not None:   # only noisy tokens get the timestep; clean ones get none
            h = h + self.time_embed(sigma)[:, None, :]
        kept = []
        for i, layer in enumerate(self.layers):
            x = mx.fast.rms_norm(h, layer["ln1"], EPS)
            q = rotate(mx.fast.rms_norm(layer["q"](x).reshape(1, N, 32, 128), layer["qn"], EPS), cos, sin)
            k = rotate(mx.fast.rms_norm(layer["k"](x).reshape(1, N, 8, 128), layer["kn"], EPS), cos, sin)
            v = layer["v"](x).reshape(1, N, 8, 128)
            q, k, v = (t.transpose(0, 2, 1, 3) for t in (q, k, v))
            if store:
                kept.append((k, v))
                if i == 35:
                    break
            ks = [c[0] for c in context[i]] + [k]
            vs = [c[1] for c in context[i]] + [v]
            o = mx.fast.scaled_dot_product_attention(q, mx.concatenate(ks, axis=2), mx.concatenate(vs, axis=2),
                                                     scale=128 ** -0.5, mask=mask)
            h = h + layer["o"](o.transpose(0, 2, 1, 3).reshape(1, N, 4096))
            x = mx.fast.rms_norm(h, layer["ln2"], EPS)
            a = layer["gate"](x)
            h = h + layer["down"](a * mx.sigmoid(a) * layer["up"](x))
            if i % 6 == 5:
                mx.eval(h)
        if store:
            mx.eval(*[t for kv in kept for t in kv])
            return None, kept
        h = mx.fast.rms_norm(h, g["norm_moe_gen.weight"], EPS)
        return (h @ g["proj_out.weight"].T + g["proj_out.bias"]).astype(mx.float32), None


class History:
    """Cached control/RGB entries per layer: C_0, R_0, C_1, R_1, ... Keys already carry their RoPE, so evicting entries
    keeps the position clock. A window W with sink S shows the first 2S entries plus the most recent ones."""

    def __init__(self, window, sink):
        self.entries = []   # list of per-layer (K, V) lists
        self.window, self.sink = window, sink

    def add(self, kv):
        self.entries.append(kv)
        if self.window:
            keep = 2 * self.sink + 2 * (self.window - self.sink - 1) + 1
            if len(self.entries) > keep:
                del self.entries[2 * self.sink]

    def view(self, for_target):
        chosen = self.entries
        if self.window:
            recent = 2 * (self.window - self.sink - 1) + (1 if for_target else 0)
            sinks = chosen[:2 * self.sink]
            rest = chosen[2 * self.sink:]
            chosen = sinks + (rest[-recent:] if recent else [])
        return chosen


def patchify(lat):
    """[1, T, h, w, 48] -> [1, T*hp*wp, 192] with zero padding to even h, w (HF _patchify_and_pack_latents)."""
    import mlx.core as mx
    b, t, h, w, z = lat.shape
    hp, wp = (h + 1) // 2, (w + 1) // 2
    if hp * 2 != h:
        lat = mx.concatenate([lat, mx.zeros((b, t, 1, w, z), lat.dtype)], axis=2)
    if wp * 2 != w:
        lat = mx.concatenate([lat, mx.zeros((b, t, lat.shape[2], 1, z), lat.dtype)], axis=3)
    x = lat.reshape(b, t, hp, 2, wp, 2, z).transpose(0, 1, 2, 4, 3, 5, 6)
    return x.reshape(b, t * hp * wp, 4 * z)


def unpatchify(tokens, h, w):
    b, n, _ = tokens.shape
    hp, wp = (h + 1) // 2, (w + 1) // 2
    x = tokens.reshape(b, n // (hp * wp), hp, wp, 2, 2, 48).transpose(0, 1, 2, 4, 3, 5, 6)
    return x.reshape(b, -1, hp * 2, wp * 2, 48)[:, :, :h, :w]


def decode_chunked(latents, vae_dir, chunk, warm=3):
    """The port's decoder runs a whole clip at once, which doesn't fit at 480p x 150 frames. Decode `chunk` latents at a
    time with `warm` earlier latents as causal context and drop the frames they produce."""
    import mlx.core as mx
    import numpy as np
    from cosmos3_mlx.decode_vae import decode_latents
    T = latents.shape[1]
    if not chunk or chunk >= T:
        video = decode_latents(latents, vae_dir)
        mx.eval(video)
        return np.array(video[0].astype(mx.float32))
    parts = []
    for start in range(0, T, chunk):
        end = min(T, start + chunk)
        ctx = max(0, start - warm)
        video = decode_latents(latents[:, ctx:end], vae_dir)
        mx.eval(video)
        video = np.array(video[0].astype(mx.float32))
        parts.append(video if start == 0 else video[-4 * (end - start):])
        del video
        mx.clear_cache()
    return np.concatenate(parts)


def save_mp4(frames, path, fps):
    h, w = frames.shape[1:3]
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                             "-r", f"{fps:g}", "-i", "-", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(path)],
                            stdin=subprocess.PIPE)
    proc.communicate(frames.tobytes())
    if proc.returncode:
        raise RuntimeError("ffmpeg failed to write the video")


def run(args):
    import mlx.core as mx
    import numpy as np
    from cosmos3_mlx.encode_vae import encode_video

    mx.set_default_device(mx.gpu)
    started = time.time()
    clock = {}
    model_dir = Path(args.model_dir)
    cfg = json.loads((model_dir / "config.json").read_text())["cosmos3_nano_sim_bimanual"]
    sigmas = list(cfg["fixed_step_sampler_config"]["t_list"]) + [0.0]
    width, height = (int(n) for n in args.size.split("x"))
    if width % 16 or height % 16:
        raise ValueError("width and height must be multiples of 16")
    fps = probe_fps(args.control)
    control = read_video(args.control, width, height, args.hint, args.frames)
    frames = len(control)
    latents_t = 1 + -(-(frames - 1) // TCF)
    control = reflect_pad(control, 1 + (latents_t - 1) * TCF)
    paint = None   # object labels (kokopelli/wm/labels.py); without --labels nothing below changes
    if getattr(args, "labels", None):
        from kokopelli.wm import labels as lb
        paint = lb.Paint(args.labels, args.label_frames, width, height, reflect_pad(np.arange(frames), len(control)),
                         steps=args.label_steps, tau=args.label_tau, mode=args.label_mode, beta=args.label_beta,
                         store=args.label_store, max_labels=args.label_max)
    prompt = paint.prompt(args.prompt) if paint else args.prompt
    text = prompt if args.raw_prompt else format_prompt(prompt, frames, fps, width, height)
    ids = tokenize(model_dir, text)
    if paint:
        paint.bind(*token_offsets(model_dir, text), len(ids))
    stride = BASE_FPS / fps
    rope = Rope()

    t0 = time.time()
    lat_c = encode_video(control.astype(np.float32) / 255.0, str(model_dir / "vae"))   # [1, T, h, w, 48]
    mx.eval(lat_c)
    h_lat, w_lat = lat_c.shape[2:4]
    hp, wp = (h_lat + 1) // 2, (w_lat + 1) // 2
    if paint and paint.grid != [hp, wp]:
        raise ValueError(f"label regions were laid out on a {paint.grid} token grid, the latents give {[hp, wp]}")
    clock["encode_s"] = time.time() - t0
    mx.clear_cache()

    t0 = time.time()
    arrays = shard_arrays(model_dir)
    text_kv = text_cache(arrays, ids, rope)
    clock["text_s"] = time.time() - t0
    del arrays
    mx.clear_cache()
    t0 = time.time()
    gen = Generator(shard_arrays(model_dir), bits=args.quantize)
    mx.clear_cache()
    clock["load_s"] = time.time() - t0
    print(json.dumps({"stage": "loaded", "text_tokens": len(ids), "latents": latents_t, "grid": [hp, wp],
                      "peak_gb": round(mx.get_peak_memory() / 2 ** 30, 2), **{k: round(v, 1) for k, v in clock.items()}}),
          flush=True)

    hh = mx.broadcast_to(mx.arange(hp, dtype=mx.float32)[:, None], (hp, wp)).reshape(-1)
    ww = mx.broadcast_to(mx.arange(wp, dtype=mx.float32)[None, :], (hp, wp)).reshape(-1)
    history = History(args.window, args.sink)
    out = []
    t_loop = time.time()
    for f in range(latents_t):
        tf = time.time()
        t_pos = float(len(ids) + MARGIN) + f * stride
        cos, sin = rope.tables(mx.stack([mx.full(hh.shape, t_pos), hh, ww]))
        layers = lambda entries: [[text_kv[i]] + [e[i] for e in entries] for i in range(36)]  # noqa: F821 -- pyflakes sees the later `del text_kv`; only called inside the loop, before it
        # 1. clean control C_f -> cache
        tokens_c = patchify(lat_c[:, f:f + 1].astype(mx.bfloat16))
        _, kv = gen(tokens_c, cos, sin, layers(history.view(False)), store=True)
        history.add(kv)
        # 2. denoise R_f: the four fixed SDE steps
        ctx = layers(history.view(True))
        # Labels: tokens outside a label's region can't read its words, for the first label_steps steps (and the store
        # pass if asked). The keys are [text | history entries | this frame], hp*wp tokens per entry.
        mask = attention_mask(paint.mask(f), len(ids) + len(ctx[0]) * hp * wp) if paint else None
        mx.random.seed(args.seed + f)
        x = mx.random.normal((1, 1, h_lat, w_lat, 48)).astype(mx.float32)
        for step, (s, s_next) in enumerate(zip(sigmas[:-1], sigmas[1:], strict=False)):
            v, _ = gen(patchify(x.astype(mx.bfloat16)), cos, sin, ctx, sigma=s,
                       mask=mask if paint and step < paint.steps else None)
            x0 = x - s * unpatchify(v, h_lat, w_lat)
            if s_next == 0.0:
                x = x0
            else:
                mx.random.seed(args.seed + f * 1_000_003 + (step + 1) * 9_176)
                x = (1 - s_next) * x0 + s_next * mx.random.normal(x.shape).astype(mx.float32)
            mx.eval(x)
        del ctx
        out.append(x.astype(mx.bfloat16))
        # 3. clean R_f -> cache (skipped for the last frame: nothing reads it)
        if f < latents_t - 1:
            _, kv = gen(patchify(out[-1]), cos, sin, layers(history.view(True)), store=True,
                        mask=mask if paint and paint.store else None)
            history.add(kv)
        mx.clear_cache()
        print(json.dumps({"latent": f, "of": latents_t, "seconds": round(time.time() - tf, 2),
                          "peak_gb": round(mx.get_peak_memory() / 2 ** 30, 2)}), flush=True)
    clock["denoise_s"] = time.time() - t_loop

    del gen, history, text_kv
    mx.clear_cache()
    t0 = time.time()
    latents = mx.concatenate(out, axis=1)
    if args.save_latents:
        np.save(args.save_latents, np.array(latents.astype(mx.float32)))
    video = decode_chunked(latents, str(model_dir / "vae"), args.decode_chunk)[:frames]
    clock["decode_s"] = time.time() - t0
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_mp4((video * 255).round().clip(0, 255).astype(np.uint8), output, fps)
    seconds = time.time() - started
    peak = mx.get_peak_memory() / 2 ** 30
    sidecar = {
        "model": model_dir.name, "model_dir": str(model_dir), "checkpoint_id": cfg["checkpoint_id"],
        "runtime": "MLX port (world_transfer.py), bf16" + (f", gen weights {args.quantize}-bit" if args.quantize else ""),
        "prompt": args.prompt, "formatted_prompt": text, "controls": {args.hint: str(args.control)},
        "size": f"{width}x{height}", "frames": int(len(video)), "latent_frames": latents_t, "fps": fps, "seed": args.seed,
        "steps": len(sigmas) - 1, "sigmas": sigmas, "guidance": 1.0, "window": args.window, "sink": args.sink,
        "seconds": round(seconds, 1), "seconds_per_output_second": round(seconds / (len(video) / fps), 1),
        "timing": {k: round(v, 1) for k, v in clock.items()}, "peak_gb": round(peak, 2),
        "ru_maxrss_gb": round(__import__("resource").getrusage(__import__("resource").RUSAGE_SELF).ru_maxrss / 2 ** 30, 2),
        **(json.loads(args.extra) if args.extra else {}),
    }
    if paint:
        from kokopelli.wm.manifest import manifest
        sidecar["labels"] = {**paint.report(), "seconds_per_latent": round(clock["denoise_s"] / latents_t, 2)}
        sidecar["manifest"] = manifest(weights=model_dir, seed=args.seed, prompt=args.prompt, quantize=args.quantize,
                                       controls={args.hint: {"path": str(args.control)}},
                                       resolution=f"{width}x{height}", labels=paint.identity())
    Path(str(output) + ".json").write_text(json.dumps(sidecar, indent=1))
    print(json.dumps({"done": str(output), "seconds": sidecar["seconds"], "peak_gb": sidecar["peak_gb"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prompt", help="caption text, or a JSON-object caption like NVIDIA's upsampled prompts")
    parser.add_argument("--hint", choices=HINTS, required=True)
    parser.add_argument("--control", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--size", default="832x480")
    parser.add_argument("--frames", type=int)
    parser.add_argument("--seed", type=int, default=2025)
    parser.add_argument("--window", type=int, default=51, help="history window in latent frames, 0 = full history")
    parser.add_argument("--sink", type=int, default=1)
    parser.add_argument("--quantize", type=int, choices=(4, 8))
    parser.add_argument("--decode-chunk", type=int, default=6)
    parser.add_argument("--model-dir", default=str(MODEL_DIR))
    parser.add_argument("--save-latents", help="also write the denoised latents to this .npy (debugging)")
    parser.add_argument("--raw-prompt", action="store_true", help="skip the reference's duration/fps/resolution metadata")
    parser.add_argument("--extra", help="JSON merged into the sidecar")
    lab = parser.add_argument_group("object labels (kokopelli/wm/labels.py, docs/LABELS_PLAN.md)")
    lab.add_argument("--labels", help="labels.json; the caption gains one subject per labeled actor in frame")
    lab.add_argument("--label-frames", help="the clip's labels/ folder (16-bit PNGs, one per control frame)")
    lab.add_argument("--label-steps", type=int, default=2, choices=range(5),
                     help="denoise steps (of 4, from the first) in which only a label's own region reads its words; "
                          "0 = caption only")
    lab.add_argument("--label-tau", type=float, default=0.25, help="share of a token a label must cover to own it")
    lab.add_argument("--label-mode", choices=("hard", "soft"), default="hard",
                     help="hard: other tokens can't read the label at all; soft: -beta outside, +beta inside")
    lab.add_argument("--label-beta", type=float, default=5.0)
    lab.add_argument("--label-store", action="store_true", help="also mask the clean pass that becomes history")
    lab.add_argument("--label-max", type=int, default=6, help="most labels the caption names (0 = no cap)")
    args = parser.parse_args()
    if args.window and not 0 <= args.sink < args.window:
        raise SystemExit("need 0 <= sink < window")
    if bool(args.labels) != bool(args.label_frames):
        raise SystemExit("--labels and --label-frames go together")
    run(args)


if __name__ == "__main__":
    main()
