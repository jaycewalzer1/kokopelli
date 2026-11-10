"""Repaint a control video with Cosmos3-Nano: the sim fixes the shapes, the model paints them. Runs from Cosmos's own environment.

The Mac runner has no control input, so this adds it, following diffusers' Cosmos3 transfer pipeline. The control video goes
in as clean extra frames in front of the frames being generated, at the same positions in time and space, so that the model
sees each frame's edges alongside that frame. Later chunks also start from the last frames of the one before, which carries
the look across chunks; the control keeps pulling the shapes back to the sim, which continuing a video alone can't do.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

import mlx.core as mx
import numpy as np

# From diffusers' Cosmos3 transfer pipeline. The model was trained with this exact sentence.
SYSTEM_PROMPT = ("You are a helpful assistant that generates images or videos following the user's instructions"
                 " and control signals (edge maps, blur, depth, or segmentation).")
# NVIDIA's edge example uses these two.
GUIDANCE, CONTROL_GUIDANCE = 3.0, 1.5


def chunk_windows(total, frames, cond):
    """(start, end) of each chunk. Each one after the first starts cond frames before the last one ended."""
    if frames > total:
        raise ValueError(f"a chunk of {frames} frames doesn't fit in {total}")
    stride = frames - cond
    if stride <= 0:
        raise ValueError("cond must be smaller than frames")
    return [(start, start + frames) for start in range(0, total - frames + 1, stride)]


def latent_frames(cond):
    """How many latent frames cond video frames cover: the first alone, then four to each."""
    return (cond - 1) // 4 + 1 if cond else 0


def pack_positions(target_ids, text_len):
    """Text, then the control and target at identical positions. [3, 1, text + n] becomes [3, 1, text + 2n]."""
    text, vision = target_ids[:, :, :text_len], target_ids[:, :, text_len:]
    return mx.concatenate([text, vision, vision], axis=2)


def noisy_mask(grid_t, spatial, conditioned, with_control):
    """1 for tokens that get the timestep. Clean tokens get none, which is how the model knows they're given."""
    target = [0.0] * (conditioned * spatial) + [1.0] * ((grid_t - conditioned) * spatial)
    return mx.array(([0.0] * (grid_t * spatial) if with_control else []) + target).reshape(1, -1, 1)


def guided(full, without_control, uncond, guidance, control_guidance):
    """Nested guidance: push away from no control first, then from the negative prompt."""
    conditioned = without_control + control_guidance * (full - without_control) if without_control is not None else full
    return uncond + guidance * (conditioned - uncond)


