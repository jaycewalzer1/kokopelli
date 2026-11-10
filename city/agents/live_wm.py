"""A life lived inside the world model: the agent sees only what Cosmos3-Nano-Sim-Transfer paints, never the sim.

    .venv/bin/python city/agents/live_wm.py --port 9001 --minutes 5
    .venv/bin/python city/agents/live_wm.py --minutes 5 --size 448x256 --fps 24

How a step goes (live.py's Life, with its eyes replaced):
  1. The sim (SimWorld) holds the truth. It applies the agent's action and advances STEP_S sim-seconds, capturing the
     agent's camera at video rate: RGB, depth and object masks for every frame.
  2. Those become the 4 controls Sim-Transfer reads (blur, seg, depth, edge, equal weights), the same conventions as
     city/wm/controls.py.
  3. One world-model rollout (world_stream.py) paints them, continuing the same causal video since the start of the life.
     The painted frames go into film/; the segments join into one continuous film.
  4. When it's time to decide, Qwen looks at the newest painted frame. The sim's own render is never shown to it.

What the agent is told in words: where it is and what places it knows (memory of its home village), what it heard, what
just happened, and only the people and things within arm's reach / talking distance (you know who's next to you).
Everything farther away it has to see in the picture. live.py instead lists everyone in view from the sim's state.

Qwen and the world model take turns with memory: the world model drops its weights while Qwen decides (its history
stays), and Qwen unloads before painting resumes.
Writes out/city_agents/<run>/ like live.py, plus film/ (painted video), sim/ is deleted step by step (controls are kept
as video in controls/), and wm/ (the worker log).
"""
import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import live  # noqa: E402
from live import HEAR_M, STEP_S, Life, m  # noqa: E402

ROOT = live.ROOT
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "city" / "wm"))
import controls as ctl  # noqa: E402  (city/wm/controls.py)
from core.world_stream import WorldStream  # noqa: E402


class VideoRateSim(live.SimWorldPhysics):
    """The adapter names render files by whole seconds (t0000_rgb.png), so at video rate every frame of a second would
    overwrite the one before. Give each render its own name as soon as it lands."""

    def render(self, modality, offset_s):
        r = super().render(modality, offset_s)
        p = Path(r.path)
        new = p.with_name(f"t{offset_s:09.4f}_{modality}.{r.format}")
        p.replace(new)
        return r.model_copy(update={"path": str(new)})


live.SimWorldPhysics = VideoRateSim   # Life.run opens the sim by this name; only this process is affected

REACH_M = 3.0
NEAR_CM, FAR_CM = 100.0, 20000.0   # fixed inverse-depth scale for a whole life (controls.py scales per clip)
BLUR_DOWNUP = 16                   # blur v2 "high", the variant the user picked for the bridge
WM_PROMPT = ("First-person view of someone walking through a sunny solarpunk village in the afternoon, at eye level. "
             "Timber apartment buildings with planted balconies, vines and green roofs line paved streets and footpaths; "
             "flowering shrubs, fruit trees and community gardens; solar panels and copper domes on the roofs; neighbours "
             "walking, chatting and carrying things; wooded hills on the horizon, deep blue sky with white clouds. "
             "Live-action video, natural light, realistic materials, steady handheld camera.")


class Film:
    """Appends painted frames to numbered mp4 segments and keeps one joined film up to date."""

    def __init__(self, folder, size, fps, name):
        self.dir, self.size, self.fps, self.name = Path(folder), size, fps, name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.segments = []

    def add(self, frames):
        if not len(frames):
            return
        path = self.dir / f"{self.name}_{len(self.segments):04d}.mp4"
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{self.size[0]}x{self.size[1]}",
                              "-r", f"{self.fps:g}", "-i", "-", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(path)],
                             stdin=subprocess.PIPE)
        p.communicate(frames.tobytes())
        self.segments.append(path)
        listing = self.dir / f"{self.name}.txt"
        listing.write_text("".join(f"file '{s.name}'\n" for s in self.segments))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
                        str(self.dir.parent / f"{self.name}.mp4")], check=False)


