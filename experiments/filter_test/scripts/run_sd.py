"""SD1.5 + DMD (one step) + depth ControlNet over test_clip, frame by frame, on the Mac's GPU (MPS). Experiments 2 and 3.

    experiments/filter_test/.venv/bin/python experiments/filter_test/scripts/run_sd.py --depth sim   # the sim's own depth (controls.py)
    experiments/filter_test/.venv/bin/python experiments/filter_test/scripts/run_sd.py --depth da    # DepthAnythingV2 on the sim's rgb, the repo's way

Settings are the repo's workflow.json (yondonfu/ComfyUI-Real-Time-SD1.5-DMD-Depth-ControlNet): Dreamshaper 8's text encoder
and VAE config, the dreamshaper-8-dmd-1kstep UNet, sampler "lcm" for 1 step, cfg 1 (no negative branch), ControlNet
control_v11f1p_sd15_depth at strength 1 from 0 to 1, TAESD to decode, empty negative prompt. What differs, because the repo
targets an NVIDIA GPU: no TensorRT or fp8 (plain diffusers in fp16 on MPS), DepthAnythingV2 Small through transformers instead of
a TensorRT engine, and 912x512 (16:9 at its native short side) instead of 512x512. The workflow randomizes its seed per run;
for a video every frame here starts from the same noise, so changes between frames come from the control, not the seed.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from diffusers import AutoencoderTiny, ControlNetModel, LCMScheduler, StableDiffusionControlNetPipeline, UNet2DConditionModel
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
CLIP = ROOT / "out" / "filter_test" / "test_clip"
CONTROLS = ROOT / "out" / "filter_test" / "controls"
SIZE = (912, 512)
PROMPT = (ROOT / "experiments" / "filter_test" / "prompt.txt").read_text().strip()
REVISIONS = {"unet": "ZeqiangLai/dreamshaper-8-dmd-1kstep", "base": "Lykon/dreamshaper-8", "controlnet": "lllyasviel/control_v11f1p_sd15_depth",
             "vae": "madebyollin/taesd", "depth": "depth-anything/Depth-Anything-V2-Small-hf"}


def da_controls(frames, device):
    """DepthAnythingV2 Small on each rgb frame, min-max per frame, near bright: what the repo's depth node feeds its ControlNet."""
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    processor = AutoImageProcessor.from_pretrained(REVISIONS["depth"])
    model = AutoModelForDepthEstimation.from_pretrained(REVISIONS["depth"]).to(device).eval()
    out = CONTROLS / "sd15_dadepth"
    out.mkdir(parents=True, exist_ok=True)
    controls = []
    for k, path in enumerate(frames):
        image = Image.open(path).convert("RGB")
        with torch.no_grad():
            predicted = model(**processor(images=image, return_tensors="pt").to(device)).predicted_depth
        depth = torch.nn.functional.interpolate(predicted[None], size=SIZE[::-1], mode="bicubic", align_corners=False)[0, 0].cpu().numpy()
        depth = (depth - depth.min()) / max(float(depth.max() - depth.min()), 1e-6)
        grey = np.round(depth * 255).astype(np.uint8)
        cv2.imwrite(str(out / f"{k:04d}.png"), grey)
        controls.append(Image.fromarray(grey).convert("RGB"))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "30", "-i", str(out / "%04d.png"), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "12", str(CONTROLS / "sd15_dadepth.mp4")], check=True)
    del model
    return controls


def pipeline(device, dtype):
    unet = UNet2DConditionModel.from_pretrained(REVISIONS["unet"], torch_dtype=dtype)
    controlnet = ControlNetModel.from_pretrained(REVISIONS["controlnet"], variant="fp16", torch_dtype=dtype)
    vae = AutoencoderTiny.from_pretrained(REVISIONS["vae"], torch_dtype=dtype)
    pipe = StableDiffusionControlNetPipeline.from_pretrained(REVISIONS["base"], unet=unet, controlnet=controlnet, vae=vae, variant="fp16",
                                                             torch_dtype=dtype, safety_checker=None, requires_safety_checker=False)
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    pipe.set_progress_bar_config(disable=True)
    return pipe.to(device)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depth", choices=["sim", "da"], required=True)
    ap.add_argument("--frames", type=int, help="only the first N frames (a smoke test)")
    ap.add_argument("--device", default="mps")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    device = args.device
    dtype = torch.float16 if device == "mps" else torch.float32
    name = f"sd15_{args.depth}depth"
    out = ROOT / "out" / "filter_test" / name
    frames = sorted((CLIP / "rgb").glob("*.png"))[:args.frames]
    if device == "mps":
        torch.mps.reset_peak_memory_stats() if hasattr(torch.mps, "reset_peak_memory_stats") else None

    started = time.time()
    if args.depth == "da":
        controls = da_controls(frames, device)
    else:
        controls = [Image.open(CONTROLS / name / f"{k:04d}.png").convert("RGB") for k in range(len(frames))]
    depth_s = time.time() - started

    loaded = time.time()
    pipe = pipeline(device, dtype)
    load_s = time.time() - loaded
    (out / "frames").mkdir(parents=True, exist_ok=True)
    shape = (1, 4, SIZE[1] // 8, SIZE[0] // 8)
    noise = torch.randn(shape, generator=torch.Generator("cpu").manual_seed(args.seed), dtype=torch.float32).to(device, dtype)
    seconds = []
    for k, control in enumerate(controls):
        clock = time.time()
        image = pipe(PROMPT, image=control, num_inference_steps=1, guidance_scale=1.0, negative_prompt="",
                     controlnet_conditioning_scale=1.0, control_guidance_start=0.0, control_guidance_end=1.0,
                     latents=noise.clone(), width=SIZE[0], height=SIZE[1]).images[0]
        image.save(out / "frames" / f"{k:04d}.png")
        seconds.append(time.time() - clock)
        if k % 30 == 0:
            print(json.dumps({"frame": k, "seconds": round(seconds[-1], 3)}), flush=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "30", "-i", str(out / "frames" / "%04d.png"), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "16", str(out / "output.mp4")], check=True)
    peak = torch.mps.driver_allocated_memory() / 2 ** 30 if device == "mps" else None
    total = time.time() - started
    stats = {"frames": len(controls), "total_s": round(total, 1), "depth_s": round(depth_s, 1), "load_s": round(load_s, 1),
             "first_frame_s": round(seconds[0], 3), "mean_frame_s": round(float(np.mean(seconds[1:] or seconds)), 3),
             "output_fps": round(len(controls) / sum(seconds), 2), "mps_allocated_gb": peak and round(peak, 2), "size": list(SIZE),
             "seed": args.seed, "prompt": PROMPT, "revisions": REVISIONS, "device": device}
    (out / "stats.json").write_text(json.dumps(stats, indent=1))
    label = "the sim's own depth" if args.depth == "sim" else "DepthAnythingV2's guess from the sim's rgb"
    (out / "run.json").write_text(json.dumps({"model": "sd15", "about": f"SD1.5 + DMD 1-step + depth ControlNet on {label}.",
                                              "lines": [f"{stats['output_fps']} frames/s on the Mac's GPU, {SIZE[0]}x{SIZE[1]}",
                                                        f"took {total / 60:.1f} min for {len(controls)} frames"]}))
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
