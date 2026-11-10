#!/usr/bin/env python3
"""Bodies.json grooms + outfit from what the MetaHuman assembly produced (wave 2b).

    python3 tools/bodies/write_parts.py [--report out/bodies/make/make_report_all.json] [--bodies mac_server/Config/Bodies.json] [--dry-run]

make_bodies.py records, per person and tier (High = near body <id>, Low = far body <id>_low), every groom, groom
binding, outfit and extra skeletal mesh the UE Optimized assembly wrote (`parts` in the report). This turns them into
Bodies.json parts the server attaches (SWCharacterBase::BuildParts):
  - a GroomBindingAsset gives slot (from its name), groom and binding; grooms attach to the face (the binding's target)
  - Low bodies: a groom only goes in if it has a cards or helmet (meshes) LOD, marked geometry "cards"/"helmet";
    strands-only grooms are left out (the server would skip them anyway); peach fuzz is left out of Low
  - outfits: clothing skeletal meshes, or Chaos outfit assets (need the ChaosOutfitAsset plugin in mac_server: noted)
  - the person's height_cm follows the report when make_bodies set it from a slider floor ("min", kai)
Only the grooms/outfit/height_cm keys of the people in the report change; everything else in Bodies.json is kept.
Writes out/bodies/write_parts.json (what changed, and notes).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "out" / "bodies" / "make" / "make_report_all.json"
BODIES = ROOT / "mac_server" / "Config" / "Bodies.json"
SLOT_WORDS = [("eyebrow", "eyebrows"), ("eyelash", "eyelashes"), ("mustache", "mustache"), ("moustache", "mustache"),
              ("beard", "beard"), ("peachfuzz", "peachfuzz"), ("fuzz", "peachfuzz"), ("hair", "hair")]
GROOM_ORDER = ["hair", "eyebrows", "eyelashes", "beard", "mustache", "peachfuzz"]


def obj_path(p):
    """'/Game/a/B' or '/Game/a/B.B' -> '/Game/a/B.B' (Bodies.json uses object paths)."""
    p = p.split(":")[0]
    if "." in p.rsplit("/", 1)[-1]:
        return p
    return f"{p}.{p.rsplit('/', 1)[-1]}"


def slot_of(path):
    name = path.rsplit("/", 1)[-1].lower()
    for word, slot in SLOT_WORDS:
        if word in name:
            return slot
    return None


def parts_for(tier_rep, low):
    """(grooms, outfit, notes) for one assembled tier."""
    notes = []
    parts = tier_rep.get("parts") or []
    grooms_by_path = {obj_path(p["path"]): p for p in parts if p["class"] == "GroomAsset"}
    used = set()
    grooms = []
    for b in (p for p in parts if p["class"] == "GroomBindingAsset"):
        g = obj_path(b["groom"]) if b.get("groom") else None
        slot = slot_of(b["path"]) or (slot_of(g) if g else None)
        if not g or not slot:
            notes.append(f"binding {b['path']}: no groom or slot; skipped")
            continue
        used.add(g)
        grooms.append((slot, g, obj_path(b["path"]), grooms_by_path.get(g, {}).get("geometry")))
    for g, p in grooms_by_path.items():  # grooms without a binding (rigid on the head)
        if g not in used and slot_of(g):
            grooms.append((slot_of(g), g, None, p.get("geometry")))
    out_grooms = []
    for slot, g, binding, geom in sorted(grooms, key=lambda t: GROOM_ORDER.index(t[0]) if t[0] in GROOM_ORDER else 99):
        entry = {"slot": slot, "groom": g, "attach": "face"}
        if binding:
            entry["binding"] = binding
        geom = geom if isinstance(geom, list) else []
        if low:
            if slot == "peachfuzz":
                notes.append(f"{g}: peach fuzz left out of the Low body")
                continue
            cheap = [x for x in geom if x in ("cards", "meshes")]
            if geom and not cheap:
                notes.append(f"{g}: strands only, left out of the Low body (no cards/helmet LOD)")
                continue
            entry["geometry"] = "helmet" if cheap == ["meshes"] else "cards"
        elif geom:
            entry["geometry"] = "strands" if "strands" in geom else ("cards" if "cards" in geom else "helmet")
        out_grooms.append(entry)
    outfit = []
    for p in parts:
        if p["class"] == "SkeletalMesh" and not slot_of(p["path"]):  # hair helmets/cards as meshes carry a slot word
            outfit.append({"slot": "outfit", "mesh": obj_path(p["path"]), "attach": "body"})
        elif p["class"] == "SkeletalMesh":
            out_grooms.append({"slot": slot_of(p["path"]), "mesh": obj_path(p["path"]), "attach": "face",
                               **({"geometry": "helmet"} if low else {})})
        elif p["class"] in ("ChaosOutfitAsset", "ChaosClothAsset"):
            outfit.append({"slot": "outfit", "mesh": obj_path(p["path"]), "attach": "body"})
            notes.append(f"{p['path']}: Chaos outfit asset; mac_server needs the ChaosOutfitAsset plugin enabled to "
                         f"cook and draw it (the server skips it with a warning otherwise)")
    return out_grooms, outfit, notes


def update(report, bodies, people=None):
    changed, notes = {}, []
    for pid, rep in report.get("bodies", {}).items():
        if people and pid not in people:
            continue
        for tier, bid, low in (("high", pid, False), ("low", f"{pid}_low", True)):
            if tier not in rep or bid not in bodies["bodies"]:
                continue
            grooms, outfit, n = parts_for(rep[tier], low)
            notes += [f"{bid}: {x}" for x in n]
            b = bodies["bodies"][bid]
            before = (b.get("grooms"), b.get("outfit"))
            if grooms:
                b["grooms"] = grooms
            else:
                b.pop("grooms", None)
            if outfit:
                b["outfit"] = outfit
            else:
                b.pop("outfit", None)
            h = (rep.get("body_constraints") or {}).get("Height")
            if rep.get("height_min") is not None and h:
                if b.get("height_cm") != round(h):
                    changed.setdefault(bid, {})["height_cm"] = [b.get("height_cm"), round(h)]
                b["height_cm"] = round(h)
            if before != (b.get("grooms"), b.get("outfit")):
                changed.setdefault(bid, {})["parts"] = {"grooms": len(grooms), "outfit": len(outfit)}
    return changed, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", default=str(REPORT))
    ap.add_argument("--bodies", default=str(BODIES))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "out" / "bodies" / "write_parts.json"))
    a = ap.parse_args(argv)
    report = json.loads(Path(a.report).read_text())
    bodies = json.loads(Path(a.bodies).read_text())
    changed, notes = update(report, bodies)
    summary = {"report": a.report, "bodies": a.bodies, "dry_run": a.dry_run, "changed": changed, "notes": notes}
    if not a.dry_run:
        Path(a.bodies).write_text(json.dumps(bodies, indent=1) + "\n")
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
