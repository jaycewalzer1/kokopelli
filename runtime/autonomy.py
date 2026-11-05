"""How much the agent changed things. A null agent lives the same stretch; the gap is what the agent itself did."""
import math
import tempfile


def counterfactual(sim_factory, config, start, agent_track):
    """Re-run the sim alone with an agent that always waits, and compare it tick by tick. No world model is involved."""
    sim = sim_factory()
    with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
        sim.reset(config.seed, start, folder, config.capture_offsets)
        rows = []
        for item in agent_track:
            null_state = sim.step({"type": "wait"}, item["tick"], render=False).state
            null_objects = {name: value["state"] for name, value in null_state["objects"].items()}
            rows.append({"tick": item["tick"], "distance": round(math.dist(item["pos"], null_state["agent"]["pos"]), 3),
                         "objects_changed": sum(item["objects"][name] != state for name, state in null_objects.items())})
    sim.close()
    return {"null_agent": "wait", "per_tick": rows, "final_distance": rows[-1]["distance"] if rows else 0,
            "max_distance": max((row["distance"] for row in rows), default=0),
            "objects_changed_at_end": rows[-1]["objects_changed"] if rows else 0}
