"""Source of bridge.json: the three hand-written variants, one annotated sentence at a time. Edit here, then run
    .venv/bin/python kokopelli/wm/controls/prompts/bridge_source.py
Each sentence is S(text, VIBE.md qualities, kept image ids, which part of the sim frame it matches)."""
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "kokopelli" / "wm" / "controls" / "prompts"))
import build  # noqa: E402

EV = build.vibe_evidence()


def S(text, vibe=(), images=(), geo=""):
    return {"text": text, "vibe": list(vibe), "images": list(images), "geometry": geo}


def join(parts):
    return " ".join(p["text"] for p in parts)


EMPTY_PERSON = {"clothing": "", "expression": "", "gender": "", "age": "", "skin_tone_and_texture": "",
                "facial_features": "", "number_of_subjects": 1, "number_of_arms": 0, "number_of_legs": 0}

# ---------------------------------------------------------------- (a) faithful photoreal
A = {
    "subjects": [
        {"description": [S("A four-metre-wide timber footbridge high above a town street, its weathered larch deck running straight ahead to a timber stair tower.", [5], ["12c4a4ec735c", "e929f29cc9ee"], "deck + rails fill the lower half in every frame; vanishing point near centre (frames 0000-0100)")],
         "appearance_details": [
             S("Boards silver-grey at the ends and honey-brown where feet wear them, with dark screw heads, hairline splits and grit in the gaps.", [5], ["de1e4899d847", "3d76a0d47a89", "e929f29cc9ee"], "transverse boards, as in the sim deck"),
             S("Chest-high oiled oak handrails, darkened by hands, on square posts with close-set vertical cedar balusters.", [5], ["12c4a4ec735c", "daade5134c59"], "the sim's baluster rails on both sides; the right rail crosses the lower frame diagonally while looking right (0149-0250)"),
             S("Low timber planter boxes with stone caps flank the near end, creeping thyme spilling over.", [3, 5], ["daade5134c59", "a404a3a3cc94"], "boxes in the bottom corners of frame 0000")],
         "location": "Lower half of the frame, receding to a vanishing point at the centre",
         "relative_size": "Large within frame", "orientation": "Running straight away from the camera"},
        {"description": [S("Partway along, a garden arch of two bent chestnut poles spans the deck, carrying magenta bougainvillea in full flower and rounded, tightly clipped clumps of small-leaved evergreen.", [3, 5], ["11bb4c0ad5e2", "28072b34a9d0", "9ede10e3e51a"], "the arbour with cushion crowns and the pink blossom crown (0050-0149)")],
         "appearance_details": [
             S("Bark-on poles lashed at the joints, fallen pink bracts on the boards, clumps lime green in sun and dark beneath, a small cream paper lantern hanging from the top.", [3, 5], ["11bb4c0ad5e2", "90cf64448d13"], "the sim's hanging white tag under the pink crown")],
         "location": "Centre of frame, framing the far end of the bridge, then passing overhead at the left edge",
         "relative_size": "Medium, growing larger", "orientation": "Facing the camera"},
        {"description": [S("At the far end, the stair and lift tower: an open square timber pavilion with a thin overhanging flat roof, grasses and wildflowers growing on top, ivy and star jasmine hanging from the eaves.", [3, 5], ["7158e81aabaa", "129473520e6f", "28072b34a9d0"], "landing_commons_west, centre of 0000-0100 and filling the frame by 0299")],
         "appearance_details": [S("Silvering timber posts and beams, woven bamboo screens, a dark glass lift shaft reflecting the sky.", [5], ["28072b34a9d0", "e942be46d019", "90cf64448d13"], "dark glazed panel at the tower's centre")],
         "location": "Centre of frame at the end of the deck", "relative_size": "Small at first, filling the upper frame by the end",
         "orientation": "Facing the camera"},
        {"description": [S("Below and to the right, the flat roof of a three-storey library covered in rows of dark blue solar panels, with a copper observatory dome at its near corner.", [5], ["51da750e8159", "aa91bad1aa52"], "the library roof (13.5 m, below the 17.5 m deck) and dome, right side of every frame")],
         "appearance_details": [S("The dome is copper weathered to blue-green verdigris with rain streaks, on a drum of dusty-rose layered rammed earth; the panels are dusty and reflect the clouds.", [5, 2], ["b4970f245701", "8c15170e420e", "85a683f9f9aa"], "world.json commons palette: rose earth, verdigris, warm glass")],
         "location": "Right third of frame, lower than the bridge", "relative_size": "Medium; large when the camera looks right",
         "orientation": "Seen from above at an angle"},
    ],
    "background_setting": [
        S("Down to the right, a garden street runs away between buildings: pale stone paving with moss in the joints and a narrow water channel, lined with deep beds of pink and lavender hydrangeas, orange daylilies, purple salvia and white roses, and a small timber pergola.", [3, 5, 8], ["a404a3a3cc94", "b645a8fdfa9c", "623179efd1ce"], "the flowering lane and pergola seen in 0149-0250; world.json lanes: permeable stone, moss joints, water runnels"),
        S("Beyond it, a long five-storey timber apartment block whose facade is a grid of deep balconies planted with shrubs and small trees, jasmine and Boston ivy hanging between them.", [3, 5], ["9e668dceb256", "a9a4dc0f1f79", "623179efd1ce", "daade5134c59"], "the long gridded green facade across the right half of 0149-0250"),
        S("To the left, beyond the rooftops, open country: hay meadows, a strip of lavender, rows of slender columnar hornbeams and Italian cypresses, low hedges and a long timber-roofed walkway.", [3, 4], ["aa91bad1aa52", "11bb4c0ad5e2", "28072b34a9d0"], "the left glance (0060-0100): fields, columnar tree rows, walkway roof"),
        S("Low wooded hills close the horizon, softened by distance haze.", [1], ["a404a3a3cc94", "7872720915d2"], "the sim's backdrop hills band behind everything"),
        S("A deep clear blue sky full of large white cumulus clouds with soft grey undersides.", [1], ["def46dad836a", "9ede10e3e51a", "7158e81aabaa", "3c7bfe2b7d79"], "upper 40 % of most frames is sky with clouds"),
        S("The bridge is empty; far below, two people walk slowly along the garden street.", [6], ["aa91bad1aa52", "575a4771197a", "28072b34a9d0"], "people only far away, where depth is coarse, so they don't fight the controls"),
    ],
    "lighting": {
        "conditions": [S("Clear, bright early-afternoon sunshine in early summer; crisp, near-white daylight, not golden.", [1, 2], ["f3a3e86b27ca", "12c4a4ec735c", "28072b34a9d0"], "capture.json clock 14:00")],
        "direction": [S("High sun from the right and slightly behind the camera.", [2], [], "baluster shadows in the sim fall forward-left across the deck")],
        "shadows": [S("Short crisp shadows; the balusters stripe the deck with diagonal shadows; cool blue shade under the arch and tower roof.", [2, 4], ["28072b34a9d0", "e942be46d019"], "matches the sim's shadow stripes on the deck")],
        "illumination_effect": [S("Saturated, true colour with neutral highlights and no orange cast.", [2, 3], ["b645a8fdfa9c", "f3a3e86b27ca"])],
    },
    "aesthetics": {
        "composition": [S("First-person view down the bridge, railings converging on the tower; when the head turns, a railing crosses the lower frame with the town below.", [], [], "head.jsonl yaw: 0, -38, 0, +42..58, +13")],
        "color_scheme": [S("Honey and silver-grey timber, emerald and lime green, magenta and lavender flowers, verdigris copper, dusty rose earth, deep blue sky.", [2, 3, 5], ["41ce7cceb2f2", "85a683f9f9aa", "b645a8fdfa9c"])],
        "mood_atmosphere": [S("Calm, quiet, unhurried and fresh, with a gentle breeze moving the leaves.", [6], ["46a20df40629", "90cf64448d13"])],
        "patterns": [S("Repeating balusters and their shadow stripes, rows of solar panels, the grid of planted balconies.", [], [], "strong repeated edges in the controls")],
    },
    "cinematography": {
        "camera_motion": [S("Handheld first-person walk with a slight bob; the view turns left, then right and down over the railing, then back to the tower.", [], [], "head.py springs and figure-8 bob")],
        "framing": [S("Wide shot")],
        "camera_angle": [S("Eye level, 1.7 m above the deck, looking slightly down when turning to the railing.", [], [], "head pitch -5 to -14 degrees in the glances")],
        "depth_of_field": [S("Deep; everything sharp from the near boards to the hills")],
        "focus": [S("The bridge deck and whatever the walker looks at")],
        "lens_focal_length": [S("Wide-angle, about 18 mm full-frame equivalent", [], [], "90 degree horizontal FOV, 16:9")],
    },
    "style_medium": [S("Live-action video")],
    "artistic_style": [S("Photographic realism with natural, ungraded colour, as recorded by a real camera")],
    "context": [S("Walking across a planted timber footbridge between two rooftops in a small, green, low-rise town on a summer afternoon.", [3, 6], ["12c4a4ec735c", "aa91bad1aa52"])],
    "actions": [
        ("0:00-0:02", S("The walker moves forward looking straight down the bridge, the garden arch and the stair tower ahead in the centre.", [], [], "frames 0-60")),
        ("0:02-0:03", S("The head turns left; the view swings over the left railing to the meadows, rows of columnar trees and the hills.", [], [], "frames 60-100, yaw -38")),
        ("0:03-0:04", S("The head turns back to the front as the arch comes close.", [], [], "frames 100-120")),
        ("0:04-0:08", S("The head turns right and tilts down over the railing: the solar roof and copper dome of the library, the flowering garden street below, and the long planted apartment block beyond.", [], [], "frames 120-255, yaw +42 then +58")),
        ("0:08-0:10", S("The head swings back toward the stair tower, now close, its overhanging planted roof and hanging vines across the top of the frame.", [], [], "frames 255-299")),
    ],
}

