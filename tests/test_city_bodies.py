"""Bodies on the Python side (tools/bodies/PLAN.md, wave 1 C): SetBody/GetBody replies, the old-server fallback,
npcs.json body ids, and live.py asking for bodies after spawn.

No server, no Qwen, no GPU: live.py runs zero steps against a fake sim whose wire answers like the server would.

    .venv/bin/python -m unittest tests/test_city_bodies.py -v
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kokopelli" / "agents"))

import live  # noqa: E402  (puts the wm-agent-loop worktree on the path)
from kokopelli.agents import bodies_client as bodies  # noqa: E402
from kokopelli.loop.adapters.simworld_wire import CommandError  # noqa: E402

NPCS = json.loads((ROOT / "kokopelli" / "agents" / "npcs.json").read_text())["npcs"]
OLD_SERVER = "error mock server does not implement blueprint function SetBody"   # mac_server/tests/mock_server.py


class FakeWire:
    """Answers like the adapter's SimWorldWire: replies as strings, CommandError for "error ..." replies.
    `answer(command)` decides the reply; every command is kept in `sent`."""

    def __init__(self, answer):
        self.answer, self.sent = answer, []

    def request(self, command, timeout=None, resend=None):
        self.sent.append(command)
        reply = self.answer(command)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, str) and reply.lower().startswith("error"):
            raise CommandError(f"{command!r} -> {reply}")
        return reply


def new_server(missing=(), near=None, fallback=()):
    """A server that knows SetBody/GetBody; bodies in `missing` are refused naming the asset. With `near` (a set of
    actors), GetBody also reports the near/far tier; without it, it answers like a build from before that plan."""
    worn = {}

    def answer(command):
        parts = command.split()
        if parts[0] == "vbp" and parts[2] == "SetBody":
            if parts[3] in missing:
                return f"error missing asset /Game/Characters/Bodies/{parts[3]}"
            worn[parts[1]] = parts[3]
            return json.dumps({"ok": True, "body": parts[3]})
        if parts[0] == "vbp" and parts[2] == "GetBody":
            reply = {"ok": True, "body": worn.get(parts[1], "manny")}
            if near is not None:
                reply["tier"] = "fallback" if parts[1] in fallback else "near" if parts[1] in near else "far"
            return json.dumps(reply)
        return "{}"
    return answer


def old_server(command):
    return OLD_SERVER if " SetBody " in command or command.endswith(" GetBody") else "{}"


class ReplyParsing(unittest.TestCase):
    def test_ok(self):
        r = bodies.parse_reply("A", "mara", '{"ok": true, "body": "mara"}')
        self.assertTrue(r.ok)
        self.assertEqual(r.body, "mara")
        self.assertIsNone(r.error)
        self.assertFalse(r.fell_back)

    def test_padded_json_and_string_true(self):
        r = bodies.parse_reply("A", "iris", b'{\n\t"ok": "true",\n\t"body": "iris"\n}\n')
        self.assertTrue(r.ok)
        self.assertEqual(r.body, "iris")

    def test_fallback_body_is_recorded(self):
        r = bodies.parse_reply("A", "mara", '{"ok": true, "body": "manny"}')
        self.assertTrue(r.ok)
        self.assertTrue(r.fell_back)
        self.assertEqual(r.as_dict()["fell_back"], True)

    def test_json_refusal_names_the_asset(self):
        r = bodies.parse_reply("A", "mara", '{"ok": false, "error": "missing asset /Game/Characters/Bodies/Mara/SKM"}')
        self.assertFalse(r.ok)
        self.assertTrue(r.supported)
        self.assertIn("/Game/Characters/Bodies/Mara", r.error)

    def test_unrealcv_error_string(self):
        r = bodies.parse_reply("A", "mara", "error missing asset /Game/X")
        self.assertFalse(r.ok)
        self.assertTrue(r.supported)
        self.assertEqual(r.error, "error missing asset /Game/X")

    def test_old_server_is_not_supported(self):
        for reply in (OLD_SERVER, "error Can not find function SetBody", "", None):
            r = bodies.parse_reply("A", "mara", reply)
            self.assertFalse(r.ok, reply)
            self.assertFalse(r.supported, reply)

    def test_get_body_bare_id(self):
        r = bodies.parse_reply("A", None, "wen\n")
        self.assertTrue(r.ok)
        self.assertEqual(r.body, "wen")

    def test_get_body_with_and_without_tier(self):
        r = bodies.parse_reply("A", None, '{"ok": true, "body": "mara", "tier": "far"}')
        self.assertEqual((r.ok, r.body, r.tier), (True, "mara", "far"))
        r = bodies.parse_reply("A", None, '{"ok": true, "body": "mara"}')   # before the near/far plan
        self.assertEqual((r.ok, r.body, r.tier), (True, "mara", None))
        self.assertEqual(bodies.parse_reply("A", None, '{"ok": true, "body": "manny", "tier": "near"}').tier, "near")
        self.assertEqual(bodies.parse_reply("A", None, '{"ok": true, "body": "manny", "tier": "fallback"}').tier,
                         "fallback")
        self.assertIsNone(bodies.parse_reply("A", None, '{"ok": true, "body": "mara", "tier": "mid"}').tier)

    def test_garbage(self):
        r = bodies.parse_reply("A", "mara", "<html>what</html>")
        self.assertFalse(r.ok)
        self.assertIn("unexpected reply", r.error)


class Commands(unittest.TestCase):
    def test_set_and_get_send_the_planned_commands(self):
        wire = FakeWire(lambda c: '{"ok": true, "body": "mara"}')
        self.assertTrue(bodies.set_body(wire, "GEN_BP_Humanoid_0", "mara").ok)
        self.assertEqual(bodies.get_body(wire, "GEN_BP_Humanoid_0").body, "mara")
        self.assertEqual(wire.sent, ["vbp GEN_BP_Humanoid_0 SetBody mara", "vbp GEN_BP_Humanoid_0 GetBody"])

    def test_command_error_from_the_adapter_wire(self):
        r = bodies.set_body(FakeWire(new_server(missing={"mara"})), "GEN_BP_Humanoid_0", "mara")
        self.assertFalse(r.ok)
        self.assertTrue(r.supported)
        self.assertEqual(r.error, "error missing asset /Game/Characters/Bodies/mara")

    def test_bare_client_returning_error_strings(self):
        """A raw unrealcv.Client returns "error ..." instead of raising."""
        client = SimpleNamespace(request=lambda command: OLD_SERVER)
        r = bodies.set_body(client, "GEN_BP_Pedestrian_0", "ana")
        self.assertFalse(r.supported)

    def test_lost_link_is_a_failure_not_a_crash(self):
        r = bodies.set_body(FakeWire(lambda c: ConnectionError("gone")), "A", "mara")
        self.assertFalse(r.ok)
        self.assertTrue(r.supported)
        self.assertIn("gone", r.error)

    def test_tiers(self):
        wire = FakeWire(new_server(near={"A"}))
        self.assertEqual(bodies.tiers(wire, ["A", "B"]), {"A": "near", "B": "far"})
        self.assertEqual(bodies.tiers(FakeWire(new_server()), ["A"]), {"A": None})
        self.assertEqual(bodies.tiers(FakeWire(old_server), ["A"]), {"A": None})

    def test_dress_stops_asking_an_old_server(self):
        wire = FakeWire(old_server)
        out = bodies.dress(wire, {"A": "mara", "B": "iris", "C": None, "D": "ana"})
        self.assertEqual(wire.sent, ["vbp A SetBody mara"])
        self.assertEqual(set(out), {"A", "B", "D"})
        self.assertTrue(all(not r.ok and not r.supported for r in out.values()))

    def test_dress_keeps_going_past_a_missing_asset(self):
        wire = FakeWire(new_server(missing={"iris"}))
        out = bodies.dress(wire, {"A": "mara", "B": "iris", "C": "ana"})
        self.assertEqual(len(wire.sent), 3)
        self.assertEqual([out[k].ok for k in "ABC"], [True, False, True])


class NpcBodies(unittest.TestCase):
    def test_every_resident_wears_their_own_body(self):
        for npc in NPCS:
            self.assertEqual(npc.get("body"), npc["id"], "a body is named after the person who wears it")
            self.assertIn(npc["body"], bodies.PLANNED_BODIES, npc["id"])

    @unittest.skipUnless(bodies.BODIES_JSON.exists(), "mac_server/Config/Bodies.json not written yet (wave 1 B)")
    def test_every_resident_body_is_in_bodies_json(self):
        known = bodies.known_bodies()
        for npc in NPCS:
            self.assertIn(npc["body"], known, f"{npc['id']}: {npc['body']} is not in {bodies.BODIES_JSON}")

    @unittest.skipUnless(bodies.BODIES_JSON.exists(), "mac_server/Config/Bodies.json not written yet (wave 1 B)")
    def test_default_agent_body_is_in_bodies_json(self):
        self.assertIn("mara", bodies.known_bodies())

    def test_known_bodies_reads_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "Bodies.json"
            self.assertIsNone(bodies.known_bodies(path))
            path.write_text(json.dumps({"bodies": {"mara": {}, "manny": {}}}))
            self.assertEqual(bodies.known_bodies(path), {"mara", "manny"})


class FakeSim:
    """Just enough of SimWorldPhysics for Life.run with zero steps: reset, a wire, one frame."""

    def __init__(self, cfg, answer, folder):
        self.config, self.wire = cfg, FakeWire(answer)
        self.frame = Path(folder) / "f.png"
        self.frame.write_bytes(b"\x89PNG fake")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def reset(self, seed=0):
        pose = SimpleNamespace(location=SimpleNamespace(x=0.0, y=0.0, z=100.0), rotation=SimpleNamespace(yaw=0.0))
        state = SimpleNamespace(agent=SimpleNamespace(pose=pose, held_object=None, posture="standing"),
                                time_of_day=SimpleNamespace(clock="14:00:00"), npcs=[], objects=[], sim_time_s=0.0)
        return SimpleNamespace(state=state, renders={"rgb": SimpleNamespace(path=str(self.frame))})


class LiveWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_city_bodies_"))
        self.patches = [mock.patch.object(live, "ROOT", self.tmp)]   # run folders go here, not out/city_agents
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def args(self, **kw):
        base = dict(port=9999, steps=0, who="w", situation="s", clock="14:00", speed=1.6, follow=False,
                    vision="unreal", weights=str(ROOT / "models" / "Qwen3-VL-8B-Instruct-4bit"), body="mara")
        return SimpleNamespace(**{**base, **kw})

    def run_life(self, answer, **kw):
        sims = []

        def make(cfg):
            sims.append(FakeSim(cfg, answer, self.tmp))
            return sims[0]
        with mock.patch.object(live, "SimWorldPhysics", make), mock.patch("builtins.print"):
            life = live.Life(self.args(**kw))
            try:
                life.run()
            finally:
                life.events.close()
                life.transcript.close()
        events = [json.loads(line) for line in (life.out / "events.jsonl").read_text().splitlines()]
        return life, sims[0].wire.sent, events, json.loads((life.out / "run.json").read_text())

    def test_bodies_sent_after_spawn_and_recorded(self):
        life, sent, events, run = self.run_life(new_server())
        set_cmds = [c for c in sent if " SetBody " in c]
        self.assertEqual(set_cmds[0], "vbp GEN_BP_Humanoid_0 SetBody mara")
        expected = {f"vbp {s.actor_name} SetBody {life.cast.people[s.id]['body']}" for s in life.cfg.npcs}
        self.assertEqual(set(set_cmds[1:]), expected)
        self.assertLess(sent.index(set_cmds[-1]), next(i for i, c in enumerate(sent) if "StopPedestrian" in c))
        body_events = [e for e in events if e["kind"] == "body"]
        self.assertEqual({e["who"] for e in body_events}, {"agent", *(n["id"] for n in NPCS)})
        self.assertEqual(run["bodies"]["agent"]["body"], "mara")
        self.assertEqual(run["bodies"]["kai"]["body"], "kai")
        self.assertEqual(run["body_asked"]["agent"], "mara")
        self.assertEqual(run["agent_model"], "Qwen3-VL-8B-Instruct-4bit")
        self.assertTrue(run["finished"])

    def test_old_server_warns_and_the_run_goes_on(self):
        life, sent, events, run = self.run_life(old_server)
        self.assertEqual(sum(" SetBody " in c for c in sent), 1)   # asked once, then stopped asking
        warnings = [e for e in events if e["kind"] == "body_warning"]
        self.assertEqual(len(warnings), 1 + len(NPCS))
        self.assertTrue(all(not w["supported"] for w in warnings))
        self.assertFalse(run["bodies"]["agent"]["ok"])
        self.assertTrue(run["finished"])
        self.assertTrue((life.out / "live.json").exists())

    def test_missing_asset_only_affects_that_person(self):
        _, _, events, run = self.run_life(new_server(missing={"wen"}))
        self.assertFalse(run["bodies"]["wen"]["ok"])
        self.assertIn("wen", run["bodies"]["wen"]["error"])
        self.assertTrue(run["bodies"]["ana"]["ok"])
        self.assertEqual([e["who"] for e in events if e["kind"] == "body_warning"], ["wen"])

    def test_tiers_logged_per_step_when_the_server_reports_them(self):
        life, _, events, _ = self.run_life(new_server(near={"GEN_BP_Humanoid_0", "GEN_BP_Pedestrian_0"}))
        rows = [e for e in events if e["kind"] == "tiers"]
        self.assertEqual(len(rows), 1)   # zero steps: just the one after spawning
        self.assertEqual(rows[0]["step"], 0)
        first = life.cfg.npcs[0].id
        self.assertEqual(rows[0]["tiers"]["agent"], "near")
        self.assertEqual(rows[0]["tiers"][first], "near")
        self.assertEqual({k for k, v in rows[0]["tiers"].items() if v == "far"}, {n["id"] for n in NPCS} - {first})

    def test_fallback_tier_is_warned_once(self):
        life, _, events, _ = self.run_life(new_server(near=set(), fallback={"GEN_BP_Humanoid_0"}))
        self.assertEqual([e for e in events if e["kind"] == "tiers"][0]["tiers"]["agent"], "fallback")
        warned = [e for e in events if e["kind"] == "body_warning"]
        self.assertEqual([(e["who"], e["tier"]) for e in warned], [("agent", "fallback")])
        with (life.out / "events.jsonl").open("a") as life.events:   # one more step's check, after the run closed it
            life.log_tiers(SimpleNamespace(wire=FakeWire(new_server(near=set(), fallback={"GEN_BP_Humanoid_0"}))), 1)
        again = [json.loads(x) for x in (life.out / "events.jsonl").read_text().splitlines()]
        self.assertEqual(sum(e["kind"] == "body_warning" for e in again), 1)   # still fallback: no second warning

    def test_no_tier_rows_from_servers_that_dont_report_them(self):
        for answer in (new_server(), old_server):
            life, sent, events, _ = self.run_life(answer)
            self.assertFalse([e for e in events if e["kind"] == "tiers"])
            self.assertFalse(life.watch_tiers)
        self.assertFalse([c for c in sent if c.endswith(" GetBody")])   # an old server isn't even asked

    def test_empty_body_sends_nothing_for_the_agent(self):
        _, sent, _, run = self.run_life(new_server(), body="")
        self.assertNotIn("vbp GEN_BP_Humanoid_0 SetBody", " ".join(sent))
        self.assertNotIn("agent", run["bodies"])

    def test_body_flag_defaults_to_mara(self):
        seen = {}

        class Recorder:
            def __init__(self, args):
                seen["args"] = args

            def run(self):
                pass
        with mock.patch.object(live, "Life", Recorder), mock.patch.object(sys, "argv", ["live.py"]):
            live.main()
        self.assertEqual(seen["args"].body, "mara")
        with mock.patch.object(live, "Life", Recorder), mock.patch.object(sys, "argv", ["live.py", "--body", "iris"]):
            live.main()
        self.assertEqual(seen["args"].body, "iris")


if __name__ == "__main__":
    unittest.main()
