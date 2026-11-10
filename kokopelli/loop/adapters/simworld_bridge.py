"""Connects the loop to SimWorld. The loop speaks small dicts in metres, and the adapter speaks PhysicalState in centimetres."""
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from kokopelli.loop.interfaces import Capture, PhysicsSim, SimStep
from kokopelli.loop.physics import SimCheckpoint

CM_PER_METRE = 100


def _position(pose):
    return [round(pose.location.x / CM_PER_METRE, 2), round(pose.location.y / CM_PER_METRE, 2)]


def _weather_text(weather):
    if not weather.available:
        return "weather unknown"
    return "foggy" if weather.fog_density else "clear"


def describe_state(state, start_time):
    """PhysicalState in the loop's shape, with the original kept whole under "raw" for the log."""
    moment = datetime.fromisoformat(start_time) + timedelta(seconds=state.sim_time_s)
    agent = state.agent
    objects = {}
    for item in state.objects:
        if not item.present:
            continue
        where = _position(item.pose) if item.pose else _position(agent.pose)
        objects[item.id] = {"pos": where, "state": f"held by {item.held_by}" if item.held_by else item.kind}
    return {"tick": state.tick_count, "sim_time": moment.isoformat(), "time_of_day": state.time_of_day.clock,
            "weather": _weather_text(state.weather),
            "agent": {"pos": _position(agent.pose), "facing": f"{agent.pose.rotation.yaw:.0f} degrees",
                      "velocity": [agent.velocity.speed_cm_s / CM_PER_METRE], "holding": agent.held_object},
            "npcs": {npc.id: {"pos": _position(npc.pose)} for npc in state.npcs}, "objects": objects,
            "raw": state.model_dump(mode="json")}


def visible_ids(state):
    return [*(npc.id for npc in state.npcs), *(item.id for item in state.objects if item.present)]


def to_sim_action(action):
    """The loop names targets as "target"; SimWorld calls them target_id."""
    if "target" not in action:
        return dict(action)
    return {"type": action["type"], "target_id": action["target"]}


def to_capture(capture):
    renders = capture.renders
    # Filter mode captures between whole seconds, and those offsets have to stay distinct.
    offset = int(capture.offset_s) if capture.offset_s == int(capture.offset_s) else capture.offset_s
    return Capture(offset, renders["rgb"].path, renders["depth"].path, renders["segmentation"].path,
                   {name: render.sha256[:16] for name, render in renders.items()})


class SimWorldSim(PhysicsSim):
    def __init__(self, settings):
        self.settings, self.physics, self.start_time = dict(settings), None, None

    def reset(self, seed, start_time, out_dir, capture_offsets):
        from kokopelli.loop.adapters.simworld import SimWorldConfig, SimWorldPhysics  # Needs unrealcv, which mock runs don't.

        self.close()
        self.start_time = start_time
        config = SimWorldConfig(**{"start_time": datetime.fromisoformat(start_time).strftime("%H:%M"), **self.settings},
                                out_dir=str(Path(out_dir).resolve()), capture_offsets_s=tuple(float(offset) for offset in capture_offsets))
        self.physics = SimWorldPhysics(config)
        first = self.physics.reset(seed)
        return SimStep(describe_state(first.state, start_time), [to_capture(first)], visible_ids(first.state))

    def step(self, action, tick, render=True):
        try:
            result, rejected = self.physics.step(to_sim_action(action)), None
        except ValidationError as error:
            # Something the agent can see but can't do, like interacting with a person. The turn is lost, not the run.
            result, rejected = self.physics.step({"type": "wait"}), str(error.errors()[0]["msg"])
        state = describe_state(result.final_state, self.start_time)
        state["last_result"] = {"action": action["type"], "ok": rejected is None and result.outcome.status != "failed",
                                "rejected": rejected, "outcome": result.outcome.model_dump(mode="json"),
                                "speech": [event.model_dump(mode="json") for event in result.speech_events]}
        return SimStep(state, [to_capture(capture) for capture in result.captures], visible_ids(result.final_state),
                       result.timing.model_dump(mode="json"))

    def get_state(self):
        return self.physics.get_state().model_dump(mode="json")

    def restore_state(self, state):
        return self.physics.restore_state(SimCheckpoint.model_validate(state))

    def close(self):
        if self.physics:
            self.physics.close()
            self.physics = None


def make_simworld(config):
    return SimWorldSim(config.sim_settings)
