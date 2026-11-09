"""Planned looks (city/bodies/looks.json) -> concrete MetaHuman wardrobe choices. Pure Python: no `unreal` import,
so it runs (and is unit-tested) without the editor; make_bodies.py imports it inside the editor.

    python3 city/bodies/metahuman/looks.py --check          # dry run: validate looks.json, print the plan
    python3 city/bodies/metahuman/looks.py --check --json   # same, machine-readable

The dry run validates the schema and resolves every slot against the wardrobe catalog it can see:
  - Core Data installed: the WI_*.uasset files under .../MetaHumanCharacter/Content/Optional/{Grooms/Bindings,Clothing}
    (the same folders the plugin's Config/Editor.ini WardrobeSections monitor), so every choice is a real item;
  - not installed: only the handful of wardrobe ids the plugin's own source and examples name (KNOWN_IDS). Most planned
    names can't be checked then, and the dry run says so per slot ("unverified").
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOOKS = HERE.parent / "looks.json"
ENGINE_PLUGIN = Path("/Users/Shared/Epic Games/UE_5.8/Engine/Plugins/MetaHuman/MetaHumanCharacter")
OPTIONAL = ENGINE_PLUGIN / "Content" / "Optional"

# Wardrobe slot -> folder under Optional/ (Config/Editor.ini WardrobeSections of the MetaHumanCharacter plugin).
SLOTS = {
    "hair": ("Hair", "Grooms/Bindings/Hair"),
    "eyebrows": ("Eyebrows", "Grooms/Bindings/Eyebrows"),
    "beard": ("Beard", "Grooms/Bindings/Beards"),
    "mustache": ("Mustache", "Grooms/Bindings/Mustaches"),
    "outfit": ("Outfits", "Clothing"),
}
GROOM_SLOTS = ("hair", "eyebrows", "beard", "mustache")
# Wardrobe ids the plugin names in its own files (examples, tests, eyelash table): all we can check without Core Data.
KNOWN_IDS = {
    "hair": ["WI_Hair_L_Straight", "WI_Hair_L_StraightBangs"],
    "outfit": ["WI_DefaultGarment"],
    "eyelashes": ["WI_Eyelashes_S_Thin", "WI_Eyelashes_S_Sparse", "WI_Eyelashes_S_Fine",
                  "WI_Eyelashes_L_ThickCurl", "WI_Eyelashes_L_SlightCurl", "WI_Eyelashes_L_Curl"],
}
HAIR_PARAMS = {"melanin": "Melanin", "redness": "Redness", "whiteness": "Whiteness", "lightness": "Lightness"}
UNIT = ("melanin", "redness", "whiteness", "lightness")


def core_data_installed(optional=OPTIONAL):
    """Same test as make_bodies.py / the editor: texture synthesis data present."""
    return (Path(optional) / "TextureSynthesis").is_dir()


def load(path=LOOKS):
    return json.loads(Path(path).read_text())


def validate(looks):
    """Schema check. Returns a list of problems (empty = valid)."""
    errs = []
    people = looks.get("people")
    if not isinstance(people, dict) or not people:
        return ["'people' must be a non-empty object"]
    for pid, p in people.items():
        where = f"people.{pid}"
        if not isinstance(p.get("age"), (int, float)) or not 1 <= p["age"] <= 110:
            errs.append(f"{where}.age must be a number of years")
        skin = p.get("skin")
        if not isinstance(skin, dict):
            errs.append(f"{where}.skin missing")
        else:
            for k in ("u", "v"):
                if not isinstance(skin.get(k), (int, float)) or not 0 <= skin[k] <= 1:
                    errs.append(f"{where}.skin.{k} must be 0..1")
            if not 0 <= skin.get("freckles", 0) <= 1:
                errs.append(f"{where}.skin.freckles must be 0..1")
            if not isinstance(skin.get("face_texture_index", 0), int) or skin.get("face_texture_index", 0) < 0:
                errs.append(f"{where}.skin.face_texture_index must be an int >= 0")
        for slot in SLOTS:
            if slot not in p:
                errs.append(f"{where}.{slot} missing (use null for none)")
                continue
            s = p[slot]
            if s is None:
                if slot in ("hair", "eyebrows"):
                    errs.append(f"{where}.{slot} must not be null (everyone has hair and brows here)")
                continue
            if not isinstance(s, dict) or not (s.get("items") or s.get("keywords")):
                errs.append(f"{where}.{slot} needs 'items' and/or 'keywords'")
                continue
            for k in ("items", "keywords", "fallback_keywords"):
                if k in s and not (isinstance(s[k], list) and all(isinstance(x, str) and x for x in s[k])):
                    errs.append(f"{where}.{slot}.{k} must be a list of names")
            if slot in GROOM_SLOTS:
                for k in UNIT:
                    if k in s and not (isinstance(s[k], (int, float)) and 0 <= s[k] <= 1):
                        errs.append(f"{where}.{slot}.{k} must be 0..1")
            if slot == "outfit":
                for name, rgb in (s.get("colors") or {}).items():
                    if not (isinstance(rgb, list) and len(rgb) == 3 and all(0 <= c <= 1 for c in rgb)):
                        errs.append(f"{where}.outfit.colors.{name} must be [r,g,b] 0..1")
        body = p.get("body")
        if body is not None:
            h = body.get("height")
            if h is not None and h != "min" and not (isinstance(h, (int, float)) and 120 <= h <= 220):
                errs.append(f"{where}.body.height must be cm or 'min'")
            for k in ("fat", "muscle", "fem"):
                if k in body and not 0 <= body[k] <= 1:
                    errs.append(f"{where}.body.{k} must be 0..1")
    return errs


def catalog_from_disk(optional=OPTIONAL):
    """{slot: [WI_* names]} from the installed Core Data, or None if it isn't installed."""
    optional = Path(optional)
    if not optional.is_dir():
        return None
    out = {}
    for slot, (_, folder) in SLOTS.items():
        d = optional / folder
        out[slot] = sorted(f.stem for f in d.rglob("WI_*.uasset")) if d.is_dir() else []
    return out