# ---------------------------------------------------------------- (b) lighter
B = {
    "subjects": [
        {"description": [S("A weathered timber footbridge high above a town, oak handrails on close-set balusters, leading to an open timber stair tower with a planted roof and hanging vines.", [3, 5], ["12c4a4ec735c", "e929f29cc9ee", "7158e81aabaa"], "deck, rails, tower: the shapes the depth control is sure about")],
         "appearance_details": [S("A pole arch carries magenta bougainvillea.", [3], ["11bb4c0ad5e2", "9ede10e3e51a"], "the arbour")],
         "location": "Lower half and centre of frame", "relative_size": "Large within frame", "orientation": "Running straight away from the camera"},
    ],
    "background_setting": [
        S("Below right: a solar-panel roof with a verdigris copper dome, a street lined with pink and lavender flowering shrubs, a timber apartment block with planted balconies.", [3, 5], ["623179efd1ce", "9e668dceb256", "51da750e8159"], "right-side view 0149-0250"),
        S("Left: meadows, columnar trees, wooded hills.", [3, 4], ["aa91bad1aa52"], "left glance and backdrop"),
        S("Deep blue sky, big white cumulus.", [1], ["def46dad836a", "9ede10e3e51a"]),
    ],
    "lighting": {
        "conditions": [S("Clear summer afternoon sun, near-white, not golden.", [1, 2], ["f3a3e86b27ca", "28072b34a9d0"])],
        "direction": [S("High sun from the right.")],
        "shadows": [S("Crisp baluster shadows on the deck.", [2], [])],
        "illumination_effect": [S("True, saturated colour.", [2], ["b645a8fdfa9c"])],
    },
    "aesthetics": {
        "composition": [S("First-person view down the bridge.")],
        "color_scheme": [S("Honey timber, green, magenta, blue sky.", [2, 3], [])],
        "mood_atmosphere": [S("Calm, quiet, unhurried.", [6], [])],
        "patterns": [S("Balusters")],
    },
    "cinematography": {
        "camera_motion": [S("Handheld walk, looking left and right.")],
        "framing": [S("Wide shot")],
        "camera_angle": [S("Eye level")],
        "depth_of_field": [S("Deep")],
        "focus": [S("The bridge")],
        "lens_focal_length": [S("18 mm wide")],
    },
    "style_medium": [S("Live-action video")],
    "artistic_style": [S("Photographic realism, natural colour")],
    "context": [S("A rooftop footbridge in a small green town.", [3], [])],
    "actions": [],
}

