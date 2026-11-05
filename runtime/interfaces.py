"""The five pieces the loop talks to. Mocks and real backends both implement these."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Capture:
    """Ground truth renders from the agent's camera, a number of sim-seconds into a tick."""
    offset_s: int
    rgb: str
    depth: str
    seg: str
    hashes: dict = field(default_factory=dict)


@dataclass
class SimStep:
    state: dict
    captures: list
    visible: list
    seconds: dict = field(default_factory=dict)


@dataclass
class CondFrame:
    """One conditioning frame. source is "wm" or "sim", so a re-anchor is visible in the log."""
    path: str
    source: str


@dataclass
class ChunkRequest:
    prompt: str
    cond: list
    target: Capture
    output: str
    tick: int
    chunk: int
    frames: int
    seed: int


@dataclass
class AgentInput:
    prompt: str
    images: list
    visible: list
    now: str
    tick: int
    retry_error: str | None = None


class PhysicsSim(ABC):
    """The source of truth for physical state. Actions land here, never on the world model."""

    @abstractmethod
    def reset(self, seed, start_time, out_dir, capture_offsets) -> SimStep: ...

    @abstractmethod
    def step(self, action, tick, render=True) -> SimStep: ...

    @abstractmethod
    def get_state(self) -> dict: ...

    @abstractmethod
    def restore_state(self, state) -> None: ...

    def close(self):
        pass


class WorldModel(ABC):
    """A renderer. Its output never changes physical state."""

    @abstractmethod
    def render_chunk(self, request) -> str:
        """Write a clip whose first frames repeat request.cond, and return its path."""

    def get_state(self):
        return {}

    def set_state(self, state):
        pass


class AgentPolicy(ABC):
    @abstractmethod
    def decide(self, agent_input) -> str:
        """Return raw text, which the loop validates against the action schema."""

    def release(self):
        """Free memory before the world model runs, for machines that can't hold both."""


class ContextDB(ABC):
    @abstractmethod
    def context_at(self, now) -> dict:
        """The life tree and world state as of now, with nothing from after it."""

    @abstractmethod
    def default_action(self, now) -> dict:
        """What the tree would have done in this slot. For the autonomy metric; never shown to the agent."""

    def start_time(self):
        return None


class EventLog(ABC):
    @abstractmethod
    def append(self, kind, tick, data) -> dict: ...

    @abstractmethod
    def offset(self) -> int: ...
