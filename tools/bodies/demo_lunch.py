"""Bodies demo: the two-agent lunch (kokopelli/agents/lunch_wm.py, used unchanged) plus what a viewer needs to see the bodies.

    .venv/bin/python tools/bodies/demo_lunch.py --port 9001 --minutes 2 --fake-wm --out out/bodies/demo/runs/sim
    tools/bodies/run_demo_lunch.sh --minutes 2 --fake-wm --out ...       # same, starting the packaged server if needed

Everything lunch_wm.py does still happens (same agents, prompts, world-model streams, films, transcript, run.json).
This wrapper only adds, by subclassing:
  - a director camera: SimCV camera 0 (the level camera, which no agent uses) is placed every capture tick by a small
    shot planner (aerial establishing shot, tracking shots while they walk, a side two-shot when they are close, an
    over-the-shoulder shot of whoever is talking) and rendered lit at --director-size into director/f000000.png ...
  - idle head sway on both agents' eye cameras (head_sway; a still camera makes the world model break up);
  - talking gestures: each spoken line sends `vbp <actor> SetSpeaking <s>` (tools/bodies/ANIMATION.md) at its slot in
    the step; the lines of one step are laid out one after another (speaker, then the reply) so the gestures and the
    captions agree;
  - director/frames.jsonl (one row per director frame: sim time, step, shot, camera, both bodies) and captions.jsonl
    (speaker, text, start/end sim time), which tools/bodies/demo_cut.py turns into the captioned demo films.
The agents never see the director camera. If it fails, the run goes on without it (logged in director/errors.log).
"""
import difflib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "kokopelli" / "agents"))
import lunch_wm as L  # noqa: E402
from lunch_wm import c, FRIEND_ACTOR, AGENT_ACTOR  # noqa: E402

DIRECTOR_CAM = 0
SHOT_MIN_S = 3.0          # hold a shot at least this long before cutting
EYE_CM = 160.0
MAX_WORDS = 24            # a longer line is sent back; two per 10 s step have to fit (words_seconds)
SAME_LINE = 0.6           # difflib ratio from which a line counts as something this person already said
FRIEND_SWAY_PHASE = 2.1   # radians, so the two agents don't sway in sync
BESIDE_M = 3.5            # "approach" is refused this close to the other agent


def head_sway(t, phase=0.0):
    """(pitch, yaw) offset in degrees at film time t. A perfectly still camera makes Cosmos break into a coloured mosaic
    (out/world_stream/still_test: 241 still frames shatter, the same frame with these few pixels of sway stays clean)."""
    tau = 2 * math.pi
    return (0.31 * math.sin(tau * t / 2.3 + 1 + phase) + 0.13 * math.sin(tau * t / 0.9 + phase),
            0.64 * math.sin(tau * t / 3.1 + phase) + 0.26 * math.sin(tau * t / 1.3 + phase))


def words_seconds(text):
    # never shorter than demo_cut.retime keeps the caption up, so the shot labels and the captions name the same speaker
    return max(2.2, min(12.0, max(0.36 * len(text.split()) + 0.8, len(text) / 24.0)))


