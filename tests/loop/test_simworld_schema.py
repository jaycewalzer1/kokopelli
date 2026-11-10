"""Action schema and formulas. Needs only pydantic, so it also runs in the root .venv."""
import json
import re
import typing
import unittest
from pathlib import Path

from pydantic import ValidationError

from kokopelli.loop import physics
from kokopelli.loop.physics import (ACTION_CATALOG, Action, Interact, LookAt, MoveTo, Rotation, Speak, Vec3, action_json_schema,
                             parse_action)

TARGETS = {"npc_0": "npc", "mug_0": "object", "scooter_0": "scooter", "bench_0": "seat", "car_0": "vehicle"}


class SchemaTest(unittest.TestCase):
    def rejects(self, raw, targets=TARGETS):
        with self.assertRaises(ValidationError):
            parse_action(raw, targets)

    def test_parses_into_the_right_class(self):
        self.assertIsInstance(parse_action({"type": "move_to", "position": {"x": 1, "y": 2, "z": 3}}), MoveTo)
        self.assertIsInstance(parse_action({"type": "look_at", "target_id": "npc_0"}, TARGETS), LookAt)
        self.assertIsInstance(parse_action({"type": "speak", "text": "hello"}), Speak)
        self.assertIsInstance(parse_action('{"type": "interact", "target_id": "mug_0"}', TARGETS), Interact)

    def test_rejects_unknown_action(self):
        self.rejects({"type": "fly"})
        self.rejects({"text": "no type at all"})

    def test_rejects_extra_and_bad_arguments(self):
        self.rejects({"type": "wait", "seconds": 5})
        self.rejects({"type": "rotate", "angle_deg": 90})  # direction missing
        self.rejects({"type": "rotate", "angle_deg": -90, "direction": "left"})
        self.rejects({"type": "rotate", "angle_deg": 90, "direction": "up"})
        self.rejects({"type": "step_forward", "duration_s": 31})
        self.rejects({"type": "step_forward", "duration_s": 0})
        self.rejects({"type": "set_speed", "speed_cm_s": 0})
        self.rejects({"type": "speak", "text": ""})
        self.rejects({"type": "speak", "text": "   "})
        self.rejects({"type": "speak", "text": "x" * 501})
        self.rejects({"type": "drive", "throttle": 2})
        self.rejects({"type": "gesture", "kind": "dance"})
        self.rejects({"type": "move_to", "position": {"x": float("nan"), "y": 0, "z": 0}})

    def test_move_to_needs_exactly_one_goal(self):
        self.rejects({"type": "move_to"})
        self.rejects({"type": "move_to", "position": {"x": 0, "y": 0, "z": 0}, "target_id": "npc_0"})
        self.rejects({"type": "look_at"})

    def test_rejects_unknown_target_ids(self):
        self.rejects({"type": "move_to", "target_id": "ghost"})
        self.rejects({"type": "look_at", "target_id": "ghost"})
        self.rejects({"type": "interact", "target_id": "ghost"})
        self.rejects({"type": "pick_up", "target_id": "ghost"})

    def test_rejects_targets_of_the_wrong_kind(self):
        self.rejects({"type": "pick_up", "target_id": "npc_0"})
        self.rejects({"type": "get_on_scooter", "target_id": "mug_0"})
        self.rejects({"type": "enter_vehicle", "target_id": "scooter_0"})
        self.rejects({"type": "interact", "target_id": "npc_0"})  # no native NPC interaction exists

    def test_target_check_is_skipped_without_a_target_list(self):
        self.assertEqual(parse_action({"type": "pick_up", "target_id": "anything"}).target_id, "anything")

    def test_round_trips_through_json(self):
        original = parse_action({"type": "move_to", "target_id": "npc_0", "arrival_radius_cm": 80}, TARGETS)
        self.assertEqual(parse_action(json.loads(original.model_dump_json()), TARGETS), original)

    def test_every_action_has_a_catalog_entry_and_the_reverse(self):
        members = typing.get_args(typing.get_args(Action)[0])
        names = {cls.model_fields["type"].default for cls in members}
        self.assertEqual(names, set(ACTION_CATALOG))
        for name in ("move_to", "look_at", "interact", "speak", "wait"):
            self.assertIn(name, names)

    def test_catalog_is_honest_about_the_requested_actions(self):
        self.assertEqual(ACTION_CATALOG["speak"].mapping, "no_physics")
        self.assertEqual(ACTION_CATALOG["move_to"].mapping, "composed")
        self.assertEqual(ACTION_CATALOG["look_at"].mapping, "composed")
        self.assertEqual(ACTION_CATALOG["interact"].mapping, "composed")
        self.assertEqual(ACTION_CATALOG["sit_down"].mapping, "native")

    def test_simworld_md_lists_each_action_under_its_real_mapping(self):
        doc = (Path(physics.__file__).parent / "SIMWORLD.md").read_text()
        headings = {"native": "**Native**", "composed": "**Composed**", "no_physics": "**No physics effect:**"}
        for mapping, heading in headings.items():
            line = next(text for text in doc.splitlines() if text.startswith(heading))
            listed = set(re.findall(r"`(\w+)`", line))
            self.assertEqual(listed, {name for name, spec in ACTION_CATALOG.items() if spec.mapping == mapping}, mapping)

    def test_json_schema_is_exportable(self):
        schema = action_json_schema()
        self.assertEqual(schema["discriminator"]["propertyName"], "type")
        json.dumps(schema)

    def test_physics_module_needs_only_pydantic(self):
        source = open(physics.__file__).read()
        for heavy in ("import numpy", "import unrealcv", "import cv2", "from simworld", "import simworld"):
            self.assertNotIn(heavy, source)
        self.assertEqual(Vec3(x=1, y=2, z=3).x, 1)
        self.assertEqual(Rotation(pitch=0, yaw=1, roll=0).yaw, 1)


if __name__ == "__main__":
    unittest.main()