class Painter:
    def __init__(self, model_dir, size, frames, steps, guidance=GUIDANCE, control_guidance=CONTROL_GUIDANCE):
        from cosmos3_mlx.load import load_tokenizer, load_transformer
        from cosmos3_mlx.pipeline import Cosmos3GenerationPipeline

        self.model = load_transformer(model_dir, reasoner_only=False)
        self.pipeline = Cosmos3GenerationPipeline(model=self.model, tokenizer=load_tokenizer(model_dir), model_dir=model_dir)
        self.model_dir, self.size, self.frames, self.steps = Path(model_dir), size, frames, steps
        self.guidance, self.control_guidance = guidance, control_guidance

    def tokens(self, text):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}]
        tokenizer = self.pipeline.tokenizer
        ids = tokenizer.encode(tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True))
        return mx.array([ids + [tokenizer.eos_token_id, tokenizer.convert_tokens_to_ids("<|vision_start|>")]])

    def first_pass(self, ids, tokens, step_time, mask, positions):
        """A full pass, which also keeps the text's keys and values. They don't depend on the video, so later passes reuse them."""
        model = self.model
        text = model.embed_tokens(ids)
        hidden = model.proj_in(tokens) + mask * mx.expand_dims(model.time_embedder(step_time * 0.001), 1)
        cache = []
        for layer in model.layers:
            text, hidden, kv = layer.forward_with_generation(text, hidden, positions)
            cache.append(kv)
        mx.eval(*[part for kv in cache for part in kv])
        return model.proj_out(model.norm_moe_gen(hidden)), cache

    def cached_pass(self, cache, text_len, tokens, step_time, mask, positions):
        model = self.model
        hidden = model.proj_in(tokens) + mask * mx.expand_dims(model.time_embedder(step_time * 0.001), 1)
        for layer, kv in zip(model.layers, cache, strict=False):
            hidden = layer.forward_generation_cached(hidden, kv, positions, text_len)
        return model.proj_out(model.norm_moe_gen(hidden))

    def paint(self, prompt, control, previous, seed):
        """One chunk. control is [frames, H, W, 3], previous the frames to start from, or None. Returns [frames, H, W, 3] uint8."""
        from cosmos3_mlx.decode_vae import decode_latents
        from cosmos3_mlx.scheduler import UniPCScheduler

        pipeline, dtype = self.pipeline, mx.bfloat16
        width, height = self.size
        mx.random.seed(seed)
        latents = pipeline._prepare_noise_latents(self.frames, height, width, pipeline.vae_config.z_dim, dtype)
        grid_t, h_lat, w_lat = latents.shape[1:4]
        patch = pipeline.vae_config.patch_size
        h_p, w_p = (h_lat + patch - 1) // patch, (w_lat + patch - 1) // patch
        spatial = h_p * w_p

        encoded = pipeline._encode_conditioning_video(control, self.frames, height, width)
        control_tokens = pipeline._patchify_latents(encoded[:, :grid_t, :h_lat, :w_lat, :].astype(dtype)).astype(dtype)
        conditioned, pin, keep = 0, None, None
        if previous is not None:
            conditioned = latent_frames(len(previous))
            pin = pipeline._encode_conditioning_video(previous, self.frames, height, width)[:, :grid_t, :h_lat, :w_lat, :].astype(dtype)
            keep = mx.array([1.0] * conditioned + [0.0] * (grid_t - conditioned), dtype=dtype).reshape(1, grid_t, 1, 1, 1)
            latents = keep * pin + (1 - keep) * latents
        mx.eval(control_tokens, latents)

        cond_ids = self.tokens(prompt)
        uncond_ids = self.tokens(pipeline._negative_prompt_text or "")
        cond_target = pipeline._build_position_ids(cond_ids.shape[1], grid_t, h_p, w_p)
        uncond_target = pipeline._build_position_ids(uncond_ids.shape[1], grid_t, h_p, w_p)
        cond_full, uncond_full = pack_positions(cond_target, cond_ids.shape[1]), pack_positions(uncond_target, uncond_ids.shape[1])
        full_mask = noisy_mask(grid_t, spatial, conditioned, True).astype(dtype)
        target_mask = noisy_mask(grid_t, spatial, conditioned, False).astype(dtype)
        scheduler = UniPCScheduler()
        scheduler.set_timesteps(self.steps)
        cond_cache = uncond_cache = None
        count = grid_t * spatial

        for index in range(self.steps):
            sigma = float(scheduler.sigmas[index].item())
            step_time = mx.array([sigma * scheduler.num_train_timesteps]).astype(dtype)
            target = pipeline._patchify_latents(latents).astype(dtype)
            full = mx.concatenate([control_tokens, target], axis=1)
            if cond_cache is None:
                with_control, cond_cache = self.first_pass(cond_ids, full, step_time, full_mask, cond_full)
                negative, uncond_cache = self.first_pass(uncond_ids, full, step_time, full_mask, uncond_full)
            else:
                with_control = self.cached_pass(cond_cache, cond_ids.shape[1], full, step_time, full_mask, cond_full)
                negative = self.cached_pass(uncond_cache, uncond_ids.shape[1], full, step_time, full_mask, uncond_full)
            without = None
            if self.control_guidance != 1.0:
                without = self.cached_pass(cond_cache, cond_ids.shape[1], target, step_time, target_mask, cond_target)
            # The model also predicts the control tokens. Only the target's are used.
            patches = guided(with_control[:, -count:], without, negative[:, -count:], self.guidance, self.control_guidance)
            velocity = pipeline._unpatchify_latents(patches, grid_t, h_p, w_p, h_orig=h_lat, w_orig=w_lat)
            if keep is not None:
                velocity = velocity * (1 - keep)
            latents = scheduler.step(velocity, step_time, latents)
            if keep is not None:  # The solver looks at past steps, so pin these exactly rather than trust a zero velocity.
                latents = keep * pin + (1 - keep) * latents
            mx.eval(latents)

        del cond_cache, uncond_cache
        mx.clear_cache()
        video = decode_latents(latents, str(self.model_dir / "vae"))
        mx.eval(video)
        return (np.array(video[0].astype(mx.float32)) * 255).clip(0, 255).astype(np.uint8)


def read_video(path, width, height):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt")
    parser.add_argument("--control", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir", default=str(Path(__file__).resolve().parents[2] / "models" / "Cosmos3-Nano"))
    parser.add_argument("--size", default="448x256")
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument("--cond-frames", type=int, default=5)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--chunks", type=int)
    parser.add_argument("--guidance", type=float, default=GUIDANCE)
    parser.add_argument("--control-guidance", type=float, default=CONTROL_GUIDANCE)
    args = parser.parse_args()
    from cosmos3_mlx.pipeline import save_video

    width, height = (int(n) for n in args.size.split("x"))
    control = read_video(args.control, width, height)
    windows = chunk_windows(len(control), args.frames, args.cond_frames)[:args.chunks]
    mx.set_default_device(mx.gpu)
    painter = Painter(args.model_dir, (width, height), args.frames, args.steps, args.guidance, args.control_guidance)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    painted, previous = [], None
    for number, (start, end) in enumerate(windows):
        clock = time.time()
        chunk = painter.paint(args.prompt, control[start:end], previous, args.seed)[:args.frames]
        painted.append(chunk if previous is None else chunk[args.cond_frames:])
        previous = chunk[-args.cond_frames:] if args.cond_frames else None
        # Saved after every chunk, so a run stopped early still has everything so far.
        save_video(np.concatenate(painted), str(output), fps=24)
        print(json.dumps({"chunk": number, "start": start, "end": end, "seconds": round(time.time() - clock, 1),
                          "frames": sum(map(len, painted)), "peak_gb": round(mx.get_peak_memory() / 1024 ** 3, 2)}), flush=True)


if __name__ == "__main__":
    main()
