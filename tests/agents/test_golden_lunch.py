"""Golden-run regression for the two-agent lunch: a fixed-seed run on the fake world, the scripted brain and the fake
world model, whose event log must match tests/golden/lunch_fake.json event for event.

No model runs: FakeWorld, ScriptedBrain and the fake MultiWorldStream come from test_city_lunch. Timing fields and the
run folder are taken out of the log before comparing, so only behavior is compared.

After an intended behavior change, regenerate and review the diff:
    .venv/bin/python tests/agents/test_golden_lunch.py --update-golden
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.agents import test_city_lunch as tcl  # noqa: E402  (FakeWorld, ScriptedBrain and the lunch args; its tests aren't re-run here)

lw = tcl.lw
GOLDEN = Path(__file__).resolve().parent / "golden" / "lunch_fake.json"
SEED = 2025
TIMING = {"seconds", "total_s", "controls_s", "sim_s", "s_per_latent", "peak_gb", "encode_s", "paint_s", "decode_s"}


class GoldenBrain(tcl.ScriptedBrain):
    """ScriptedBrain, except Iris lets one of Mara's lines go unanswered once, so Mara waits PATIENCE steps for an
    answer before deciding again and then asks once more: the golden log then pins PATIENCE (the plain brain always
    answers at once)."""

    def __init__(self):
        super().__init__()
        self.ignored = self.nudged = False

    def ask(self, prompt, image):
        heard = tcl.section(prompt, "What you heard:\n", "\n\nYour notes")
        close = tcl.section(prompt, "Who is right next to you (close enough to talk):\n", "\n")
        if (prompt.startswith("You are Mara") and self.ignored and not self.nudged and "Iris" not in heard
                and "iris" in close):
            self.calls.append({"name": "Mara", "prompt": prompt, "image": image})
            self.nudged = True
            return json.dumps({"thought": "did she hear me?", "action": {"type": "say", "text": "Iris, did you hear me?"}})
        reply = super().ask(prompt, image)
        if self.calls[-1]["name"] == "Iris" and self.lines["Iris"] == 3 and not self.ignored:
            self.ignored, self.lines["Iris"] = True, 2
            return json.dumps({"thought": "not now", "action": {"type": "wait"}})
        return reply


def normalize(event, run_dir):
    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if k not in TIMING}
        if isinstance(v, list):
            return [clean(x) for x in v]
        if isinstance(v, str):
            return v.replace(str(run_dir), "<run>")
        return v
    return clean(event)


def golden_run():
    """Run the lunch once and return (normalized events, run.json)."""
    tmp = Path(tempfile.mkdtemp(prefix="test_golden_lunch_"))
    try:
        out = tmp / "run"
        nav = lw.NavMap()
        args = tcl.lunch_args(out)
        args.seed = SEED
        lw.people(args, nav)
        world = tcl.FakeWorld(nav, tmp / "sim", {"mara": nav.doors["fern_common"], "iris": nav.doors["fern_bakery"]})
        wm = tcl.MultiWorldStream(out_dir=out / "wm", fake=True)
        try:
            lw.open_streams(wm, args, ["mara", "iris"])
            lw.Lunch(args, world, wm, GoldenBrain(), out=out, nav=nav, cast=None).run(args.steps)
        finally:
            wm.close()
        events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()]
        events = [normalize(e, out) for e in events if e["kind"] != "step_time"]
        return events, json.loads((out / "run.json").read_text())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def first_difference(got, want):
    for i, (g, w) in enumerate(zip(got, want, strict=False)):
        if g != w:
            return f"event {i} differs:\n got  {json.dumps(g)[:400]}\n want {json.dumps(w)[:400]}"
    return f"lengths differ: got {len(got)} events, want {len(want)}"


class GoldenLunchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events, cls.run_json = golden_run()

    def test_event_log_matches_golden(self):
        want = json.loads(GOLDEN.read_text())["events"]
        if self.events != want:
            self.fail(first_difference(self.events, want) + "\nIf the change is intended: "
                      ".venv/bin/python tests/agents/test_golden_lunch.py --update-golden")

    def test_a_second_run_is_identical(self):
        self.assertEqual(golden_run()[0], self.events)

    def test_changing_patience_breaks_the_golden(self):
        with mock.patch.object(lw, "PATIENCE", lw.PATIENCE + 1):
            changed, _ = golden_run()
        self.assertNotEqual(changed, self.events)

    def test_manifest_is_complete_and_says_fake(self):
        m = self.run_json["manifest"]
        for field in ("commit", "dirty", "weights", "seed", "prompt", "quantize", "controls", "resolution", "fake"):
            self.assertIn(field, m)
        self.assertTrue(m["fake"])
        self.assertTrue(m["fake_world_model"])
        self.assertTrue(m["fake_brain"])
        self.assertEqual(m["brain"], "GoldenBrain")
        self.assertNotIn("world_model", m["weights"])
        self.assertEqual(m["seed"], {"mara": SEED, "iris": SEED + 1})


if __name__ == "__main__":
    if "--update-golden" in sys.argv:
        events, _ = golden_run()
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps({"about": "tests/agents/test_golden_lunch.py: fake world, GoldenBrain, fake world model, "
                                               f"seed {SEED}; timing fields removed", "events": events}, indent=1) + "\n")
        print(f"wrote {GOLDEN} ({len(events)} events)")
    else:
        unittest.main()
