"""Which models this repo uses and where they live."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

WORLD_MODEL = "nvidia/Cosmos3-Nano"
LLM_MODEL = "Qwen/Qwen3-VL-8B-Instruct"

WORLD_MODEL_WEIGHTS = ROOT / "models" / WORLD_MODEL.split("/")[1]
WORLD_MODEL_RUNNER = Path.home() / "cosmos3" / "cosmos3-mlx"
LLM_MODEL_WEIGHTS = ROOT / "models" / LLM_MODEL.split("/")[1]
