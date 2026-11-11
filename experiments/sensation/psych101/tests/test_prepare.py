"""Psych-101 conversion and the hold-out filter, on made-up sessions. No real data, no model, seconds.

    tools/fable/test_all.sh experiments/sensation/psych101/tests
"""
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from experiments.sensation.psych101 import prepare


def session(experiment, participant, trials=6, opening="You choose between two machines, F and J.\nPress a key.\n\n", line=None):
    """A made-up session in Psych-101's shape: instructions, then one line per trial with the choice in << >>."""
    line = line or (lambda trial: f"Trial {trial}: you press <<{'FJ'[trial % 2]}>> and get {trial} points.\n")
    return {"text": opening + "".join(line(trial) for trial in range(trials)), "experiment": experiment, "participant": participant}


DICTATOR = "You are given 10 dollars. Decide how much to give to the other participant.\n\n"
FEEDING = "You are hungry. Choose a snack to eat.\n\n"
MACHINES = "Pick the slot machine that will give you the most points.\n\n"


def made_up_file(folder, people=40):
    rows = []
    for person in range(people):
        rows.append(session("lab2020dictator/exp1.csv", person, opening=DICTATOR,
                            line=lambda trial: f"Round {trial}: you send <<{trial}>> dollars.\n"))
        rows.append(session("lab2021snack/exp1.csv", person, opening=FEEDING))
        rows.append(session("lab2022bandit/exp1.csv", person, opening=MACHINES))
        rows.append(session("lab2023shapes/exp1.csv", person))
        rows.append(session("lab2023shapes/exp2.csv", person))
    path = Path(folder) / "made_up.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def rulings(folder, held=("lab2020dictator", "lab2021snack"), kept=("lab2022bandit",)):
    path = Path(folder) / "held_out.yaml"
    path.write_text(yaml.safe_dump({
        "held_out": [{"experiment": name, "reason": f"{name} is about giving or food"} for name in held],
        "kept_after_review": [{"experiment": name, "reason": "the machine gives points; nobody gives anything away"} for name in kept]}))
    return path


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


class RowTest(unittest.TestCase):
    def test_the_answer_is_the_choice_and_the_prompt_stops_just_before_it(self):
        made = session("lab/exp.csv", 1, trials=3)
        rows = prepare.rows_from(made, per_session=3)
        self.assertEqual([row["messages"][1]["content"] for row in rows], ["F", "J", "F"])
        second = rows[1]["messages"][0]["content"]
        self.assertTrue(second.endswith("Trial 1: you press"), second[-40:])
        self.assertIn("Trial 0: you press F and get 0 points.", second)   # earlier choices are history, unwrapped
        self.assertNotIn("<<", second)
        self.assertNotIn("and get 1 points", second)                      # what followed the choice isn't shown
        self.assertNotIn("Trial 2", second)

    def test_the_instructions_survive_when_a_long_session_is_cut(self):
        made = session("lab/exp.csv", 1, trials=400)
        choices = list(prepare.CHOICE.finditer(made["text"]))
        prompt = prepare.context(made["text"], choices[-1].start(), max_chars=600)
        self.assertLessEqual(len(prompt), 600 + len(prepare.CUT) + 1)
        self.assertTrue(prompt.startswith("You choose between two machines, F and J."))
        self.assertIn(f"\n{prepare.CUT}\nTrial ", prompt)                  # the gap is marked, and history resumes on a whole line
        self.assertTrue(prompt.endswith("Trial 399: you press"))
        self.assertNotIn("Trial 5:", prompt)

    def test_a_short_session_is_kept_whole(self):
        made = session("lab/exp.csv", 1, trials=3)
        choices = list(prepare.CHOICE.finditer(made["text"]))
        self.assertNotIn(prepare.CUT, prepare.context(made["text"], choices[-1].start(), max_chars=600))

    def test_a_session_with_no_line_breaks_is_still_bounded(self):
        made = session("lab/exp.csv", 1, trials=300, opening="", line=lambda trial: f"You press <<{trial}>> then ")
        choices = list(prepare.CHOICE.finditer(made["text"]))
        prompt = prepare.context(made["text"], choices[-1].start(), max_chars=400)
        self.assertLessEqual(len(prompt), 400 + len(prepare.CUT) + 1)
        self.assertTrue(prompt.endswith("You press"))

    def test_the_same_choices_are_picked_every_time_and_never_more_than_asked(self):
        first = prepare.picked(200, 4, "lab/exp.csv", 7)
        self.assertEqual(first, prepare.picked(200, 4, "lab/exp.csv", 7))
        self.assertEqual(first, sorted(set(first)))
        self.assertEqual(len(first), 4)
        self.assertNotEqual(first, prepare.picked(200, 4, "lab/exp.csv", 8))
        self.assertEqual(prepare.picked(3, 4, "lab/exp.csv", 7), [0, 1, 2])

    def test_rows_are_in_the_format_the_trainer_reads(self):
        row = prepare.rows_from(session("lab/exp.csv", 1), per_session=1)[0]
        self.assertEqual([message["role"] for message in row["messages"]], ["user", "assistant"])
        # mlx-vlm treats these keys as media to load, so a row must never carry them.
        self.assertFalse({"image", "images", "audio", "audios", "video", "videos"} & set(row))


