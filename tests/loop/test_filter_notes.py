import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from kokopelli.loop import notebook
from kokopelli.loop.adapters.cosmos_server import FILTER_MODEL, CosmosServerWorldModel
from kokopelli.loop.config import Config
from kokopelli.loop.frames import control_frame, read_clip
from kokopelli.loop.interfaces import ChunkRequest
from kokopelli.loop.prompt_builder import build_wm_prompt, outcome_text
from kokopelli.loop.replay import summarize
from kokopelli.loop.run import run
from tests.loop.test_cosmos_server import FakeServer
from kokopelli.loop.mocks.context import MockContext

NOW = "1992-03-19T09:00:30"
LATER = "1992-03-20T09:01:00"


def folder():
    return Path(tempfile.mkdtemp(prefix="wmloop_"))


def filter_config(**values):
    return Config(ticks=2, wm_filter="depth", wm_preset="filter_mock", drift_control=False, counterfactual=False, **values)


class NotebookTest(unittest.TestCase):
    def test_nearly_the_same_note_stays_one_note(self):
        notes = notebook.remember([], NOW, "The clock ticks louder than usual, echoing in the quiet space.")
        notebook.remember(notes, LATER, "The clock ticks louder than usual, echoing in the quiet room.")
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0]["times"], notes[0]["last"]), (2, LATER))

    def test_a_different_note_is_kept(self):
        notes = notebook.remember([], NOW, "The pigeons are gone.")
        self.assertEqual(len(notebook.remember(notes, LATER, "I walked to the bench and sat down.")), 2)

    def test_a_repeated_note_stays_in_view(self):
        notes = notebook.remember([], NOW, "first thought about the door")
        for i in range(3):
            notebook.remember(notes, f"1992-03-19T09:0{i + 1}:00", f"unrelated {i} " + "x" * i * 30)
        notebook.remember(notes, "1992-03-19T09:09:00", "first thought about the door")
        self.assertEqual(notebook.latest(notes, 1)[0]["text"], "first thought about the door")

    def test_the_folder_follows_the_format(self):
        out = folder()
        notes = notebook.remember([], NOW, 'She said "wait: here"\nand left.')
        notebook.remember(notes, NOW, 'She said "wait: here"\nand left.')
        notebook.write_bundle(out, notes)
        document = (out / "notes" / "note-0001.md").read_text()
        head = document.split("---\n")[1]
        self.assertIn("type: Diary Note", head)
        self.assertEqual(json.loads(head.split("description: ")[1].split("\n")[0]), 'She said "wait: here" and left.')
        self.assertIn("okf_version", (out / "index.md").read_text())
        self.assertIn("## 1992-03-19", (out / "log.md").read_text())

    def test_the_folder_forgets_what_the_list_forgot(self):
        out = folder()
        notes = notebook.remember([], NOW, "one")
        notebook.remember(notes, NOW, "something else entirely")
        notebook.write_bundle(out, notes)
        notebook.write_bundle(out, notes[:1])
        self.assertEqual([path.name for path in (out / "notes").iterdir()], ["note-0001.md"])


class OutcomeTest(unittest.TestCase):
    def test_says_what_changed(self):
        text = outcome_text({"type": "move_to", "target": "door"}, ["ana", "door"], ["door", "ball"])
        self.assertIn("move_to door", text)
        self.assertIn("Now in view: ball.", text)
        self.assertIn("No longer in view: ana.", text)

    def test_says_when_nothing_changed_or_it_failed(self):
        self.assertIn("did not change", outcome_text({"type": "wait"}, ["door"], ["door"]))
        self.assertIn("didn't work", outcome_text({"type": "interact", "target": "ana"}, ["ana"], ["ana"], {"ok": False}))