def _tokens(name):
    return [t.lower() for t in re.split(r"[_\W]+", name) if t]


def match(spec, names):
    """Pick a wardrobe item for one slot. Order: the first of spec['items'] that exists, then the item whose name
    contains all spec['keywords'] (as name tokens or substrings), then fallback_keywords, then the best partial
    keyword match. Returns (name or None, how)."""
    if not names:
        return None, "empty catalog"
    lower = {n.lower(): n for n in names}
    for item in spec.get("items", []):
        if item.lower() in lower:
            return lower[item.lower()], "item"

    def score(name, keys):
        toks, low = _tokens(name), name.lower()
        return sum(1 for k in keys if k.lower() in toks or (len(k) > 2 and k.lower() in low))

    for field in ("keywords", "fallback_keywords"):
        keys = spec.get(field) or []
        if keys:
            full = [n for n in names if score(n, keys) == len(keys)]
            if full:
                return sorted(full, key=len)[0], field
    keys = (spec.get("keywords") or []) + (spec.get("fallback_keywords") or [])
    best = max(names, key=lambda n: (score(n, keys), -len(n)))
    return (best, "partial") if keys and score(best, keys) > 0 else (None, "no match")


def plan(looks, catalog=None):
    """Concrete choices per person. catalog: {slot: [names]} (None = unknown: planned names are kept, unverified)."""
    out = {}
    for pid, p in looks["people"].items():
        rec = {"age": p["age"], "skin": p["skin"], "body": p.get("body"), "slots": {}}
        for slot, (ue_slot, folder) in SLOTS.items():
            s = p.get(slot)
            if s is None:
                continue
            entry = {"ue_slot": ue_slot, "package_path": f"/MetaHumanCharacter/Optional/{folder}"}
            if catalog is not None:
                name, how = match(s, catalog.get(slot, []))
                entry.update(item=name, how=how, verified=name is not None)
            else:
                known = KNOWN_IDS.get(slot, [])
                hit = next((i for i in s.get("items", []) if i in known), None)
                entry.update(item=hit or (s.get("items") or [None])[0], how="known id" if hit else "planned",
                             verified=bool(hit), keywords=s.get("keywords"))
            if slot in GROOM_SLOTS:
                entry["params"] = {HAIR_PARAMS[k]: s[k] for k in UNIT if k in s}
            else:
                entry["colors"] = s.get("colors", {})
            entry["desc"] = s.get("desc", "")
            rec["slots"][slot] = entry
        out[pid] = rec
    return out


def check(path=LOOKS, optional=OPTIONAL):
    looks = load(path)
    errs = validate(looks)
    cat = catalog_from_disk(optional) if core_data_installed(optional) else None
    report = {
        "looks": str(path),
        "valid": not errs,
        "errors": errs,
        "core_data": cat is not None,
        "catalog": "installed Core Data (Optional/)" if cat is not None else
                   "not installed: only the plugin's own known ids can be checked (KNOWN_IDS); other names are unverified",
        "plan": plan(looks, cat) if not errs else {},
    }
    if cat is not None:
        report["catalog_sizes"] = {k: len(v) for k, v in cat.items()}
    report["unresolved"] = [f"{pid}.{slot}" for pid, r in report["plan"].items()
                            for slot, e in r["slots"].items() if not e.get("item")]
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate looks.json and print the plan (dry run)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--looks", default=str(LOOKS))
    ap.add_argument("--optional", default=str(OPTIONAL), help="MetaHumanCharacter Content/Optional dir")
    a = ap.parse_args(argv)
    r = check(a.looks, a.optional)
    if a.json:
        print(json.dumps(r, indent=1))
    else:
        print(f"looks.json: {'valid' if r['valid'] else 'INVALID'}; catalog: {r['catalog']}")
        for e in r["errors"]:
            print("  error:", e)
        for pid, rec in r["plan"].items():
            parts = ", ".join(f"{s}={e.get('item') or '?'}{'' if e.get('verified') else ' (unverified)'}"
                              for s, e in rec["slots"].items())
            print(f"  {pid:6s} age {rec['age']:>3}: {parts}")
        if r["core_data"] and r["unresolved"]:
            print("  unresolved:", ", ".join(r["unresolved"]))
    return 0 if r["valid"] and not (r["core_data"] and r["unresolved"]) else 1


if __name__ == "__main__":
    sys.exit(main())
