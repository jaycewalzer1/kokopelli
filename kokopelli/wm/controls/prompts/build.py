"""Assemble a Cosmos world-model text prompt for one shot, so later shots don't need hand-writing.

    python3 kokopelli/wm/controls/prompts/build.py SHOT.json [--mode full|light|phone] [--out FILE]
    python3 kokopelli/wm/controls/prompts/build.py --check kokopelli/wm/controls/prompts/bridge.json   # banned words + token counts

SHOT.json is a short description of what the sim camera sees (see README.md for the fields). This file adds the
parts that are the same for every shot in the city: the light and sky from VIBE.md, physical words for the
world.json materials and palettes of the places you name, the camera wording for each mode, and a check that no
style or genre word ("solarpunk", "futuristic", "balloons"...) slipped in. The output has the same shape as
NVIDIA's upsampled captions (models/Cosmos3-Nano-Sim-Transfer/assets/sample_data/*), and `prompt` is that caption
as one JSON string, which is what the model was trained on.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
WORLD = ROOT / "data" / "city" / "world.json"
VIBE = ROOT / "tools" / "moodboard" / "VIBE.md"
TOKENIZER = ROOT / "models" / "Cosmos3-Nano-Sim-Transfer" / "tokenizer.json"
STOCK_NEGATIVE = ROOT / "models" / "Cosmos3-Nano" / "assets" / "negative_prompt.json"

# Words that pulled earlier renders toward illustration, or name a genre instead of a thing a camera can see.
BANNED = ["solarpunk", "cyberpunk", "utopia", "utopian", "futuristic", "future", "sci-fi", "fantasy", "magical",
          "whimsical", "dreamy", "anime", "ghibli", "illustration", "painting", "painterly", "render", "3d",
          "cgi", "unreal", "stylized", "stylised", "festoon", "balloon", "balloons", "fairy lights", "isono",
          "vibrant", "lush", "eco", "sustainable", "visionary", "hyperrealistic", "8k", "masterpiece"]

# world.json palette and material words -> what they physically are.
PHYSICAL = {
    "sage": "sage-green painted timber", "cream": "cream lime render", "brass": "brass fittings dulled by weather",
    "deep green": "deep green stained timber", "terracotta": "terracotta tile", "linen": "off-white lime render",
    "white oak": "pale white-oak boards", "pale gold": "pale straw-coloured render", "sky blue": "sky-blue painted shutters",
    "indigo": "indigo-dyed canvas awnings", "copper": "copper trim gone brown and green", "sand": "sand-coloured render",
    "rust": "rust-red painted steel", "steel": "galvanised steel", "clover green": "clover-green window frames",
    "tomato red": "tomato-red painted doors", "ochre": "ochre rammed earth", "olive": "olive-green shutters",
    "slate": "slate roof tiles", "coral": "coral-pink lime render", "white": "white lime render",
    "rose earth": "dusty-rose rammed earth in visible layers", "verdigris": "copper weathered to blue-green verdigris",
    "warm glass": "glass reflecting the sky", "natural timber": "untreated timber going silver",
    "CLT timber": "cross-laminated timber", "bamboo louvers": "woven bamboo louvres", "solar glass": "dark blue solar glass",
    "green roof": "a roof of grasses and wildflowers", "canopy walk": "a planted rooftop walkway",
    "woven bamboo screen": "woven bamboo screens", "timber vaulted hall": "a hall with an exposed timber vault",
}

# The light, sky, planting and wear the board asks for (VIBE.md qualities), in camera words. Each line names the
# VIBE.md quality numbers it carries; the image ids are read from VIBE.md itself.
VIBE_LINES = {
    "sky": ("A deep, clear blue sky with large white cumulus clouds; haze only at the far horizon.", [1]),
    "light": ("Crisp, near-white sunlight, not golden; short crisp shadows, cool blue shade, saturated true colours.", [2]),
    "planting": ("Plants spill over every edge: climbing jasmine and ivy, hanging vines, flowering shrubs in pink, "
                 "lavender, red, orange and white among dense green.", [3]),
    "trees": ("Large mature trees with dappled light under their crowns.", [4]),
    "wear": ("Every surface shows its age: weathered silvering timber, moss in joints and at the base of walls, "
             "rain streaks, scuffs and dust.", [5]),
    "people": ("Only a few people, far apart, doing ordinary things at an unhurried pace.", [6]),
    "water": ("Still water reflects the blue sky.", [8]),
}

MODES = {
    "full": {"style_medium": "Live-action video",
             "artistic_style": "Photographic realism with natural, ungraded colour, as recorded by a real camera"},
    "light": {"style_medium": "Live-action video", "artistic_style": "Photographic realism, natural colour"},
    "phone": {"style_medium": "Live-action video, handheld smartphone footage",
              "artistic_style": "Unedited documentary phone video: automatic exposure, slightly clipped bright clouds, "
                                "mild sharpening and compression, natural colour"},
}


def vibe_evidence(path=VIBE):
    """{quality number: {"title", "images"}} from the '### N. title' sections of VIBE.md (kept ids only, before 'Not this')."""
    out, number = {}, None
    for line in path.read_text().splitlines():
        head = re.match(r"### (\d+)\. (.+)", line)
        if head:
            number = int(head.group(1))
            out[number] = {"title": head.group(2).strip(), "images": []}
        elif line.startswith("## "):
            number = None
        elif number and "Not this" not in line:
            for found in re.findall(r"`([0-9a-f]{12})`", line):
                if found not in out[number]["images"]:
                    out[number]["images"].append(found)
    return out


def find(world, pid):
    """A place id from any list in world.json: buildings, places, cells, landscape, sky bridges, lanes."""
    pools = [world["buildings"], world["places"], world["cells"], world["landscape"],
             world["sky_bridges"]["segments"], world["lanes"]["segments"]]
    for pool in pools:
        for entry in pool:
            if entry.get("id") == pid:
                return entry
    raise KeyError(f"{pid} is not in world.json")


def physical(text):
    for word, phrase in sorted(PHYSICAL.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"\b{re.escape(word)}\b", phrase, text)
    return text


def describe_place(world, pid, seen=None):
    """One plain sentence about a world.json entry, in material words. A palette already in `seen` isn't repeated."""
    e = find(world, pid)
    seen = set() if seen is None else seen
    name = e.get("description") or e.get("type", "").replace("_", " ") or pid.replace("_", " ")
    bits = []
    if e.get("floors"):
        bits.append(f"{e['floors']} storeys tall" if isinstance(e["floors"], int) else "")
    if e.get("materials"):
        bits.append("built of " + physical(e["materials"]).replace(" + ", " and ").replace(", ", " and "))
    if e.get("palette") and tuple(e["palette"]) not in seen:
        seen.add(tuple(e["palette"]))
        bits.append("finished in " + ", ".join(PHYSICAL.get(p, p) for p in e["palette"]))
    if e.get("roof"):
        bits.append("with " + physical(e["roof"]).replace(", ", ", "))
    if e.get("features"):
        bits.append("with " + ", ".join(e["features"]).replace("_", " "))
    sentence = physical(name) + (", " + "; ".join(b for b in bits if b) if any(bits) else "")
    return sentence[0].upper() + sentence[1:] + "."


