"""The bodies demo's talk rules (tools/bodies/demo_lunch.py): answer when spoken to, short lines, no repeats."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "bodies"))
import demo_lunch as D  # noqa: E402
import demo_cut  # noqa: E402


def lunch(apart_m):
    bodies = {"mara": SimpleNamespace(xy=(0.0, 0.0)), "iris": SimpleNamespace(xy=(apart_m, 0.0))}
    world = SimpleNamespace(bodies=lambda: bodies, objects=lambda: [])
    out = D.DemoLunch.__new__(D.DemoLunch)
    out.world, out.cast, out.said = world, None, {}
    out.minds = {"mara": SimpleNamespace(id="mara", name="Mara", other="iris", pending=None, heard=[]),
                 "iris": SimpleNamespace(id="iris", name="Iris", other="mara", pending=None, heard=[])}
    return out


class TalkRules(unittest.TestCase):
    def test_answering_is_required_when_the_other_just_spoke(self):
        l = lunch(2.0)
        iris = l.minds["iris"]
        iris.pending, iris.heard = "heard", ['Mara (mara): "How are the bees?"']
        for act in ({"type": "approach", "target": "mara"}, {"type": "wait"}):
            with self.assertRaisesRegex(ValueError, "just spoke"):
                l.check(iris, act)
        l.check(iris, {"type": "say", "text": "One hive swarmed on Thursday."})

    def test_a_resident_speaking_does_not_force_an_answer(self):
        l = lunch(2.0)
        iris = l.minds["iris"]
        iris.pending, iris.heard = "heard", ['Ana Reyes (ana): "Afternoon!"']
        l.check(iris, {"type": "wait"})

    def test_approach_is_refused_only_when_already_beside(self):
        with self.assertRaisesRegex(ValueError, "already beside"):
            l = lunch(2.0)
            l.check(l.minds["mara"], {"type": "approach", "target": "iris"})
        l = lunch(8.0)
        l.check(l.minds["mara"], {"type": "approach", "target": "iris"})

    def test_repeats_are_refused_and_new_lines_pass(self):
        l = lunch(2.0)
        l.said["mara"] = ["Hey Iris, I know you're buzzing, but I'm all ears, what's new with the bees?"]
        with self.assertRaisesRegex(ValueError, "already said"):
            l.check(l.minds["mara"], {"type": "say", "text": "Iris, I know you're buzzing, but I'm all ears, what's new with the bees?"})
        l.check(l.minds["mara"], {"type": "say", "text": "The fair banners are finally dyed."})
        l.said = {"iris": l.said["mara"]}    # one person's lines don't count against another
        l.check(l.minds["mara"], {"type": "say", "text": "Iris, I know you're buzzing, but I'm all ears, what's new with the bees?"})

    def test_long_lines_are_refused(self):
        l = lunch(2.0)
        with self.assertRaisesRegex(ValueError, "too long"):
            l.check(l.minds["mara"], {"type": "say", "text": " ".join(["word"] * (D.MAX_WORDS + 1))})

    def test_spoken_time_covers_the_caption_so_retime_does_not_move_lines(self):
        caps, t = [], 10.0
        for text in ("Hi.", "The hive on the east roof swarmed on Thursday morning.", "x" * 240):
            end = t + D.words_seconds(text)
            caps.append({"text": text, "start": round(t, 3), "end": round(end, 3)})
            t = end + 0.25
        self.assertEqual([c["start"] for c in demo_cut.retime(caps)], [c["start"] for c in caps])


class HeadSway(unittest.TestCase):
    def sim(self):
        sim = D.DirectorSim.__new__(D.DirectorSim)
        sim.sent, sim.camera_id, sim.friend_camera_id, sim.director_dir = [], 1, 2, None
        sim._camera_overridden = False

        def request(cmd, **kw):
            sim.sent.append(cmd)
            return "-5.0 90.0 0.0" if cmd.startswith("vget") else "ok"
        sim.wire = SimpleNamespace(request=request)
        sim._read_pose = lambda actor: SimpleNamespace(rotation=SimpleNamespace(yaw=30.0))
        return sim

    def test_stays_small_and_the_two_agents_differ(self):
        ts = [i / 24 for i in range(24 * 20)]
        offsets = [D.head_sway(t) for t in ts]
        self.assertLess(max(abs(p) for p, _ in offsets), 0.45)
        self.assertLess(max(abs(y) for _, y in offsets), 0.91)
        self.assertGreater(max(y for _, y in offsets) - min(y for _, y in offsets), 1.0)
        self.assertNotEqual(D.head_sway(1.0), D.head_sway(1.0, D.FRIEND_SWAY_PHASE))

    def test_each_camera_gets_its_base_aim_plus_sway(self):
        sim = self.sim()
        sim._sway(1.0)
        sets = [cmd.split() for cmd in sim.sent if cmd.startswith("vset /camera")]
        self.assertEqual([cmd[1] for cmd in sets], ["/camera/1/rotation", "/camera/2/rotation"])
        pitch, yaw = D.head_sway(1.0)
        self.assertAlmostEqual(float(sets[0][2]), -5.0 + pitch, places=3)
        self.assertAlmostEqual(float(sets[0][3]), 90.0 + yaw, places=3)
        pitch, yaw = D.head_sway(1.0, D.FRIEND_SWAY_PHASE)
        self.assertAlmostEqual(float(sets[1][2]), pitch, places=3)
        self.assertAlmostEqual(float(sets[1][3]), 30.0 + yaw, places=3)
        self.assertTrue(sim._camera_overridden)   # so the adapter restores the base aim before the next capture


class Residents(unittest.TestCase):
    def cast(self):
        cast = D.DemoCast.__new__(D.DemoCast)
        cast.people, cast.met = {"ana": {"name": "Ana Reyes", "fallback": ()}}, {"ana"}
        return cast

    def test_a_resident_who_has_met_them_only_answers_when_named(self):
        with mock.patch.object(D.L.QuietCast, "reply", return_value="Oat flat white?") as parent:
            self.assertIsNone(self.cast().reply("ana", "Bring me coffee when you're ready.", (0, 0)))
            parent.assert_not_called()
            self.assertEqual(self.cast().reply("ana", "Ana, two coffees please.", (0, 0)), "Oat flat white?")


if __name__ == "__main__":
    unittest.main()