class WorldModelLife(Life):
    def __init__(self, args):
        super().__init__(args)
        self.size = tuple(int(n) for n in args.size.split("x"))
        fps = args.fps
        tick = 1.0 / (2 * fps)   # the adapter needs a velocity window shorter than the first capture: two ticks per frame
        offsets = tuple(round(k / fps, 9) for k in range(1, int(round(STEP_S * fps)) + 1))
        self.cfg = type(self.cfg)(**{**self.cfg.model_dump(), **dict(   # rebuilt, so the adapter's checks run
            tick_interval_s=tick, velocity_window_s=tick, capture_offsets_s=offsets,
            modalities=("rgb", "depth", "segmentation"))})
        self.palette = ctl.Palette()
        self.film = Film(self.out / "film", self.size, fps, "world_model")
        self.sim_film = Film(self.out / "film", self.size, fps, "sim")
        self.ctl_film = {h: Film(self.out / "controls", self.size, fps, h) for h in ("blur", "seg", "depth", "edge")}
        steps = args.steps
        self.wm = WorldStream(args.wm_prompt, size=args.size, fps=fps, seed=args.seed, window=args.window, sink=args.sink,
                              quantize=args.quantize, planned_frames=int(steps * STEP_S * fps) + 1, out_dir=self.out / "wm")
        self.log("world_model", **{k: v for k, v in self.wm.info.items() if k != "formatted_prompt"},
                 formatted_prompt=self.wm.info["formatted_prompt"], size=args.size, fps=fps, window=args.window, sink=args.sink)
        self.k_seen = 0
        self.timing = []

    # --- perception: sim captures -> controls -> world model -> what the agent sees
    def controls_for(self, captures):
        import numpy as np
        out = {h: [] for h in ("blur", "seg", "depth", "edge")}
        rgbs = []
        for cap in captures:
            rgb = np.array(ctl.Image.open(cap.renders["rgb"].path).convert("RGB"))
            small = ctl.resize_rgb(rgb, self.size)
            depth = np.load(cap.renders["depth"].path).astype(np.float32)
            seg = np.array(ctl.Image.open(cap.renders["segmentation"].path).convert("RGB"))
            ids = ctl.refined_ids(seg, rgb)
            seg_small = ctl.cv2.resize(self.palette.paint(ids), self.size, interpolation=ctl.cv2.INTER_NEAREST)
            out["blur"].append(ctl.blur(small, downup=BLUR_DOWNUP)[0])
            out["seg"].append(seg_small)
            out["depth"].append(ctl.depth_inverse_frame(depth, NEAR_CM, FAR_CM, self.size))
            out["edge"].append(ctl.edge(small))
            rgbs.append(small)
        return {h: np.stack(v) for h, v in out.items()}, np.stack(rgbs)

    def perceive(self, captures):
        """Paint the new captures, add them to the films, delete the raw captures, return the newest painted frame."""
        import numpy as np
        t0 = time.time()
        controls, rgb = self.controls_for(captures)
        t_ctl = time.time() - t0
        from core import llm_model
        llm_model.unload()               # Qwen out of the way while the world model paints
        painted = self.wm.push(controls)
        self.film.add(painted)
        self.sim_film.add(rgb)
        for h, f in self.ctl_film.items():
            f.add(controls[h])
        for cap in captures:              # raw captures are big (depth .npy); the controls keep what matters
            for r in cap.renders.values():
                Path(r.path).unlink(missing_ok=True)
        stats = dict(self.wm.last, controls_s=round(t_ctl, 1), frames_in=len(rgb), total_s=round(time.time() - t0, 1))
        self.log("painted", **{k: v for k, v in stats.items() if k != "out"})
        if len(painted):
            self.k_seen += 1
            path = self.out / "frames" / f"seen_{self.k_seen:04d}.png"
            ctl.Image.fromarray(painted[-1]).save(path)
            self.seen = str(path)
        return self.seen

    # --- what the agent is told: no sim-derived sight lines beyond arm's reach / talking distance
    def describe(self, state):
        me = m(state.agent.pose.location)
        here = self.nav.place_at(me)
        near = self.nav.place_at(me, 40.0)
        where = (f"at {self.nav.places[here]['name']}" if here else
                 f"out in the streets near {self.nav.places[near]['name']}" if near else "out in the streets")
        lines = [f"Time: {state.time_of_day.clock[:5]}.",
                 f"You are {where}, {state.agent.posture}, carrying {state.agent.held_object or 'nothing'}."]
        if self.route:
            lines.append(f"You are walking to {self.nav.places[self.goal_place]['name']}, "
                         f"{live.rough(self.nav.length(me, self.route))} to go.")
        close = []
        for npc in state.npcs:
            d = math.dist(me, m(npc.pose.location))
            if d <= HEAR_M:
                p = self.cast.people[npc.id]
                close.append(f"- {npc.id}: {p['name']}, {p['role']}, {live.rough(d)} {live.bearing(me, state.agent.pose.rotation.yaw, m(npc.pose.location))}")
        lines.append("Who is right next to you (close enough to talk):\n" + ("\n".join(close) if close else "- nobody"))
        reach = [f"- {o.id}" for o in state.objects if o.pose and not o.held_by and math.dist(me, m(o.pose.location)) <= REACH_M]
        if reach:
            lines.append("Within arm's reach:\n" + "\n".join(reach))
        lines.append("Anyone or anything farther away, you only know from what you see in the picture.")
        ranked = sorted(self.nav.places.items(), key=lambda kv: math.dist(me, self.nav.doors[kv[0]]))
        lines.append("Places you know in the village (nearest first):\n" + "\n".join(
            f"- {pid}: {p['name']} ({p['category'].replace('_', ' ')}), {live.rough(math.dist(me, self.nav.doors[pid]))} "
            f"{live.compass(me, self.nav.doors[pid])}" for pid, p in ranked[:14]))
        return "\n".join(lines)

    def decide(self, state, frame):
        self.wm.release()                 # give the world model's weights back while Qwen thinks
        return super().decide(state, self.seen)

    # --- live.py's _live, with every frame going through the world model
    def _live(self, sim):
        cap = sim.reset(seed=0)
        state = cap.state
        frame = self.perceive([cap])
        self.snapshot(state, frame, 0)
        decide = True
        n_steps = self.args.steps
        for step in range(n_steps):
            t_step = time.time()
            self.sim_t = state.sim_time_s
            if decide:
                thought, act, diary = self.decide(state, frame)
                shutil.copy(frame, self.out / "frames" / f"{step:04d}.png")
                if diary:
                    self.diary.append(f"[{state.time_of_day.clock}] {diary}")
                self.last_thought, self.last_action = thought, act
                self.say(f"\n### {state.time_of_day.clock} — step {step}\n![](frames/{step:04d}.png)\n\n"
                         f"*{thought}*\n\n**→** `{json.dumps(act)}`")
                self.heard = []
                self.recent.append(f"[{state.time_of_day.clock}] " + json.dumps(act))
                sim_action, problem = self.to_sim(act, state)
                self.problem = problem
                if problem:
                    self.last = problem
            else:
                act, self.problem = {"type": "continue"}, None
                sim_action = self.next_leg() if self.new_leg else {"type": "continue"}
            self.log("act", action=act, sim_action=sim_action)
            t_sim = time.time()
            result = sim.step(sim_action)
            t_sim = time.time() - t_sim
            state = result.final_state
            frame = self.perceive(result.captures)
            self.new_leg = False
            decide = self.after(act, sim_action, result, state)
            self.snapshot(state, frame, step + 1)
            self.log("step_time", step=step, sim_s=round(t_sim, 1), total_s=round(time.time() - t_step, 1))
            print(json.dumps({"step": step + 1, "of": n_steps, "sim_s": round(t_sim, 1),
                              "step_s": round(time.time() - t_step, 1), **{k: self.wm.last.get(k) for k in
                              ("latents", "s_per_latent", "peak_gb")}}), flush=True)

    def run(self):
        try:
            super().run()
        finally:
            self.wm.close()
            self.write_sidecar()

    def write_sidecar(self):
        film = self.out / "world_model.mp4"   # Film joins segments one folder up
        meta = {"model": "Cosmos3-Nano-Sim-Transfer", "agent_model": Path(self.args.weights).name,
                "runtime": "world_stream.py (MLX, one causal rollout for the whole life) + city/agents/live_wm.py",
                "controls": {"blur": f"downup {BLUR_DOWNUP} (v2 high)", "seg": "SimWorld masks x material class",
                             "depth": f"inverse depth, near {NEAR_CM} cm, far {FAR_CM} cm", "edge": "Canny 100/200"},
                "weights": self.wm.info.get("weights"), "prompt": self.args.wm_prompt, "size": self.args.size,
                "fps": self.args.fps, "seed": self.args.seed, "steps": 4, "window": self.args.window, "sink": self.args.sink,
                "sim_steps": self.args.steps, "step_seconds": STEP_S, "frames": self.wm.last.get("frames_out") if hasattr(self.wm, "last") else 0,
                "who": self.args.who, "situation": self.args.situation}
        if film.exists():
            film.with_name(film.name + ".json").write_text(json.dumps(meta, indent=1))
        (self.out / "run.json").write_text(json.dumps(meta, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--minutes", type=float, default=5.0, help="sim-minutes to live")
    ap.add_argument("--who", default=live.DEFAULT_WHO)
    ap.add_argument("--situation", default=live.DEFAULT_SITUATION)
    ap.add_argument("--clock", default="14:00")
    ap.add_argument("--speed", type=float, default=1.6)
    ap.add_argument("--follow", action="store_true")
    ap.add_argument("--weights", default=str(ROOT / "models" / "Qwen3-VL-8B-Instruct-4bit"))
    ap.add_argument("--size", default="448x256", help="world-model canvas; 832x480 is the trained one, ~3x slower")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--window", type=int, default=24, help="world-model history in latents (4 frames each)")
    ap.add_argument("--sink", type=int, default=1)
    ap.add_argument("--quantize", type=int, choices=(4, 8))
    ap.add_argument("--wm-prompt", default=WM_PROMPT)
    args = ap.parse_args()
    args.steps = max(1, int(round(args.minutes * 60 / STEP_S)))
    args.vision = "unreal"   # Life's own vision hook stays a pass-through; perceive() does the world model
    life = WorldModelLife(args)
    life.run()


if __name__ == "__main__":
    main()