# ---------------------------------------------------------------- (c) documentary phone video
C = json.loads(json.dumps(A))  # deep copy, then make it read like an ordinary phone clip
C["subjects"][0]["appearance_details"] = [
    S("The boards are silver-grey at their ends and honey-brown where feet wear them, with dark screw heads, hairline splits and grit in the gaps.", [5], ["de1e4899d847", "e929f29cc9ee"]),
    S("Chest-high oiled oak handrails on square posts, with close-set vertical cedar balusters between them; low timber planter boxes with stone caps at the near end.", [5], ["12c4a4ec735c", "daade5134c59"], "rails + planter boxes")]
C["subjects"][1]["appearance_details"] = [S("Bark-on poles lashed at the joints, fallen pink bracts on the boards, a small cream paper lantern hanging from the top.", [5], ["90cf64448d13"])]
C["background_setting"] = [
    S("Down to the right: a garden street of pale stone paving and a narrow water channel, with beds of pink and lavender hydrangeas and orange daylilies, and a long timber apartment block with balconies full of shrubs and hanging ivy.", [3, 5, 8], ["623179efd1ce", "9e668dceb256", "a404a3a3cc94"], "right-side view"),
    S("To the left: meadows, a strip of lavender, rows of columnar trees, and wooded hills on the horizon.", [3, 4], ["aa91bad1aa52"], "left glance"),
    S("Deep blue sky with big white cumulus clouds, the brightest parts slightly blown out.", [1], ["def46dad836a", "7158e81aabaa"], "phone auto-exposure clips bright clouds"),
    S("The bridge is empty; two small figures walk along the street far below.", [6], ["575a4771197a", "aa91bad1aa52"]),
]
C["aesthetics"]["composition"] = [S("Casual, unframed point-of-view: the phone points down the bridge, swings left, then right and down over the railing, then back.", [], [], "same yaw sequence")]
C["aesthetics"]["mood_atmosphere"] = [S("Ordinary, calm, a quiet weekday; wind gently moving the leaves.", [6], ["46a20df40629"])]
C["cinematography"] = {
    "camera_motion": [S("Handheld phone held at eye level while walking: small bobs with each step, slight tilts, quick pans left and right.", [], [], "head.py bob 1.8 cm, roll 0.6 deg")],
    "framing": [S("Wide shot")],
    "camera_angle": [S("Eye level, 1.7 m above the deck, tilting down toward the railing when panning right.")],
    "depth_of_field": [S("Deep, as with any phone")],
    "focus": [S("Everything in focus")],
    "lens_focal_length": [S("Phone main camera at its wide setting, about 18 mm equivalent")],
}
C["style_medium"] = [S("Live-action video, handheld smartphone footage")]
C["artistic_style"] = [S("Unedited documentary phone video: automatic exposure and white balance, slightly clipped bright clouds, mild sharpening and compression, natural colour")]
C["context"] = [S("Someone films their walk across a planted footbridge between two rooftops in a small green town, to show a friend the view.", [6], ["575a4771197a"])]