class DirectorSim(L.TwoBodySim):
    """TwoBodySim + camera 0 as a film camera, and scheduled SetSpeaking."""

    director_dir = None
    director_size = (1280, 720)
    nav = None

    def __init__(self, *a, **kw):
        self.d_frame = 0
        self.d_shot, self.d_shot_since, self.d_cam = None, -1e9, None
        self.d_rows = None
        self.speech_plan = []      # (start_s, end_s, actor, speaker_id, text)
        self.speaking_sent = set()
        self.d_ok = True
        self.d_idx, self.d_checks, self.fov = None, 0, 60.0
        super().__init__(*a, **kw)

    # --- setup
    def _setup_camera(self):
        super()._setup_camera()
        city = [n for n in self._objects() if n.upper().startswith("CITY_")]
        if len(city) < 20:   # lunch_wm never builds the city; run_demo_lunch.sh does (tools/city_build/build_city.py)
            raise RuntimeError(f"the city isn't built on this server ({len(city)} CITY_* actors); "
                               f"run simworld/.venv/bin/python -I tools/city_build/build_city.py --port {self.config.port}")
        self.city_actors = len(city)
        if self.director_dir is None:
            return
        Path(self.director_dir).mkdir(parents=True, exist_ok=True)
        self.d_rows = (Path(self.director_dir) / "frames.jsonl").open("a")
        try:
            w, h = self.director_size
            self.wire.request(c.set_camera_size(DIRECTOR_CAM, w, h), resend=False)
            self.wire.request(c.set_camera_fov(DIRECTOR_CAM, self.fov), resend=False)
        except Exception as e:
            self._d_error(f"setup: {e}")

    def _d_error(self, msg):
        if self.director_dir:
            with (Path(self.director_dir) / "errors.log").open("a") as f:
                f.write(msg + "\n")

    def now_s(self):
        return round(self.tick_count * self.config.tick_interval_s, 6)

    # --- speech
    def plan_speech(self, actor, speaker, text, start_s):
        dur = words_seconds(text)
        self.speech_plan.append((start_s, start_s + dur, actor, speaker, text))
        return start_s + dur

    def _speak_due(self, t):
        for i, (s0, s1, actor, _, _) in enumerate(self.speech_plan):
            if i not in self.speaking_sent and s0 <= t:
                self.speaking_sent.add(i)
                try:
                    self.wire.request(f"vbp {actor} SetSpeaking {max(0.5, s1 - t):.2f}", resend=False)
                except Exception as e:
                    self._d_error(f"SetSpeaking {actor}: {e}")

    def speaking_at(self, t):
        for s0, s1, actor, who, _ in self.speech_plan:
            if s0 <= t < s1:
                return actor, who
        return None, None

    # --- shot planning (cm, Unreal axes; yaw 0 = +x, yaw 90 = +y)
    # Each shot type proposes candidate cameras, best first. A candidate is kept only if a depth render from it shows
    # nothing in front of both people (head or chest), so the camera never ends up inside a tree or behind a wall.
    # The chosen candidate is re-checked every RECHECK frames; if it becomes blocked the next clear one is cut to.
    RECHECK = 12

    @staticmethod
    def _aim(pos, look):
        dx, dy, dz = look[0] - pos[0], look[1] - pos[1], look[2] - pos[2]
        return math.degrees(math.atan2(dz, math.hypot(dx, dy))), math.degrees(math.atan2(dy, dx))

    def _project(self, pos, pitch, yaw, q):
        w, h = self.director_size
        th, ps = math.radians(pitch), math.radians(yaw)
        f = (math.cos(th) * math.cos(ps), math.cos(th) * math.sin(ps), math.sin(th))
        r = (-math.sin(ps), math.cos(ps), 0.0)
        u = (-math.sin(th) * math.cos(ps), -math.sin(th) * math.sin(ps), math.cos(th))
        v = [q[k] - pos[k] for k in range(3)]
        x = sum(v[k] * f[k] for k in range(3))
        if x < 50:
            return None
        foc = (w / 2) / math.tan(math.radians(self.fov / 2))
        px = w / 2 + foc * sum(v[k] * r[k] for k in range(3)) / x
        py = h / 2 - foc * sum(v[k] * u[k] for k in range(3)) / x
        return px, py, x, math.dist(pos, q)

    def _visible(self, pos, look, people):
        """Depth from pos: every person in `people` must show its head or chest unblocked and inside the frame."""
        import io
        import numpy as np
        pitch, yaw = self._aim(pos, look)
        self.wire.request(f"vset /camera/{DIRECTOR_CAM}/location {pos[0]:.1f} {pos[1]:.1f} {pos[2]:.1f}", resend=False)
        self.wire.request(c.set_camera_rotation(DIRECTOR_CAM, round(pitch, 3), round(yaw, 3), 0), resend=False)
        data = self.wire.request(c.render(DIRECTOR_CAM, "depth", "npy"), timeout=self.config.render_timeout_s)
        depth = np.load(io.BytesIO(bytes(data)), allow_pickle=False)
        depth = depth.reshape(depth.shape[0], depth.shape[1], -1)[:, :, 0]
        h, w = depth.shape
        sx, sy = w / self.director_size[0], h / self.director_size[1]
        self.d_checks += 1
        for q in people:
            ok = False
            for dz in (75, 35):
                pr = self._project(pos, pitch, yaw, (q[0], q[1], q[2] + dz))
                if not pr:
                    continue
                px, py, plane, euc = pr
                if not (0.08 * self.director_size[0] < px < 0.92 * self.director_size[0]
                        and 0.06 * self.director_size[1] < py < 0.94 * self.director_size[1]):
                    continue
                i, j = int(py * sy), int(px * sx)
                win = depth[max(0, i - 3):i + 4, max(0, j - 3):j + 4]
                if win.size and float(np.median(win)) >= min(plane, euc) - 90:
                    ok = True
                    break
            if not ok:
                return False
        return True

    def _candidates(self, shot, a, b, A, B):
        d = math.dist(a[:2], b[:2])
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
        out = []   # (pos, look, people)
        if shot in ("establishing", "crane"):
            look = (mid[0], mid[1], mid[2])
            base = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) + 90 if d > 1 else 0
            for r, z in ((1500 + d * 0.5, 1300 + d * 0.3), (1000 + d * 0.4, 1800 + d * 0.3), (500, 2500 + d * 0.3)):
                for k in range(8):
                    ang = math.radians(base + 45 * k)
                    out.append(((mid[0] + r * math.cos(ang), mid[1] + r * math.sin(ang), mid[2] + z), look, [a, b]))
        elif shot.startswith("track_"):
            P, Q = (A, a) if shot == "track_mara" else (B, b)
            yaw0 = P.rotation.yaw
            look = (Q[0] + 250 * math.cos(math.radians(yaw0)), Q[1] + 250 * math.sin(math.radians(yaw0)), Q[2] + 40)
            for back, up in ((420, 230), (330, 200), (550, 400)):
                for off in (0, 25, -25, 50, -50):
                    yr = math.radians(yaw0 + 180 + off)
                    out.append(((Q[0] + back * math.cos(yr), Q[1] + back * math.sin(yr), Q[2] + up), look, [Q]))
            for off in (0, 90, 180, 270):   # high follow
                yr = math.radians(yaw0 + 180 + off)
                out.append(((Q[0] + 500 * math.cos(yr), Q[1] + 500 * math.sin(yr), Q[2] + 900), (Q[0], Q[1], Q[2]), [Q]))
        elif shot in ("ots_mara", "ots_iris"):
            spk, lis = (a, b) if shot == "ots_mara" else (b, a)
            ux, uy = (spk[0] - lis[0]) / max(d, 1), (spk[1] - lis[1]) / max(d, 1)
            px, py = -uy, ux
            look = (spk[0], spk[1], spk[2] + 60)
            for back, side, up in ((110, 55, 75), (110, -55, 75), (170, 70, 85), (170, -70, 85)):
                out.append(((lis[0] - back * ux + side * px, lis[1] - back * uy + side * py, lis[2] + up), look, [spk]))
        if shot == "two_shot" or shot.startswith("ots_"):
            ux, uy = ((b[0] - a[0]) / max(d, 1), (b[1] - a[1]) / max(d, 1)) if d > 1 else (1.0, 0.0)
            px, py = -uy, ux
            look = (mid[0], mid[1], mid[2] + 35)
            for dist, up in ((max(420.0, d * 1.25), 90), (max(320.0, d * 1.0), 80), (max(600.0, d * 1.6), 160)):
                for side in (1, -1):
                    for tilt in (0, 30, -30):
                        ang = math.atan2(side * py, side * px) + math.radians(tilt)
                        out.append(((mid[0] + dist * math.cos(ang), mid[1] + dist * math.sin(ang), mid[2] + up), look, [a, b]))
        return out

    def _plan(self, t):
        A = self._read_pose(AGENT_ACTOR)
        B = self._read_pose(FRIEND_ACTOR)
        a = (A.location.x, A.location.y, A.location.z)
        b = (B.location.x, B.location.y, B.location.z)
        d = math.dist(a[:2], b[:2])
        speaker, who = self.speaking_at(t)
        if t < 6.0:
            want = "establishing"
        elif d > 1500:
            want = "track_mara" if (int(t // 12) % 2 == 0) else "track_iris"
        elif speaker and d < 600 and who in ("mara", "iris"):
            want = f"ots_{who}"
        else:
            want = "two_shot"
        if self.d_shot is not None and want != self.d_shot and (t - self.d_shot_since) < SHOT_MIN_S \
                and not (self.d_shot == "establishing" and t >= 6.0):
            want = self.d_shot
        cands = self._candidates(want, a, b, A, B)
        cut = want != self.d_shot
        idx = self.d_idx if not cut else None
        check = cut or self.d_frame % self.RECHECK == 0 or idx is None
        chosen = None
        if not check and idx is not None and idx < len(cands):
            chosen = idx
        else:
            order = ([idx] if idx is not None and idx < len(cands) else []) + [k for k in range(len(cands)) if k != idx]
            for k in order[:14]:
                pos, look, ppl = cands[k]
                if self._visible(pos, look, ppl):
                    chosen = k
                    break
            if chosen is None:   # nothing clear: a high crane shot over both, from straight above
                fallback = self._candidates("crane", a, b, A, B)[-8:]
                cands, chosen, want = fallback, 0, "crane"
                for k, (pos, look, ppl) in enumerate(fallback):
                    if self._visible(pos, look, ppl):
                        chosen = k
                        break
            if chosen != idx and not cut:
                cut = True
        if cut or want != self.d_shot:
            self.d_shot_since = t if want != self.d_shot else self.d_shot_since
        self.d_shot, self.d_idx = want, chosen
        pos, look, _ = cands[chosen]
        if not cut and self.d_cam:   # smooth moves within a shot
            k = 0.2
            pos = tuple(p0 + k * (p1 - p0) for p0, p1 in zip(self.d_cam[0], pos, strict=False))
            look = tuple(p0 + k * (p1 - p0) for p0, p1 in zip(self.d_cam[1], look, strict=False))
        self.d_cam = (pos, look)
        pitch, yaw = self._aim(pos, look)
        return {"shot": want, "cand": chosen, "cut": cut, "cam": [round(v, 1) for v in pos], "pitch": round(pitch, 2),
                "yaw": round(yaw, 2), "checks": self.d_checks,
                "mara": {"x": round(a[0], 1), "y": round(a[1], 1), "z": round(a[2], 1), "yaw": round(A.rotation.yaw, 1)},
                "iris": {"x": round(b[0], 1), "y": round(b[1], 1), "z": round(b[2], 1), "yaw": round(B.rotation.yaw, 1)},
                "dist_m": round(d / 100, 2), "speaking": who}

    def _place(self, t):
        if self.director_dir is None or not self.d_ok:
            return None
        try:
            row = self._plan(t)
            x, y, z = row["cam"]
            self.wire.request(f"vset /camera/{DIRECTOR_CAM}/location {x} {y} {z}", resend=False)
            self.wire.request(c.set_camera_rotation(DIRECTOR_CAM, row["pitch"], row["yaw"], 0), resend=False)
            return row
        except Exception as e:
            self._d_error(f"plan t={t}: {e!r}")
            return None

    def _sway(self, t):
        """Both eye cameras get the idle head motion, at the camera so every control sees it. super()._before_capture has
        already put the agent's camera on its base aim (and does so every capture once _camera_overridden is set);
        the friend's follows its body, so its base aim is just the body's yaw."""
        try:
            base = [float(v) for v in str(self.wire.request(c.get_camera_rotation(self.camera_id))).split()]
            pitch, yaw = head_sway(t)
            self.wire.request(c.set_camera_rotation(self.camera_id, round(base[0] + pitch, 4), round(base[1] + yaw, 4), 0), resend=False)
            self._camera_overridden = True
            pitch, yaw = head_sway(t, FRIEND_SWAY_PHASE)
            body = self._read_pose(FRIEND_ACTOR).rotation.yaw
            self.wire.request(c.set_camera_rotation(self.friend_camera_id, round(pitch, 4), round(body + yaw, 4), 0), resend=False)
        except Exception as e:
            self._d_error(f"sway t={t}: {e!r}")

    def _before_capture(self, capture_time_s):
        super()._before_capture(capture_time_s)
        self._sway(capture_time_s)
        self._speak_due(capture_time_s)
        self._pending_row = self._place(capture_time_s)

    def _capture(self, offset_s, timing):
        cap = super()._capture(offset_s, timing)
        if self.director_dir is None or not self.d_ok:
            return cap
        t = self.now_s()
        row = getattr(self, "_pending_row", None) or self._place(t)
        self._pending_row = None
        try:
            data = self.wire.request(c.render(DIRECTOR_CAM, "lit", "png"), timeout=self.config.render_timeout_s)
            path = Path(self.director_dir) / f"f{self.d_frame:06d}.png"
            path.write_bytes(bytes(data))
            self.d_rows.write(json.dumps({"frame": self.d_frame, "t": t, "step": self.step_index, **(row or {})}) + "\n")
            self.d_rows.flush()
            self.d_frame += 1
        except Exception as e:
            self._d_error(f"render t={t}: {e!r}")
        return cap


def chunked_stream_class():
    """world_stream_multi.MultiWorldStream, but each push is fed to the same causal rollout in pieces of CHUNK frames.
    lunch_wm pushes a whole 10 s step (240 frames, 61 latents) at once, and the worker decodes them in one go: in
    wmbodies_demo's first step that peaked at 42.7 GB and swapped 26 GB; 48-frame pieces still peaked at 24.6 GB. The
    smoke test's 6-latent push peaked at 18.9 GB. Painting is identical; only the decode is split (one mild seam per chunk, as measured by the smoke test)."""
    import numpy as np
    from kokopelli.wm.world_stream_multi import MultiWorldStream

    class ChunkedWorldStream(MultiWorldStream):
        CHUNK = 24   # frames, 6 latents: 48 still peaked at 24.6 GB and swapped next to SimWorld (6.5 GB)

        def push(self, stream, controls):
            n = len(next(iter(controls.values())))
            outs, stats = [], []
            for a in range(0, n, self.CHUNK):
                part = {h: v[a:a + self.CHUNK] for h, v in controls.items()}
                outs.append(super().push(stream, part))
                stats.append(self.last.get(stream) or {})
            spl = [float(r.get("s_per_latent") or 0) for r in stats if r.get("s_per_latent")]
            self.last[stream] = {**(stats[-1] if stats else {}), "chunks": len(stats),
                                 "s_per_latent": round(sum(spl) / len(spl), 2) if spl else 0.0,
                                 "peak_gb": max((float(r.get("peak_gb") or 0) for r in stats), default=0.0)}
            return np.concatenate(outs) if outs else np.zeros((0,) + next(iter(controls.values())).shape[1:], np.uint8)

    return ChunkedWorldStream


class DemoCast(L.QuietCast):
    """After a resident's first hello she only speaks when named. In bodies_demo_sim2 Ana still broke into the agents'
    talk because "Loom & Thread" and "coffee" matched her topics."""

    def reply(self, pid, text, listener_xy):
        if pid in self.met and self.people[pid]["name"].split()[0].lower() not in text.lower():
            return None
        return super().reply(pid, text, listener_xy)


class DeadlineStop(Exception):
    pass


class DemoLunch(L.Lunch):
    """Lunch + spoken lines scheduled for gestures and captions."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.captions = (self.out / "captions.jsonl").open("a")
        self._slot_step, self._slot_t = None, 0.0
        self.said = {}    # person id -> the lines they've spoken, for check()

    deadline = None   # epoch seconds; set by --deadline HH:MM

    TALK_NOTE = (f"\nWhen you speak, keep it to one short sentence, at most {MAX_WORDS - 4} words, like real conversation. "
                 "If someone just spoke to you, answer what they said. Never say again something you already said: "
                 "move the talk on, or tell them your own news. Once a question has been answered, don't ask it again in other words: "
                 "talk about something else, like the fair, what to eat, or your plans for the afternoon.")

    def prompt(self, mind):
        return super().prompt(mind) + self.TALK_NOTE

    def check(self, mind, act):
        """lunch_wm's check, plus the talk rules. In wmbodies_demo Iris walked up to Mara three times instead of answering
        her from 2 m away, so Mara asked about the bees three times in nearly the same words."""
        super().check(mind, act)
        t = act.get("type")
        bodies = self.world.bodies()
        other = self.minds[mind.other]
        d = math.dist(bodies[mind.id].xy, bodies[other.id].xy)
        if t == "say":
            text = str(act.get("text", ""))
            if len(text.split()) > MAX_WORDS:
                raise ValueError(f"that is too long to say in one breath; use at most {MAX_WORDS - 4} words")
            if any(difflib.SequenceMatcher(None, text.lower(), old.lower()).ratio() >= SAME_LINE for old in self.said.get(mind.id, ())):
                raise ValueError("you already said that; say something new, answer them, or tell them your own news")
        elif mind.pending == "heard" and d <= L.HEAR_M and any(h.startswith(f"{other.name} (") for h in mind.heard):
            raise ValueError(f"{other.name} just spoke to you and is waiting; use a say action to answer her")
        elif t == "approach" and act.get("target") == other.id and d <= BESIDE_M:
            raise ValueError(f"you are already beside {other.name}; use a say action to talk to her")

    def step(self):
        import time
        t0 = time.time()
        super().step()
        self._step_times = getattr(self, "_step_times", []) + [time.time() - t0]
        done, total = self.step_no + 1, self.args.steps
        avg = sum(self._step_times[-4:]) / len(self._step_times[-4:])
        finish = time.time() + avg * (total - done)
        wm = getattr(self.wm, "last", {}) or {}
        spl = {k: v.get("s_per_latent") for k, v in wm.items() if isinstance(v, dict)}
        self.log("projection", step_s=round(self._step_times[-1], 1), avg_step_s=round(avg, 1), steps_left=total - done,
                 finish=datetime.fromtimestamp(finish).isoformat(timespec="minutes"), s_per_latent=spl)
        print(f"[demo] step {done}/{total} took {self._step_times[-1]:.0f}s, avg {avg:.0f}s, s/latent {spl}, "
              f"projected finish {datetime.fromtimestamp(finish):%H:%M}", flush=True)
        if self.deadline and done < total and time.time() + avg > self.deadline:
            self.say(f"\n_(demo cut short after step {done} of {total}: the next step would end after the "
                     f"{datetime.fromtimestamp(self.deadline):%H:%M} deadline)_")
            self.log("deadline_stop", steps_done=done, of=total)
            raise DeadlineStop(done)

    def _actor(self, who):
        sim = self.world.sim
        if who == self.args.first["id"]:
            return AGENT_ACTOR
        if who == self.args.second["id"]:
            return FRIEND_ACTOR
        return sim._tracked().get(who)

    def _schedule(self, who, name, text):
        sim = self.world.sim
        self.said.setdefault(who, []).append(text)
        base = sim.now_s()
        # one line after another, also across steps (resetting per step let a reply that spilled past the step end be
        # talked over by the next step's first line in wmbodies_demo; demo_cut.retime repairs that run's captions)
        start = max(self._slot_t, base + 0.3)
        actor = self._actor(who)
        end = sim.plan_speech(actor, who, text, start) if actor else start + words_seconds(text)
        self._slot_t = end + 0.25
        self.captions.write(json.dumps({"who": who, "name": name, "text": text, "start": round(start, 3), "end": round(end, 3),
                                        "step": self.step_no, "actor": actor}) + "\n")
        self.captions.flush()

    def say(self, md):
        super().say(md)
        # lunch_wm prints every line through say(); spoken ones look like "> **Name:** text"
        if md.startswith("> **") and ":** " in md:
            name, text = md[4:].split(":** ", 1)
            who = next((m.id for m in self.minds.values() if m.name == name), None)
            if who is None and self.cast:
                who = next((pid for pid, p in self.cast.people.items() if p["name"] == name), name)
            self._schedule(who, name, text)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    size, director = "1280x720", True
    if "--director-size" in argv:
        k = argv.index("--director-size")
        size = argv[k + 1]
        del argv[k:k + 2]
    if "--deadline" in argv:   # HH:MM local; the run stops after the last step that ends before it
        k = argv.index("--deadline")
        hh, mm = (int(v) for v in argv[k + 1].split(":"))
        now = datetime.now()
        dl = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if dl < now:
            from datetime import timedelta
            dl += timedelta(days=1)
        DemoLunch.deadline = dl.timestamp()
        del argv[k:k + 2]
    if "--no-director" in argv:
        argv.remove("--no-director")
        director = False
    from navmap import NavMap
    args = L.build_args(argv)
    nav = NavMap()
    L.people(args, nav)
    cast = None if args.no_npcs else L.lunch_cast(nav)
    if cast is not None:
        cast.__class__ = DemoCast
    args.out = args.out or str(ROOT / "out" / "bodies" / "demo" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "_lunch"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    DirectorSim.director_dir = str(out / "director") if director else None
    DirectorSim.director_size = tuple(int(v) for v in size.split("x"))
    DirectorSim.nav = nav
    L.TwoBodySim = DirectorSim          # SimWorldPair looks the class up at construction time
    L.Lunch = DemoLunch
    (out / "demo_wrapper.json").write_text(json.dumps({
        "wrapper": "tools/bodies/demo_lunch.py", "lunch_code": "kokopelli/agents/lunch_wm.py (unchanged)",
        "director_camera": DIRECTOR_CAM if director else None, "director_size": size, "head_sway": True, "argv": argv}, indent=1))
    wm = chunked_stream_class()(out_dir=out / "wm", quantize=args.quantize, fake=args.fake_wm)
    try:
        L.open_streams(wm, args, [args.first["id"], args.second["id"]])
        with L.make_world(args, nav, cast) as world:
            lunch = DemoLunch(args, world, wm, L.QwenBrain(args.weights), out=args.out, nav=nav, cast=cast)
            try:
                lunch.run(args.steps)
            except DeadlineStop as e:
                print(f"[demo] stopped at the deadline after {e} steps; films and transcript are complete up to there")
    finally:
        wm.close()


if __name__ == "__main__":
    main()
