"""Fetch every weight file the Mac filter test uses into the Hugging Face cache, and NVIDIA's depth example for checking the encoding.

    filter_test/.venv/bin/python filter_test/scripts/download.py
"""
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

ROOT = Path(__file__).resolve().parents[2]
WANT = [
    ("ZeqiangLai/dreamshaper-8-dmd-1kstep", None),  # the one-step DMD UNet (what aaronb/... now redirects to)
    ("Lykon/dreamshaper-8", ["model_index.json", "scheduler/*", "text_encoder/config.json", "text_encoder/model.fp16.safetensors",
                             "tokenizer/*", "vae/config.json", "vae/diffusion_pytorch_model.fp16.safetensors", "feature_extractor/*"]),
    ("lllyasviel/control_v11f1p_sd15_depth", ["config.json", "diffusion_pytorch_model.fp16.safetensors"]),
    ("madebyollin/taesd", ["config.json", "diffusion_pytorch_model.safetensors"]),
    ("depth-anything/Depth-Anything-V2-Small-hf", None),
]

for repo, patterns in WANT:
    print(repo, snapshot_download(repo, allow_patterns=patterns), flush=True)
examples = ROOT / "out" / "filter_test" / "reference" / "cosmos_example1"
for name in ("example1.mp4", "example1_depth.mp4", "example1_upsampled_prompt.json"):
    print(hf_hub_download("nvidia/Cosmos3-Nano-Sim-Transfer", f"assets/sample_data/example1/{name}", local_dir=examples), flush=True)
