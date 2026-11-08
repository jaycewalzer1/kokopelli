"""Planned looks and wardrobe parts (city/bodies, wave 2b), testable before MetaHuman Creator Core Data exists.

city/bodies/looks.json (who wears what), city/bodies/metahuman/looks.py (validation + wardrobe matching, the dry run),
city/bodies/write_parts.py (assembly report -> Bodies.json grooms/outfit), city/bodies/apply_core_data.sh (guard).
No Unreal, no server.

    .venv/bin/python -m unittest tests/test_city_bodies_looks.py -v
"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "city" / "bodies" / "metahuman"))
sys.path.insert(0, str(ROOT / "city" / "bodies"))

import looks  # noqa: E402
import write_parts  # noqa: E402

LOOKS = looks.load()
PEOPLE = ("mara", "iris", "ana", "tomas", "wen", "priya", "kai")
# A wardrobe the size and naming style of Epic's (WI_<Slot>_<S|M|L>_<Style>), standing in for the Core Data catalog.
FAKE_CATALOG = {
    "hair": ["WI_Hair_L_Straight", "WI_Hair_L_StraightBangs", "WI_Hair_L_Wavy", "WI_Hair_S_Afro", "WI_Hair_M_Ponytail",
             "WI_Hair_S_Crop", "WI_Hair_S_Receding", "WI_Hair_M_Bun", "WI_Hair_S_Messy"],
    "eyebrows": ["WI_Eyebrows_Natural", "WI_Eyebrows_Thick", "WI_Eyebrows_Sparse", "WI_Eyebrows_Thin"],
    "beard": ["WI_Beard_S_Stubble", "WI_Beard_M_Full"],
    "mustache": ["WI_Mustache_S_Thin"],
    "outfit": ["WI_DefaultGarment", "WI_Overalls", "WI_Cardigan_Knit", "WI_Apron_Canvas", "WI_Tunic_Long", "WI_Tshirt_Shorts"],
}


class LooksJson(unittest.TestCase):
    def test_valid_and_complete(self):
        self.assertEqual(looks.validate(LOOKS), [])
        self.assertEqual(set(LOOKS["people"]), set(PEOPLE))

    def test_varied_people(self):
        p = LOOKS["people"]
        ages = [p[i]["age"] for i in PEOPLE]
        tones = [p[i]["skin"]["u"] for i in PEOPLE]
        self.assertGreaterEqual(max(ages) - min(ages), 40)
        self.assertGreaterEqual(max(tones) - min(tones), 0.4, "skin tones should span light to dark")
        self.assertEqual(len({p[i]["hair"]["desc"] for i in PEOPLE}), len(PEOPLE), "everyone gets a different hair")

    def test_wen_oldest_and_greyest_kai_youngest(self):
        p = LOOKS["people"]
        self.assertEqual(max(PEOPLE, key=lambda i: p[i]["age"]), "wen")
        self.assertEqual(max(PEOPLE, key=lambda i: p[i]["hair"].get("whiteness", 0)), "wen")
        self.assertEqual(min(PEOPLE, key=lambda i: p[i]["age"]), "kai")
        self.assertEqual(p["kai"]["body"]["height"], "min", "kai: as young as the sliders allow")

    def test_validation_catches_mistakes(self):
        bad = copy.deepcopy(LOOKS)
        bad["people"]["mara"]["skin"]["u"] = 1.5
        bad["people"]["iris"]["hair"] = None
        bad["people"]["ana"]["outfit"] = {"desc": "no ids"}
        del bad["people"]["tomas"]["beard"]
        bad["people"]["wen"]["hair"]["whiteness"] = 2
        errs = "\n".join(looks.validate(bad))
        for frag in ("mara.skin.u", "iris.hair must not be null", "ana.outfit needs", "tomas.beard missing", "wen.hair.whiteness"):
            self.assertIn(frag, errs)


class Matching(unittest.TestCase):
    def test_exact_item_first(self):
        self.assertEqual(looks.match({"items": ["WI_Hair_S_Afro"], "keywords": ["L"]}, FAKE_CATALOG["hair"]), ("WI_Hair_S_Afro", "item"))

    def test_keywords_all_then_fallback_then_partial(self):
        self.assertEqual(looks.match({"keywords": ["L", "Wavy"]}, FAKE_CATALOG["hair"])[0], "WI_Hair_L_Wavy")
        self.assertEqual(looks.match({"keywords": ["Hoodie"], "fallback_keywords": ["Apron"]}, FAKE_CATALOG["outfit"]),
                         ("WI_Apron_Canvas", "fallback_keywords"))
        self.assertEqual(looks.match({"keywords": ["Knit", "Wool"]}, FAKE_CATALOG["outfit"]), ("WI_Cardigan_Knit", "partial"))
        self.assertEqual(looks.match({"keywords": ["Kilt"]}, FAKE_CATALOG["outfit"]), (None, "no match"))
        self.assertEqual(looks.match({"keywords": ["x"]}, []), (None, "empty catalog"))

    def test_plan_resolves_everyone_against_a_full_catalog(self):
        plan = looks.plan(LOOKS, FAKE_CATALOG)
        for pid in PEOPLE:
            for slot, e in plan[pid]["slots"].items():
                self.assertTrue(e["item"], f"{pid}.{slot} unresolved")
        self.assertEqual(plan["tomas"]["slots"]["beard"]["item"], "WI_Beard_M_Full")
        self.assertEqual(plan["wen"]["slots"]["hair"]["params"]["Whiteness"], LOOKS["people"]["wen"]["hair"]["whiteness"])
        self.assertNotIn("beard", plan["mara"]["slots"])

    def test_plan_without_core_data_marks_unverified(self):
        plan = looks.plan(LOOKS, None)
        self.assertTrue(plan["mara"]["slots"]["hair"]["verified"])  # WI_Hair_L_Straight is named by the plugin itself
        self.assertFalse(plan["iris"]["slots"]["hair"]["verified"])

    def test_dry_run_cli(self):
        with tempfile.TemporaryDirectory() as d:  # an empty Optional dir: Core Data absent
            r = subprocess.run([sys.executable, str(ROOT / "city/bodies/metahuman/looks.py"), "--check", "--json",
                                "--optional", d], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertTrue(out["valid"])
            self.assertFalse(out["core_data"])
            # fake Core Data: TextureSynthesis + the wardrobe folders with WI_ files
            opt = Path(d)
            (opt / "TextureSynthesis").mkdir()
            for slot, (_, folder) in looks.SLOTS.items():
                (opt / folder).mkdir(parents=True, exist_ok=True)
                for n in FAKE_CATALOG[slot]:
                    (opt / folder / f"{n}.uasset").write_bytes(b"")
            r = subprocess.run([sys.executable, str(ROOT / "city/bodies/metahuman/looks.py"), "--check", "--json",
                                "--optional", d], capture_output=True, text=True)
            out = json.loads(r.stdout)
            self.assertEqual(r.returncode, 0, out["unresolved"])
            self.assertTrue(out["core_data"])
            self.assertEqual(out["unresolved"], [])


def tier(parts):
    return {"parts": parts}


H = "/Game/Characters/Bodies/tomas/High/tomas_high"
L = "/Game/Characters/Bodies/tomas/Low/tomas_low"
REPORT = {"bodies": {
    "tomas": {
        "high": tier([
            {"path": f"{H}/Grooms/GR_Hair.GR_Hair", "class": "GroomAsset", "geometry": ["strands", "cards"]},
            {"path": f"{H}/Grooms/GB_Hair.GB_Hair", "class": "GroomBindingAsset", "groom": f"{H}/Grooms/GR_Hair.GR_Hair"},
            {"path": f"{H}/Grooms/GR_Beard.GR_Beard", "class": "GroomAsset", "geometry": ["strands"]},
            {"path": f"{H}/Grooms/GB_Beard.GB_Beard", "class": "GroomBindingAsset", "groom": f"{H}/Grooms/GR_Beard.GR_Beard"},
            {"path": f"{H}/Grooms/GR_Peachfuzz.GR_Peachfuzz", "class": "GroomAsset", "geometry": ["strands"]},
            {"path": f"{H}/Clothing/SKM_Apron", "class": "SkeletalMesh"},
        ]),
        "low": tier([
            {"path": f"{L}/Grooms/GR_Hair.GR_Hair", "class": "GroomAsset", "geometry": ["cards"]},
            {"path": f"{L}/Grooms/GB_Hair.GB_Hair", "class": "GroomBindingAsset", "groom": f"{L}/Grooms/GR_Hair.GR_Hair"},
            {"path": f"{L}/Grooms/GR_Beard.GR_Beard", "class": "GroomAsset", "geometry": ["strands"]},
            {"path": f"{L}/Grooms/GR_Peachfuzz.GR_Peachfuzz", "class": "GroomAsset", "geometry": ["meshes"]},
            {"path": f"{L}/Grooms/SKM_Eyebrows_Helmet", "class": "SkeletalMesh"},
            {"path": f"{L}/Clothing/CO_Apron", "class": "ChaosOutfitAsset"},
        ]),
    },
    "kai": {"height_min": 135.0, "body_constraints": {"Height": 135.2}, "high": tier([]), "low": tier([])},
}}


class WriteParts(unittest.TestCase):
    def setUp(self):
        self.bodies = json.loads((ROOT / "mac_server" / "Config" / "Bodies.json").read_text())

    def test_high_gets_strands_grooms_and_outfit(self):
        changed, _ = write_parts.update(REPORT, self.bodies)
        b = self.bodies["bodies"]["tomas"]
        self.assertEqual([g["slot"] for g in b["grooms"]], ["hair", "beard", "peachfuzz"])
        hair = b["grooms"][0]
        self.assertEqual((hair["groom"], hair["binding"], hair["attach"], hair["geometry"]),
                         (f"{H}/Grooms/GR_Hair.GR_Hair", f"{H}/Grooms/GB_Hair.GB_Hair", "face", "strands"))
        self.assertEqual(b["outfit"], [{"slot": "outfit", "mesh": f"{H}/Clothing/SKM_Apron.SKM_Apron", "attach": "body"}])
        self.assertIn("tomas", changed)

    def test_low_never_strands(self):
        _, notes = write_parts.update(REPORT, self.bodies)
        b = self.bodies["bodies"]["tomas_low"]
        slots = {g["slot"]: g for g in b["grooms"]}
        self.assertEqual(set(slots), {"hair", "eyebrows"})          # beard strands-only and peach fuzz left out
        self.assertEqual(slots["hair"]["geometry"], "cards")
        self.assertEqual(slots["eyebrows"]["geometry"], "helmet")
        self.assertTrue(all(g.get("geometry") in ("cards", "helmet") for g in b["grooms"]))
        self.assertTrue(any("strands only" in n for n in notes) and any("ChaosOutfitAsset plugin" in n for n in notes))

    def test_kai_height_follows_slider_floor_and_rest_untouched(self):
        before = copy.deepcopy(self.bodies)
        write_parts.update(REPORT, self.bodies)
        self.assertEqual(self.bodies["bodies"]["kai"]["height_cm"], 135)
        self.assertEqual(self.bodies["bodies"]["kai_low"]["height_cm"], 135)
        for bid in ("mara", "iris_low", "standin_near", "manny", "test_parts"):
            self.assertEqual(self.bodies["bodies"][bid], before["bodies"][bid])
        self.assertEqual({k: v for k, v in self.bodies.items() if k != "bodies"},
                         {k: v for k, v in before.items() if k != "bodies"})

    def test_cli_dry_run_leaves_file(self):
        with tempfile.TemporaryDirectory() as d:
            rep, bj = Path(d) / "r.json", Path(d) / "b.json"
            rep.write_text(json.dumps(REPORT))
            bj.write_text(json.dumps(self.bodies))
            r = subprocess.run([sys.executable, str(ROOT / "city/bodies/write_parts.py"), "--report", str(rep), "--bodies",
                                str(bj), "--dry-run"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(bj.read_text()), self.bodies)
            r = subprocess.run([sys.executable, str(ROOT / "city/bodies/write_parts.py"), "--report", str(rep), "--bodies",
                                str(bj), "--out", str(Path(d) / "w.json")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("grooms", json.loads(bj.read_text())["bodies"]["tomas"])


class ApplyScript(unittest.TestCase):
    def test_apply_core_data_refuses_without_core_data(self):
        script = ROOT / "city" / "bodies" / "apply_core_data.sh"
        self.assertTrue(script.exists())
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run(["bash", str(script), "--check-only"], capture_output=True, text=True,
                               env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "CORE_DATA_DIR": d + "/none"})
            self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
            self.assertIn("Core Data", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