KEEP_ACTIONS = False  # NVIDIA's transfer example strips actions and times: the controls carry the motion


def to_caption(v, size=(832, 480), duration="10s", fps=30):
    """Turn the annotated variant into NVIDIA's caption shape; return (caption, carries)."""
    carries = []

    def take(field, parts):
        for p in parts:
            if p["vibe"] or p["images"] or p["geometry"]:
                carries.append({"field": field, "text": p["text"],
                                "vibe": [f"{n}. {EV[n]['title']}" for n in p["vibe"]],
                                "images": p["images"], "geometry": p["geometry"]})
        return join(parts)

    cap: dict[str, Any] = {"subjects": []}
    for i, s in enumerate(v["subjects"]):
        cap["subjects"].append({"description": take(f"subjects[{i}].description", s["description"]),
                                "appearance_details": take(f"subjects[{i}].appearance_details", s["appearance_details"]),
                                "location": s["location"], "relative_size": s["relative_size"],
                                "orientation": s["orientation"], **EMPTY_PERSON})
    cap["background_setting"] = take("background_setting", v["background_setting"])
    for group in ("lighting", "aesthetics", "cinematography"):
        cap[group] = {k: take(f"{group}.{k}", parts) for k, parts in v[group].items()}
    for k in ("style_medium", "artistic_style", "context"):
        cap[k] = take(k, v[k])
    if v["actions"] and KEEP_ACTIONS:
        cap["actions"] = [{"time": t, "description": take(f"actions {t}", [p])} for t, p in v["actions"]]
        cap["temporal_caption"] = " ".join(f"From {t.split('-')[0]}, {p['text'][0].lower()}{p['text'][1:]}" for t, p in v["actions"])
    cap["text_and_signage_elements"] = []
    cap.update({"resolution": {"H": size[1], "W": size[0]}, "aspect_ratio": "16,9", "duration": duration, "fps": fps})
    return cap, carries