class SplitTest(unittest.TestCase):
    def test_a_person_is_always_on_the_same_side(self):
        self.assertEqual(prepare.split_of("lab/exp.csv", 12), prepare.split_of("lab/exp.csv", 12))

    def test_about_one_in_twenty_people_validate(self):
        sides = [prepare.split_of("lab/exp.csv", person) for person in range(4000)]
        self.assertTrue(0.035 < sides.count("validation") / len(sides) < 0.065)

    def test_round_robin_puts_every_experiment_in_the_first_rows(self):
        order = prepare.interleave({"b": ["b0", "b1", "b2"], "a": ["a0"], "c": ["c0", "c1"]})
        self.assertEqual(order, ["a0", "b0", "c0", "b1", "c1", "b2"])


class ScreenTest(unittest.TestCase):
    def test_it_finds_whole_words_and_phrases_whatever_the_case(self):
        hits = prepare.screen("Decide how much to DONATE to the Other Participant. Then eat.")
        self.assertEqual(hits, {"food": ["eat"], "giving": ["donate", "other participant"]})

    def test_it_doesnt_match_inside_other_words(self):
        self.assertEqual(prepare.screen("You get feedback on a great offering after sharpening the affair."), {})

    def test_every_match_must_be_ruled_on(self):
        lists = {"held_out": {"lab2020dictator": "x"}, "kept_after_review": {"lab2022bandit/exp1.csv": "y"}}
        hits = {"lab2020dictator/exp1.csv": {"giving": ["give"]}, "lab2022bandit/exp1.csv": {"giving": ["give"]},
                "lab2022bandit/exp2.csv": {"giving": ["give"]}, "lab2023shapes/exp1.csv": {}}
        # A study name covers all its experiments; a full id covers only itself.
        self.assertEqual(list(prepare.unreviewed(hits, lists)), ["lab2022bandit/exp2.csv"])


class HeldOutListTest(unittest.TestCase):
    def test_an_entry_without_a_reason_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "held_out.yaml"
            path.write_text(yaml.safe_dump({"held_out": [{"experiment": "lab2020dictator", "reason": " "}]}))
            with self.assertRaises(ValueError):
                prepare.load_held_out(path)

    def test_an_experiment_cant_be_both_held_out_and_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                prepare.load_held_out(rulings(folder, held=("lab2020dictator",), kept=("lab2020dictator",)))

    def test_the_tracked_list_loads_and_every_ruling_has_a_reason(self):
        lists = prepare.load_held_out()
        self.assertIn("ludwig2023human", lists["held_out"])
        self.assertTrue(all(len(reason) > 20 for key in ("held_out", "kept_after_review") for reason in lists[key].values()))
        self.assertEqual(set(lists["tiers"]), set(lists["held_out"]))


class ConvertTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = made_up_file(cls.root)
        cls.out = cls.root / "data"
        cls.manifest = prepare.convert(cls.source, cls.out, rulings(cls.root), per_session=2, max_chars=300, pilot_per_experiment=5)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_no_held_out_experiment_reaches_training_or_validation(self):
        for name in ("train", "validation", "pilot/train", "pilot/validation"):
            studies = {prepare.study(row["experiment"]) for row in read(self.out / "lora" / f"{name}.jsonl")}
            self.assertTrue(studies, name)
            self.assertFalse(studies & {"lab2020dictator", "lab2021snack"}, name)

    def test_held_out_experiments_go_to_their_own_file_and_nowhere_else(self):
        studies = {prepare.study(row["experiment"]) for row in read(self.out / "lora" / "transfer_held_out.jsonl")}
        self.assertEqual(studies, {"lab2020dictator", "lab2021snack"})

    def test_nobody_is_in_both_train_and_validation(self):
        people = {name: {(row["experiment"], row["participant"]) for row in read(self.out / "lora" / f"{name}.jsonl")}
                  for name in ("train", "validation")}
        self.assertFalse(people["train"] & people["validation"])
        self.assertTrue(people["validation"])

    def test_the_counts_add_up(self):
        rows = self.manifest["rows"]
        self.assertEqual(rows["train"]["rows"] + rows["validation"]["rows"], 40 * 3 * 2)   # 3 kept experiments, 2 choices each
        self.assertEqual(rows["transfer_held_out"]["rows"], 40 * 2 * 2)
        self.assertEqual(self.manifest["in_the_file"], {"experiments": 5, "sessions": 200, "choices": 1200,
                                                        "chars": sum(len(row["text"]) for row in read(self.source))})

    def test_the_pilot_sample_is_small_fixed_and_spread_over_experiments(self):
        pilot = read(self.out / "lora" / "pilot" / "train.jsonl")
        self.assertEqual(len(pilot), 3 * 5)
        self.assertEqual(len({row["experiment"] for row in pilot[:3]}), 3)
        whole = {json.dumps(row, sort_keys=True) for row in read(self.out / "lora" / "train.jsonl")}
        self.assertTrue(all(json.dumps(row, sort_keys=True) in whole for row in pilot))

    def test_the_held_out_list_is_written_beside_the_data_with_reasons_and_cost(self):
        report = json.loads((self.out / "held_out.json").read_text())
        self.assertEqual({entry["experiment"] for entry in report["held_out"]}, {"lab2020dictator", "lab2021snack"})
        self.assertTrue(all(entry["reason"] and entry["covers"] for entry in report["held_out"]))
        self.assertEqual(report["cost"]["experiments"], 2)
        self.assertEqual(report["cost"]["of_experiments"], 5)
        self.assertEqual((report["cost"]["sessions"], report["cost"]["of_sessions"]), (80, 200))
        self.assertEqual(report["kept_after_review"][0]["experiment"], "lab2022bandit")

    def test_converting_again_gives_the_same_bytes(self):
        again = prepare.convert(self.source, self.root / "again", rulings(self.root), per_session=2, max_chars=300, pilot_per_experiment=5)
        self.assertEqual(again["files"], self.manifest["files"])

    def test_an_unreviewed_match_stops_everything_before_a_file_is_written(self):
        out = self.root / "refused"
        with self.assertRaises(SystemExit) as stopped:
            prepare.convert(self.source, out, rulings(self.root, kept=()), per_session=2)
        self.assertIn("lab2022bandit/exp1.csv", str(stopped.exception))
        self.assertFalse(out.exists())

    def test_a_ruling_on_an_experiment_that_isnt_there_is_refused(self):
        out = self.root / "typo"
        with self.assertRaises(SystemExit) as stopped:
            prepare.convert(self.source, out, rulings(self.root, held=("lab2020dictator", "lab2021snack", "lab2020dictater")))
        self.assertIn("lab2020dictater", str(stopped.exception))
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
