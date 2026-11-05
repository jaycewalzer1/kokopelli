"""One tick, in the order the plan gives: sim, prompt, world model, drift, agent, log, checkpoint."""
import shutil
import time
from pathlib import Path

from runtime import checkpoint, drift
from runtime.actions import InvalidDecision, action_dict, parse_decision
from runtime.frames import evenly_spaced, file_hash, read_clip, save_rgb
from runtime.interfaces import AgentInput, ChunkRequest, CondFrame
from runtime.leak_guard import LeakError, drop_future
from runtime.prompt_builder import build_agent_prompt, build_wm_prompt


def text_hash(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class Loop:
    def __init__(self, config, out_dir, sim, world_model, agent, context, log):
        self.config, self.out = config, Path(out_dir)
        self.sim, self.world_model, self.agent, self.context, self.log = sim, world_model, agent, context, log
        self.next_tick = 1
        self.pending = {"type": "wait"}
        self.notes = []
        self.cond = []
        self.since_anchor = 0
        self.visible = []

    def _rel(self, path):
        return str(Path(path).resolve().relative_to(self.out.resolve()))

    def start(self):
        start = self.config.start_time or self.context.start_time()
        first = self.sim.reset(self.config.seed, start, self.out, self.config.capture_offsets)
        self.cond = [CondFrame(first.captures[0].rgb, "sim")]
        self.visible = first.visible
        self.log.append("sim_reset", 0, {"state": first.state, "capture": self._capture_data(first.captures[0]), "visible": first.visible})

    def resume(self, saved):
        self.next_tick = saved["next_tick"]
        self.pending, self.notes, self.since_anchor, self.visible = saved["pending"], saved["notes"], saved["since_anchor"], saved["visible"]
        self.cond = [CondFrame(str(self.out / frame["path"]), frame["source"]) for frame in saved["cond"]]
        start = self.config.start_time or self.context.start_time()
        self.sim.reset(self.config.seed, start, self.out, self.config.capture_offsets)
        self.sim.restore_state(saved["sim_state"])
        self.world_model.set_state(saved["wm_state"])
        self.log.append("resume", None, {"from_tick": self.next_tick, "log_offset": saved["log_offset"]})

    def run(self):
        while self.next_tick <= self.config.ticks:
            self.tick(self.next_tick)
            self.next_tick += 1

    def tick(self, tick):
        started = time.perf_counter()
        seconds = {}
        self.log.append("tick_start", tick, {"action_applied": self.pending})

        clock = time.perf_counter()
        step = self.sim.step(self.pending, tick)
        seconds["sim"] = time.perf_counter() - clock
        now = step.state["sim_time"]
        self.visible = step.visible
        self.log.append("sim_step", tick, {"state": step.state, "captures": [self._capture_data(c) for c in step.captures],
                                           "visible": step.visible, "seconds": step.seconds})

        clock = time.perf_counter()
        context = self._guarded(tick, now, self.context.context_at, now)
        prompt, _ = self._guarded(tick, now, build_wm_prompt, context, step.state, self.pending, self.config.wm_style, now)
        seconds["prompt"] = time.perf_counter() - clock
        self.log.append("wm_prompt", tick, {"text": prompt, "hash": text_hash(prompt), "context": context, "now": now,
                                            "dropped_future": context["dropped"], "leak_check": "passed",
                                            "cond": [self._cond_data(frame) for frame in self.cond]})

        clock = time.perf_counter()
        self.agent.release()
        sampled = self._render(tick, prompt, step, seconds)
        seconds["wm"] = time.perf_counter() - clock - seconds["drift"]

        clock = time.perf_counter()
        decision = self._decide(tick, now, context, sampled)
        seconds["agent"] = time.perf_counter() - clock

        self._score_autonomy(tick, now, decision)
        self.pending = action_dict(decision.action)

        clock = time.perf_counter()
        self._checkpoint(tick, step)
        seconds["checkpoint"] = time.perf_counter() - clock
        seconds["total"] = time.perf_counter() - started
        compute = seconds["sim"] + seconds["wm"] + seconds["agent"]
        self.log.append("tick_end", tick, {"seconds": {key: round(value, 4) for key, value in seconds.items()},
                                           "cost_usd": round(compute / 3600 * self.config.gpu_dollars_per_hour, 6)})

    def _guarded(self, tick, now, function, *args):
        """A leak ends the run on purpose. It goes in the log first, so the panel can show the alarm."""
        try:
            return function(*args)
        except LeakError as error:
            self.log.append("leak_alarm", tick, {"error": str(error), "now": now})
            raise

    def _render(self, tick, prompt, step, seconds):
        settings = self.config.wm_settings
        chunks = settings["chunk_frames"]
        chunk_seconds = self.config.tick_seconds / len(chunks)
        per_chunk = max(1, round(self.config.agent_frames / len(chunks)))
        sampled = []
        seconds["drift"] = 0.0
        for index, frames in enumerate(chunks):
            elapsed = round((index + 1) * chunk_seconds, 6)
            target = next(c for c in step.captures if c.offset_s >= elapsed or c is step.captures[-1])
            output = self.out / "ticks" / f"{tick:04d}" / f"wm_{index:02d}.mp4"
            request = ChunkRequest(prompt, self.cond, target, str(output), tick, index, frames, self.config.seed)
            clock = time.perf_counter()
            self.world_model.render_chunk(request)
            render_seconds = time.perf_counter() - clock
            video = read_clip(output)
            folder = output.parent
            sampled += [save_rgb(video[i], folder / f"wm_{index:02d}_sample_{i:03d}.png") for i in evenly_spaced(len(video), per_chunk)]
            count = min(self.config.cond_frames, len(video))
            self.cond = [CondFrame(save_rgb(video[len(video) - count + i], folder / f"wm_{index:02d}_tail_{i}.png"), "wm") for i in range(count)]
            self.log.append("wm_chunk", tick, {"chunk": index, "clip": self._rel(output), "hash": file_hash(output), "frames": len(video),
                                               "seconds": round(render_seconds, 4), "seed": self.config.seed,
                                               "samples": [self._rel(path) for path in sampled[-per_chunk:]]})
            self.since_anchor += chunk_seconds
            check_every = self.config.check_every
            if int(elapsed // check_every) > int(round(elapsed - chunk_seconds, 6) // check_every):
                clock = time.perf_counter()
                self._check_drift(tick, elapsed, step)
                seconds["drift"] += time.perf_counter() - clock
        return [sampled[i] for i in evenly_spaced(len(sampled), self.config.agent_frames)]

    def _check_drift(self, tick, elapsed, step):
        offset = int(elapsed // self.config.check_every) * self.config.check_every
        capture = next(c for c in step.captures if c.offset_s == offset)
        scores = drift.score(self.cond[-1].path, capture.rgb)
        reason = drift.reanchor_reason(scores["score"], self.since_anchor, self.config)
        self.log.append("drift_check", tick, {"offset_s": offset, **scores, "threshold": self.config.drift_threshold,
                                              "seconds_since_anchor": self.since_anchor, "reanchor": reason})
        if reason:
            frame = self.out / "ticks" / f"{tick:04d}" / f"anchor_{offset:02d}.png"
            shutil.copyfile(capture.rgb, frame)
            self.cond = drift.anchored(self.cond, str(frame), CondFrame)
            self.since_anchor = 0
            self.log.append("reanchor", tick, {"offset_s": offset, "reason": reason, "frame": self._rel(frame),
                                               "replaced": "oldest", "cond": [self._cond_data(item) for item in self.cond]})

    def _decide(self, tick, now, context, images):
        notes, _ = drop_future(self.notes, now)
        notes = notes[-self.config.notes_shown:]
        prompt, _ = self._guarded(tick, now, build_agent_prompt, context, notes, self.visible, len(images), now)
        self.log.append("agent_input", tick, {"prompt": prompt, "hash": text_hash(prompt), "images": [self._rel(p) for p in images],
                                              "image_hashes": [file_hash(p) for p in images], "notes": notes, "leak_check": "passed"})
        error = None
        for attempt in (1, 2):
            clock = time.perf_counter()
            raw = self.agent.decide(AgentInput(prompt, images, self.visible, now, tick, error))
            latency = round(time.perf_counter() - clock, 4)
            try:
                decision = parse_decision(raw, self.visible)
                self.log.append("agent_output", tick, {"attempt": attempt, "raw": raw, "valid": True, "seconds": latency})
                break
            except InvalidDecision as invalid:
                error = str(invalid)
                self.log.append("agent_output", tick, {"attempt": attempt, "raw": raw, "valid": False, "error": error, "seconds": latency})
        else:
            # Two bad replies. The agent loses its turn rather than the run stopping.
            decision = parse_decision('{"action": {"type": "wait"}}', self.visible)
            self.log.append("agent_fallback", tick, {"action": "wait", "reason": error})
        if decision.diary:
            self.notes.append({"t": now, "text": decision.diary})
        self.log.append("decision", tick, {"action": action_dict(decision.action), "diary": decision.diary})
        return decision

    def _score_autonomy(self, tick, now, decision):
        default = self.context.default_action(now)
        action = action_dict(decision.action)
        self.log.append("autonomy", tick, {"action": action["type"], "default": default["type"], "default_source": default["source"],
                                           "differs": action["type"] != default["type"]})

    def _checkpoint(self, tick, step):
        offset = self.log.offset()
        checkpoint.save(self.out, {"next_tick": tick + 1, "pending": self.pending, "notes": self.notes, "since_anchor": self.since_anchor,
                                   "visible": self.visible, "cond": [self._cond_data(frame) for frame in self.cond],
                                   "sim_state": self.sim.get_state(), "wm_state": self.world_model.get_state(),
                                   "log_offset": offset, "seed": self.config.seed})
        self.log.append("checkpoint", tick, {"next_tick": tick + 1, "log_offset": offset})

    def _capture_data(self, capture):
        return {"offset_s": capture.offset_s, "rgb": self._rel(capture.rgb), "depth": self._rel(capture.depth),
                "seg": self._rel(capture.seg), "hashes": capture.hashes}

    def _cond_data(self, frame):
        return {"path": self._rel(frame.path), "source": frame.source}
