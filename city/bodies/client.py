"""Ask the server which body a person wears: `vbp <actor> SetBody <id>` / `vbp <actor> GetBody` (city/bodies/PLAN.md).

    from city.bodies.client import set_body, dress
    result = set_body(sim.wire, "GEN_BP_Humanoid_0", "mara")      # -> BodyResult(ok=True, body="mara", ...)
    results = dress(sim.wire, {"GEN_BP_Humanoid_0": "mara", "GEN_BP_Humanoid_1": "iris"})

`wire` is anything with `.request(command)`: the wm-agent-loop adapter's `sim.wire` (raises CommandError on an
"error ..." reply) or a bare `unrealcv.Client` (returns the error string). Both are handled the same way.

A body is a nicety, never a reason to stop a run. Nothing here raises for a server-side problem: an old server
without the command, a missing asset or a lost link all come back as `BodyResult(ok=False, error=...)`, and the
caller logs a warning and carries on with whatever body the server gave the actor (its Bodies.json mapping, or the
placeholder).

Replies the server may send (PLAN.md "Interface"):
    {"ok": true, "body": "mara"}                         SetBody worked (body may differ from the one asked for when
                                                         the server fell back, e.g. to "manny")
    {"ok": false, "error": "missing asset /Game/..."}    or the plain "error ..." string UnrealCV uses
    {"ok": true, "body": "mara"} / {"body": "mara"} / mara    GetBody
    {"ok": true, "body": "mara", "tier": "near"}         GetBody since the near/far plan: "near" = the high-quality
                                                         MetaHuman, "far" = the Low export of the same person,
                                                         "fallback" = the mannequin because the body failed to load.
                                                         Optional; older replies lack it.
"""
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
BODIES_JSON = ROOT / "mac_server" / "Config" / "Bodies.json"

# The ids planned before Bodies.json exists: a body is named after the person who wears it (the two agents and the
# five residents in npcs.json; kai may map to a fallback server-side if no child body is made), plus the stand-in.
PLANNED_BODIES = ("mara", "iris", "ana", "tomas", "wen", "priya", "kai", "manny")

# How an UnrealCV server says it has no such blueprint function (real SimCV and mac_server/tests/mock_server.py).
TIERS = ("near", "far", "fallback")

NO_COMMAND = re.compile(r"does not implement|can ?not find (a )?(function|handler)|no (such )?function|"
                        r"unknown (blueprint )?function|not a function", re.IGNORECASE)


@dataclass
class BodyResult:
    actor: str
    requested: Optional[str]      # None for GetBody
    ok: bool
    body: Optional[str] = None    # the body the actor actually wears, when the server said
    error: Optional[str] = None
    supported: bool = True        # False: the server doesn't know SetBody/GetBody at all (an old build)
    tier: Optional[str] = None    # "near" | "far" | "fallback" when the server says (GetBody), else None

    @property
    def fell_back(self) -> bool:
        return self.ok and self.requested is not None and self.body is not None and self.body != self.requested

    def as_dict(self) -> dict:
        return {**asdict(self), "fell_back": self.fell_back}


def known_bodies(path=BODIES_JSON) -> Optional[set]:
    """Body ids in the server's Bodies.json, or None while that file doesn't exist yet."""
    path = Path(path)
    if not path.exists():
        return None
    return set(json.loads(path.read_text()).get("bodies", {}))


def parse_reply(actor, requested, raw) -> BodyResult:
    """Turn one server reply (str, bytes, or an exception's text) into a BodyResult."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw if raw is not None else "")
    text = re.sub(r"\s+", " ", text).strip()   # SimCV pads JSON replies with tabs and newlines
    if not text:
        return BodyResult(actor, requested, ok=False, error="empty reply (old server without SetBody?)", supported=False)
    low = text.lower()
    if low.startswith("error") or "-> error" in low:
        # "error ..." from UnrealCV, or the adapter's CommandError: "'vbp X SetBody mara' -> error ..."
        message = text.split("->", 1)[-1].strip()
        return BodyResult(actor, requested, ok=False, error=message, supported=not NO_COMMAND.search(message))
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if re.fullmatch(r"[A-Za-z0-9_\-]+", text):   # GetBody may answer with the bare id
            return BodyResult(actor, requested, ok=True, body=text)
        return BodyResult(actor, requested, ok=False, error=f"unexpected reply: {text[:200]}")
    if not isinstance(data, dict):
        return BodyResult(actor, requested, ok=False, error=f"unexpected reply: {text[:200]}")
    ok = data.get("ok", data.get("Success", "body" in data and "error" not in data))
    ok = ok if isinstance(ok, bool) else str(ok).strip().lower() == "true"
    body = data.get("body") or None
    error = data.get("error") or (None if ok else "the server said no, without a reason")
    tier = data.get("tier") if data.get("tier") in TIERS else None
    return BodyResult(actor, requested, ok=ok, body=body, error=None if ok else str(error), tier=tier)


def _ask(wire, actor, requested, command) -> BodyResult:
    try:
        raw = wire.request(command)
    except Exception as e:   # CommandError carries the server's "error ..." text; a lost link is just a failure here
        return parse_reply(actor, requested, str(e) if "error" in str(e).lower() else f"error {type(e).__name__}: {e}")
    return parse_reply(actor, requested, raw)


def set_body(wire, actor, body_id) -> BodyResult:
    return _ask(wire, actor, body_id, f"vbp {actor} SetBody {body_id}")


def get_body(wire, actor) -> BodyResult:
    return _ask(wire, actor, None, f"vbp {actor} GetBody")


def dress(wire, wants) -> dict:
    """SetBody for each {actor: body_id}; skips actors whose body is empty. Returns {actor: BodyResult}.
    Once the server shows it doesn't know SetBody, the rest are marked the same way without asking again."""
    results, old_server = {}, None
    for actor, body_id in wants.items():
        if not body_id:
            continue
        if old_server:
            results[actor] = BodyResult(actor, body_id, ok=False, error=old_server.error, supported=False)
            continue
        results[actor] = set_body(wire, actor, body_id)
        if not results[actor].supported:
            old_server = results[actor]
    return results


def tiers(wire, actors) -> dict:
    """{actor: "near" | "far" | "fallback" | None} from GetBody: which body each person shows right now. None where the server
    doesn't say (an old build, or one from before the near/far plan). A near/far swap in view is a visible pop
    in the world model's input, so callers log this every step."""
    return {actor: get_body(wire, actor).tier for actor in actors}
