"""Every number a run depends on. Saved with the run, so a resume uses the same ones."""
from dataclasses import asdict, dataclass, field

# Frames per chunk within one tick. 24 fps video shares cond_frames between chunks, so "full" is a real 30 seconds.
WM_PRESETS = {
    "mock": {"size": "448x256", "chunk_frames": [24, 24], "steps": 0},
    "demo": {"size": "448x256", "chunk_frames": [16], "steps": 30},
    "tiny": {"size": "256x256", "chunk_frames": [16], "steps": 20},
    # Sizes and frame counts the model README lists. Each chunk shares one frame, so 4 x 180 + 1 is 30 seconds at 24 fps.
    "gpu_demo": {"size": "832x480", "chunk_frames": [81], "steps": 35},
    "gpu_full": {"size": "832x480", "chunk_frames": [181] * 4, "steps": 35},
    "full": {"size": "448x256", "chunk_frames": [84] * 8 + [88], "steps": 30},
}


@dataclass
class Config:
    seed: int = 7
    ticks: int = 5
    sim: str = "mock"
    wm: str = "mock"
    agent: str = "mock"
    context: str = "mock"
    start_time: str | None = None
    life_db: str | None = None
    life_run: int = 2
    agent_url: str | None = None
    agent_model: str = "Qwen/Qwen3-VL-8B-Instruct"
    agent_weights: str | None = None
    mind: bool = False
    wm_quantize: int = 0
    wm_url: str | None = None

    tick_seconds: int = 30
    check_every: int = 15
    reanchor_every: int = 60
    drift_threshold: float = 0.45
    drift_control: bool = True
    cond_frames: int = 5
    agent_frames: int = 6
    notes_shown: int = 5
    counterfactual: bool = True

    wm_preset: str = "mock"
    wm_style: str = "A steady view of the scene, natural light, continuous motion."
    gpu_dollars_per_hour: float = 0.0
    sim_settings: dict = field(default_factory=dict)

    @property
    def wm_settings(self):
        return WM_PRESETS[self.wm_preset]

    @property
    def capture_offsets(self):
        return list(range(self.check_every, self.tick_seconds + 1, self.check_every))

    def to_dict(self):
        return asdict(self)
