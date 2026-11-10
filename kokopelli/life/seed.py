"""The input to a life. The hidden target lives only on LifeSeed, so a PublicSeed cannot leak it."""
import random
from dataclasses import asdict, dataclass, field
from datetime import date


def rng(*parts):
    """A random stream named by its parts, so one node's draws never shift another's."""
    return random.Random(":".join(str(part) for part in parts))


@dataclass(frozen=True)
class PublicSeed:
    prompt: str
    birth_date: date
    place: str = ""
    era: str = ""
    family: tuple = ()
    temperament: str = ""
    anchors: tuple = ()
    rng_seed: int = 0

    def to_dict(self):
        return {**asdict(self), "birth_date": self.birth_date.isoformat()}

    @classmethod
    def from_dict(cls, data):
        return cls(data["prompt"], date.fromisoformat(data["birth_date"]), data["place"], data["era"],
                   tuple(data["family"]), data["temperament"], tuple(data["anchors"]), data["rng_seed"])


@dataclass(frozen=True)
class LifeSeed(PublicSeed):
    hidden_target: str = field(default=None, repr=False)

    def public(self):
        return PublicSeed(self.prompt, self.birth_date, self.place, self.era, self.family,
                          self.temperament, self.anchors, self.rng_seed)