def check(text):
    """Banned words in text (whole words, case-insensitive)."""
    return [w for w in BANNED if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", text, re.I)]


def count_tokens(text):
    try:
        from tokenizers import Tokenizer
        return len(Tokenizer.from_file(str(TOKENIZER)).encode(text).ids)
    except Exception:  # no tokenizers package: about 4 characters a token for this kind of English
        return round(len(text) / 4)


def negative(extra=None):
    """The base model's stock negative caption with our own failure modes added. Only used where the sampler runs
    classifier-free guidance (base Cosmos3-Nano via world_filter.py); the distilled Sim-Transfer checkpoint has no
    guidance, so a negative prompt does nothing there."""
    neg = json.loads(STOCK_NEGATIVE.read_text()) if STOCK_NEGATIVE.exists() else {}
    neg["style_medium"] = "3D video-game render, cartoon, illustration, anime background painting, digital concept art"
    neg["artistic_style"] = ("Computer graphics look: smooth untextured plastic surfaces, uniform repeating tiles, "
                             "rounded blob-shaped foliage, toy-like proportions, flat colour fills, outlines")
    neg.setdefault("lighting", {})["conditions"] = ("Golden-hour sepia haze, sun burning through smog, flat white "
                                                    "overcast, grey dull sky, orange colour cast")
    neg.setdefault("aesthetics", {})["color_scheme"] = ("Brownish, desaturated, sepia or golden grade; neon; "
                                                        "garish oversaturated candy colours")
    if extra:
        neg["context"] = neg.get("context", "") + " " + extra
    return neg


def build(shot, mode="full", world=None):
    world = world or json.loads(WORLD.read_text())
    evidence = vibe_evidence()
    carries = []

    def note(field, text, vibe=(), source=()):
        imgs = [i for n in vibe for i in evidence.get(n, {}).get("images", [])[:4]]
        carries.append({"field": field, "text": text, "vibe": [f"{n}. {evidence[n]['title']}" for n in vibe if n in evidence],
                        "images": imgs, "source": list(source)})
        return text

    subjects, seen = [], set()
    items = shot.get("in_frame", [])[: (2 if mode == "light" else len(shot.get("in_frame", [])))]
    for item in items:
        detail = " ".join(describe_place(world, p, seen) for p in item.get("places", []))
        desc = note("subjects", item["what"], item.get("vibe", []), [f"world.json:{p}" for p in item.get("places", [])])
        subjects.append({"description": desc, "appearance_details": "" if mode == "light" else note(
            "subjects", (item.get("details", "") + " " + detail).strip(), item.get("vibe", [5])),
            "location": item.get("where", ""), "relative_size": item.get("size", ""), "orientation": "",
            "clothing": "", "expression": "", "gender": "", "age": "", "skin_tone_and_texture": "",
            "facial_features": "", "number_of_subjects": 1, "number_of_arms": 0, "number_of_legs": 0})

    keys = ["sky", "planting"] if mode == "light" else ["sky", "planting", "wear"] + shot.get("vibe_extra", [])
    background = [note("background_setting", shot["setting"], [], ["shot"])]
    named = {p for item in items for p in item.get("places", [])}  # already described as subjects
    background += [note("background_setting", describe_place(world, p, seen), [5], [f"world.json:{p}"])
                   for p in ([] if mode == "light" else shot.get("places", [])) if p not in named]
    background += [note("background_setting", VIBE_LINES[k][0], VIBE_LINES[k][1]) for k in keys]
    if shot.get("people"):
        background.append(note("background_setting", shot["people"], [6]))

    cam = shot.get("camera", {})
    lens = cam.get("lens", f"Wide-angle, about {cam.get('mm', 18)} mm full-frame equivalent")
    if mode == "phone":
        lens = "Phone camera, wide lens"
    caption = {
        "subjects": subjects,
        "background_setting": " ".join(background),
        "lighting": {
            "conditions": note("lighting", f"Clear, bright {shot.get('time', 'late morning')} sunshine in early summer; "
                                            "crisp near-white daylight, not golden", [1, 2]),
            "direction": note("lighting", shot.get("sun", "High sun from the side"), [2]),
            "shadows": note("lighting", shot.get("shadows", "Short, crisp-edged shadows with cool blue shade"), [2, 4]),
            "illumination_effect": note("lighting", VIBE_LINES["light"][0], [2]),
        },
        "aesthetics": {
            "composition": cam.get("composition", ""),
            "color_scheme": note("aesthetics", shot.get("colors", "Natural greens, timber browns, flowers, blue sky"), [2, 3]),
            "mood_atmosphere": note("aesthetics", "Calm, quiet, unhurried, fresh", [6]),
            "patterns": shot.get("patterns", ""),
        },
        "cinematography": {
            "camera_motion": cam.get("motion_phone" if mode == "phone" else "motion", "Steady walk forward"),
            "framing": "Wide shot",
            "camera_angle": cam.get("angle", "Eye level, about 1.7 m above the ground"),
            "depth_of_field": "Deep, everything in focus from near to far",
            "focus": cam.get("focus", ""),
            "lens_focal_length": lens,
        },
        **MODES[mode],
        "context": shot.get("context", ""),
    }
    if mode != "light" and shot.get("beats"):
        caption["actions"] = [{"time": t, "description": d} for t, d in shot["beats"]]
        caption["temporal_caption"] = " ".join(f"{t.split('-')[0]}: {d}" for t, d in shot["beats"])
    caption["text_and_signage_elements"] = []
    w, h = shot.get("size", [832, 480])
    caption.update({"resolution": {"H": h, "W": w}, "aspect_ratio": shot.get("aspect_ratio", "16,9"),
                    "duration": f"{shot.get('duration_s', 10)}s", "fps": shot.get("fps", 30)})
    prompt = json.dumps(caption, ensure_ascii=False)
    return {"mode": mode, "caption": caption, "prompt": prompt, "tokens": count_tokens(prompt),
            "banned_words_found": check(prompt), "carries": carries}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shot", nargs="?")
    ap.add_argument("--mode", choices=list(MODES), default="full")
    ap.add_argument("--out")
    ap.add_argument("--check", help="a prompts file like bridge.json: report banned words and token counts")
    args = ap.parse_args()
    if args.check:
        data = json.loads(Path(args.check).read_text())
        bad = False
        for v in data["variants"]:
            words = check(v["prompt"])
            bad |= bool(words)
            print(f"{v['id']}: {count_tokens(v['prompt'])} tokens, banned: {words or 'none'}")
        sys.exit(1 if bad else 0)
    if not args.shot:
        ap.error("give a SHOT.json or --check FILE")
    result = build(json.loads(Path(args.shot).read_text()), args.mode)
    text = json.dumps(result, indent=1, ensure_ascii=False)
    Path(args.out).write_text(text + "\n") if args.out else print(text)
    if result["banned_words_found"]:
        print(f"warning: banned words in prompt: {result['banned_words_found']}", file=sys.stderr)


if __name__ == "__main__":
    main()