VARIANTS = [
    ("a_faithful_photoreal", A,
     "Maximal realism. Every visible shape the controls impose (deck, rails, planter boxes, arch, tower, library roof and dome, garden street, planted block, fields, hills, sky) is named, in the same screen place, so the text and the controls agree. The vision is carried only by physical description: real species (bougainvillea, star jasmine, hydrangea, hornbeam, cypress), real materials and how they age (larch silvering, oak worn by hands, verdigris with rain streaks, rammed earth layers), and a time of day. No style or genre words. Field structure and length match NVIDIA's upsampled captions (theirs are 980 and 1,266 tokens; this is about 1,400), which is what the model was trained on. Like NVIDIA's transfer example, it has no time-coded actions: the controls already carry the motion, and the camera turns are named once in camera_motion. The per-second beats are kept in `beats` below for reference."),
    ("b_light", B,
     "Same scene, same order, about a third the words. Use it if (a) fights the controls: long, specific text can make the model paint things the depth map has no room for (a bench where the depth says empty paving), or invent detail that flickers between chunks. Kept: the big shapes, the light, the sky, and the colours that carry the vision. Dropped: most wear details and species, the planter boxes, people. About 470 tokens, so it also fits if the distilled checkpoint really caps text at 512 tokens (config.json text_cache_max_len)."),
    ("c_documentary_phone", C,
     "Same scene described as an ordinary person's phone clip. Phone footage is the most common 'real video' in web-scale training data, so asking for it pulls hardest away from a game look: auto exposure, slightly blown clouds, mild compression, small step bobs. It also explains away the head-bob and quick pans in the controls instead of letting the model read them as glitches. Costs: less colour richness and a flatter, plainer look than (a); it may under-saturate the flowers the board wants."),
]


def main():
    out = {
        "shot": "bridge",
        "clip": "out/filter_test/test_clip/ (300 frames, 30 fps = 10 s, 1280x720, 90 deg FOV, 14:00, walk x 356->372 m, y 115 m, 17.5 m up, facing east)",
        "how_to_use": "Send `prompt` (a JSON string, as in NVIDIA's example1_upsampled_prompt.json) as the text prompt. `caption` is the same thing as an object for reading. Change `resolution`/`duration`/`fps` inside it to match the run (world_filter.py default is 448x256, 24 fps chunks; Sim-Transfer is 480p). `carries` lists, for each sentence, the VIBE.md qualities and kept moodboard images it carries and the part of the sim frame it matches.",
        "negative_prompt_support": {
            "Cosmos3-Nano-Sim-Transfer": "Not used. It is a DMD-distilled 4-step model (model_index.json fixed_step_sampler_config) with guidance baked in; the README says the request sets neither steps nor guidance, and with no classifier-free guidance there is no negative branch to steer away from.",
            "Cosmos3-Nano base via world_filter.py": "Used. world_filter.py runs guidance 3.0 and builds its negative branch from pipeline._negative_prompt_text, which cosmos3_mlx loads from models/Cosmos3-Nano/assets/negative_prompt.json. world_filter.py has no flag to pass another one yet; `negative_prompt` below is ready for when it does (a --negative option there, owned by the world-filter session).",
        },
        "negative_prompt": build.negative("Looks like a video game, an architectural visualisation or a painting rather than a photograph."),
        "beats": [{"time": t, "what": p["text"], "frames": p["geometry"]} for t, p in A["actions"]],
        "variants": [],
    }
    for vid, v, why in VARIANTS:
        cap, carries = to_caption(v)
        prompt = json.dumps(cap, ensure_ascii=False)
        bad = build.check(prompt)
        assert not bad, (vid, bad)
        out["variants"].append({"id": vid, "reasoning": why, "tokens": build.count_tokens(prompt),
                                "prompt": prompt, "caption": cap, "carries": carries})
    out["negative_prompt_tokens"] = build.count_tokens(json.dumps(out["negative_prompt"]))
    dest = ROOT / "kokopelli" / "wm" / "controls" / "prompts" / "bridge.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for v in out["variants"]:
        print(v["id"], v["tokens"], "tokens,", len(v["carries"]), "annotated sentences")


main()