class FilterRunTest(unittest.TestCase):
    def test_every_output_frame_comes_from_the_sim(self):
        out = folder()
        run(filter_config(), out)
        events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()]
        chunks = [e["data"] for e in events if e["kind"] == "wm_chunk"]
        self.assertEqual([chunk["frames"] for chunk in chunks], [12, 12, 12, 12])
        self.assertFalse([e for e in events if e["kind"] in ("reanchor", "drift_check")])
        control, painted = read_clip(out / chunks[-1]["control"]), read_clip(out / chunks[-1]["clip"])
        self.assertEqual(len(control), len(painted))
        self.assertLess(np.abs(painted[-1].astype(int) - (control[-1] // 2 + 40)).mean(), 6)

    def test_the_picture_does_not_decay(self):
        out = folder()
        run(Config(ticks=8, wm_filter="depth", wm_preset="filter_mock", drift_control=False, counterfactual=False), out)
        # The scene itself moves, so what must hold is that the last tick still matches its own control as well as the first did.
        errors = []
        for tick in ("0001", "0008"):
            control, painted = read_clip(out / "ticks" / tick / "control_00.mp4"), read_clip(out / "ticks" / tick / "wm_00.mp4")
            errors.append(float(np.abs(painted[-1].astype(int) - (control[-1] // 2 + 40)).mean()))
        self.assertLess(errors[1], errors[0] + 1)

    def test_only_checked_captures_stay_on_disk(self):
        out = folder()
        run(filter_config(), out)
        self.assertEqual(sorted(path.name for path in (out / "ticks/0001").glob("sim_*_depth.png")),
                         ["sim_015.000_depth.png", "sim_030.000_depth.png"])

    def test_same_seed_same_run_and_the_chain_holds(self):
        a, b = folder(), folder()
        run(filter_config(), a)
        run(filter_config(), b)
        hashes = [[json.loads(line)["data"]["hash"] for line in (run_dir / "events.jsonl").read_text().splitlines()
                   if json.loads(line)["kind"] == "wm_chunk"] for run_dir in (a, b)]
        self.assertEqual(*hashes)
        self.assertEqual(len(summarize(a)["ticks"]), 2)

    def test_the_final_video_keeps_every_frame(self):
        out = folder()
        run(filter_config(), out)
        self.assertEqual(len(read_clip(out / "final.mp4")), 48)

    def test_the_prompt_leaves_geometry_to_the_sim(self):
        mock = MockContext()
        now = mock.start_time()
        context = mock.context_at(now)
        state = {"time_of_day": "morning", "weather": "clear", "agent": {"pos": [1, 2], "facing": "north"},
                 "npcs": {"ana": {"pos": [3, 4]}}, "objects": {}}
        text, _ = build_wm_prompt(context, state, {"type": "wait"}, "Style.", now, steer=False)
        self.assertNotIn("Camera at", text)
        self.assertNotIn("just chose", text)


class FilterServerTest(unittest.TestCase):
    def request(self, control):
        return ChunkRequest("A hallway.", [], None, str(folder() / "out.mp4"), 1, 0, 24, 7, str(control))

    def test_a_session_resets_once_and_then_continues(self):
        with FakeServer() as server:
            model = CosmosServerWorldModel(server.url, "832x480", 4, control_kind="seg")
            model.render_chunk(self.request("/shared/control_00.mp4"))
            model.render_chunk(self.request("/shared/control_01.mp4"))
        first, second = (json.loads(sent["extra_params"]) for sent in server.received)
        self.assertEqual((first["reset"], second["reset"]), (True, False))
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(second["seg"]["control_path"], "/shared/control_01.mp4")
        self.assertNotIn("input_reference", server.received[0])
        self.assertEqual(server.received[0]["model"].decode(), FILTER_MODEL)


class ControlFrameTest(unittest.TestCase):
    def test_raw_depth_is_near_bright_and_far_black(self):
        path = folder() / "depth.npy"
        np.save(path, np.array([[50.0, 10000.0], [np.inf, np.nan]]))
        frame = control_frame(path, "2x2")
        self.assertEqual((frame[0, 0, 0], frame[0, 1, 0], frame[1, 0, 0], frame[1, 1, 0]), (255, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
