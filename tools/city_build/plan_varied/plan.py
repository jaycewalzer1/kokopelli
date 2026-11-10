#!/usr/bin/env python
"""Write data/city/world.json: world.json with the seven residential cells re-planned as a varied village.

    ~/Desktop/kokopelli/simworld/.venv/bin/python tools/city_build/plan_varied/plan.py [--png out/city_kinds/planner/plan.png]

Everything outside the seven cells (commons, green, farms, lanes, water, landscape, moss_east, the Moss-Commons
bridge) is copied unchanged. The layout lives in LAYOUT below: one list per cell of buildings (kinds from
tools/city_build/kinds/CATALOG.md), open spaces (lawns/squares with props, courtyard gardens) and mews paths, plus the
canopy-walk spans (sky_bridges) and landing towers. check.py (same folder) validates the result.
"""
import argparse
import copy
import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "data" / "city" / "world.json"
DST = ROOT / "data" / "city" / "world_varied.json"   # a fresh plan is written beside the kept city, never over it
RES = ("fern", "moss", "birch", "reed", "clover", "sorrel", "heron")
KEEP_IDS = {"moss_east"}
WALK = 17.5

# kind -> (default use, entrance type)
USE = {
    "coconut_shophouse": ("shops + homes", "shopfront"), "bamboo_hall": ("common house", "main entrance"),
    "kampung_terraces": ("common house + homes + clinic garden", "main entrance"), "lever_slab": ("workshops + homes", "main entrance"),
    "unite_habitation": ("shops + homes", "main entrance"), "oasia_tower": ("gym + homes", "main entrance"),
}

# Palette variations: each building takes its cell palette with one colour swapped, so neighbours differ.
ALT = {
    "fern": ["sage", "cream", "brass", "white oak", "clover green", "coral"],
    "moss": ["deep green", "terracotta", "linen", "ochre", "rose earth", "sage"],
    "birch": ["white oak", "pale gold", "sky blue", "coral", "cream", "tomato red"],
    "reed": ["indigo", "copper", "sand", "verdigris", "deep green", "ochre"],
    "clover": ["rust", "steel", "clover green", "pale gold", "sky blue", "cream"],
    "sorrel": ["tomato red", "ochre", "olive", "cream", "sky blue", "terracotta"],
    "heron": ["slate", "coral", "white", "sky blue", "pale gold", "verdigris"],
}


def B(i, kind, r, front, h, use=None, pal=None, ent=None, note=None):
    return {"t": "b", "id": i, "arch": kind, "r": r, "front": front, "h": h, "use": use, "pal": pal, "ent": ent, "note": note}


def G(i, r, gate_x=None, features=None):
    """courtyard garden (SWCityOpenSpace 'courtyard': beds, long table, play corner, runnel; fruit trees round it)"""
    return {"t": "court", "id": i, "r": r, "gate_x": gate_x, "features": features}


def S(i, r, props=(), desc="small square"):
    """lawn / small square with props (planter-bench trees, cafe tables, shade sails, pools, bikes, string lights)"""
    return {"t": "lawn", "id": i, "r": r, "props": list(props), "desc": desc}


def P(i, line):
    return {"t": "path", "id": i, "line": line}


def T(i, r, on=None):
    """canopy landing tower (stair + lift), free-standing unless on= a host"""
    return {"t": "tower", "id": i, "r": r, "on": on}


# ---- the plan -----------------------------------------------------------------------------------------------------
# rects are [x0, y0, x1, y1] world metres (x east, y south); front = the street side (N/S/E/W).
LAYOUT = {
    # FERN: "glass houses in the orchard". A shophouse street on the parkway lane (The Kettle, Rise Bakery), Mies and
    # Johnson glass pavilions in the meadow facing the food forest, the bamboo common hall over a big orchard, and
    # a Habitat-67 hill of stacked boxes on the east lane; the canopy walk turns on the SE corner tower.
    "fern": [
        B("fern_ando", "ando_courtyard", [50, 40, 68, 58], "N", 8, "home"),
        B("fern_kettle", "coconut_shophouse", [72, 40, 104, 58], "N", 10, "cafe + homes"),
        S("fern_kettle_square", [107, 40, 133, 62], [("tables", 112, 47), ("sail", 126, 52), ("planter", 112, 57, "flowering cherry"), ("planter", 129, 44, "maple")], "Kettle Square: cafe tables under a sail"),
        B("fern_rise", "coconut_shophouse", [136, 40, 164, 58], "N", 11, "bakery + homes"),
        B("fern_corner", "coconut_shophouse", [167, 40, 190, 60], "N", 9),
        B("fern_farnsworth", "farnsworth", [50, 68, 68, 98], "W", 6, "home"),
        B("fern_glass", "glass_house", [50, 108, 66, 128], "W", 5, "home"),
        B("fern_eichler", "eichler_court", [50, 142, 78, 190], "W", 5, "homes"),
        B("fern_hall", "bamboo_hall", [96, 92, 142, 120], "N", 11, "common house"),
        B("fern_hanna", "hanna_honeycomb", [84, 128, 118, 160], "W", 6, "home"),
        G("fern_orchard", [121, 124, 142, 169], gate_x=131, features=["orchard rows", "long dining table", "play corner", "water runnel"]),
        S("fern_meadow", [73, 64, 92, 122], [("planter", 82, 74, "birch"), ("planter", 84, 112, "jacaranda")], "a wildflower meadow round the glass houses"),
        B("fern_flats", "breeze_block_flats", [172, 66, 190, 112], "E", 18),
        B("fern_sukiya", "sukiya_villa", [148, 70, 169, 95], "W", 6, "home + tea room"),
        S("fern_pocket", [148, 98, 169, 116], [("tables", 158, 106)], "pocket garden by the flats"),
        B("fern_habitat", "habitat67", [150, 120, 190, 172], "E", 24, "homes with roof gardens"),
        B("fern_flats_s", "breeze_block_flats", [92, 172, 142, 190], "S", 16),
        B("fern_butterfly", "butterfly_row", [148, 175, 178, 190], "S", 6, "homes"),
        T("landing_fern_south", [182, 182, 190, 190]),
        P("fern_mews", [[121, 62], [121, 88], [145, 88], [145, 117], [145, 190]]),
        P("fern_meadow_walk", [[70, 40], [70, 62], [94, 62], [94, 88], [81, 96], [81, 190]]),
    ],
    # MOSS: "the green hill". A Kampung-Admiralty stack of planted terraces fills the middle (the common house and
    # roof dye garden), ringed by tiled courtyard houses (Bawa), a stacked-stone clinic (Corbero) and a shophouse row
    # on the south lane (Loom & Thread). moss_east stays exactly as it was: the bridge shot looks over its roof.
    "moss": [
        B("moss_clinic", "corbero_house", [222, 40, 258, 66], "N", 9, "clinic"),
        S("moss_dye_square", [262, 40, 302, 70], [("pool", 282, 55, 1100, 300), ("planter", 268, 64, "jacaranda"), ("planter", 296, 64, "flowering cherry"), ("sail", 270, 47)], "a still pool and dye-plant beds"),
        B("moss_daycare", "bawa_courtyard", [306, 40, 341, 68], "N", 7, "daycare"),
        B("moss_kampung", "kampung_terraces", [220, 92, 310, 152], "N", 20, "common house + homes; roof dye garden"),
        G("moss_dye_garden", [314, 92, 340, 152], gate_x=327, features=["dye garden", "long dining table"]),
        T("landing_moss_west", [220, 182, 228, 190]),
        B("moss_bawa_sw", "bawa_courtyard", [232, 162, 264, 190], "S", 8, "homes"),
        B("moss_loom", "coconut_shophouse", [270, 168, 304, 190], "S", 10, "fashion studio + homes"),
        B("moss_x100", "eichler_x100", [311, 168, 341, 190], "S", 5, "home"),
        P("moss_mews_n", [[220, 86], [341, 86]]),
        P("moss_mews_s", [[220, 158], [268, 158], [268, 190]]),
    ],
    # BIRCH: "the garden suburb" (elders + young families). Eichler courts, a Palm Springs butterfly row, Koenig's
    # Stahl house and Neutra's Kaufmann house in big gardens; breeze-block flats and a Barbican terrace face the
    # Village Green. The canopy walk comes down at the two lane-side towers and runs along the Green.
    "birch": [
        B("birch_butterfly", "butterfly_row", [54, 220, 136, 240], "N", 6, "homes"),
        B("birch_glass", "glass_house", [144, 220, 166, 236], "N", 5, "home"),
        T("landing_birch_north", [182, 220, 190, 228]),
        B("birch_flats", "breeze_block_flats", [172, 231, 190, 277], "E", 18),
        B("birch_corner_shop", "coconut_shophouse", [168, 280, 190, 297], "E", 11, "shops + homes"),
        B("birch_stahl", "stahl_house", [50, 252, 78, 284], "W", 5, "home"),
        B("birch_kaufmann", "kaufmann_desert", [50, 294, 82, 330], "W", 6, "home"),
        B("birch_eichler_1", "eichler_atrium", [92, 252, 112, 278], "S", 5, "home"),
        B("birch_eichler_2", "eichler_atrium", [115, 252, 135, 278], "S", 5, "home"),
        B("birch_eichler_3", "eichler_atrium", [138, 252, 160, 278], "S", 5, "home"),
        B("birch_common", "eichler_court", [92, 284, 150, 310], "N", 5, "common house"),
        B("birch_terrace", "barbican_terrace", [168, 300, 190, 359], "E", 21),
        T("landing_birch_south", [182, 362, 190, 370]),
        B("birch_eichler_mid", "eichler_court", [94, 318, 152, 344], "N", 5, "homes"),
        B("birch_eichler_s", "eichler_court", [50, 342, 88, 370], "S", 5, "homes"),
        B("birch_kitchen", "coconut_shophouse", [102, 350, 136, 370], "S", 9, "community kitchen + homes"),
        B("birch_farnsworth", "farnsworth", [140, 350, 164, 370], "S", 6, "home"),
        P("birch_mews", [[50, 247], [87, 247], [87, 336], [92, 346], [98, 370]]),
        P("birch_cross", [[87, 280], [165, 280]]),
        P("birch_mews_s", [[87, 314], [165, 314]]),
    ],
    # REED: "tropical high", between the Green and the creek. A Boeri vertical forest by the creek, breeze-block
    # flats in the middle, a Bawa courtyard common house, shophouses for the tea house and the pub, and a cluster
    # of stilt houses (the music practice pods) down to the creek lane.
    "reed": [
        B("reed_tea", "coconut_shophouse", [385, 220, 417, 240], "N", 9, "tea house + homes"),
        B("reed_shop_n", "coconut_shophouse", [420, 220, 448, 240], "N", 10, "shops + homes"),
        T("landing_reed_north", [451, 220, 459, 228]),
        B("reed_lowtide", "coconut_shophouse", [466, 220, 498, 240], "N", 10, "pub + homes"),
        B("reed_forest", "vertical_forest", [499, 246, 525, 272], "E", 36, "homes"),
        B("reed_common", "bawa_courtyard", [385, 256, 419, 290], "W", 8, "common house"),
        B("reed_flats", "breeze_block_flats", [446, 264, 464, 324], "W", 18),
        B("reed_terrace", "barbican_terrace", [385, 298, 407, 348], "W", 21),
        G("reed_rain_garden", [411, 298, 436, 344], gate_x=424, features=["rain garden", "long dining table", "water runnel"]),
        B("reed_creek_flats", "breeze_block_flats", [507, 288, 525, 346], "E", 16),
        S("reed_creek_lawn", [468, 278, 504, 298], [("planter", 476, 288, "jacaranda"), ("sail", 492, 288)], "a hammock lawn under trees"),
        B("reed_casa", "casa_de_vidro", [472, 300, 496, 324], "N", 9, "home"),
        B("reed_sea_ranch", "sea_ranch", [470, 327, 500, 351], "E", 9, "homes"),
        T("landing_reed_south", [385, 362, 393, 370]),
        B("reed_butterfly", "butterfly_row", [396, 352, 434, 370], "S", 6, "homes"),
        B("reed_pods_a", "stilt_house", [466, 354, 482, 370], "S", 7, "music practice pods"),
        B("reed_pods_b", "stilt_house", [486, 356, 500, 370], "S", 7, "music practice pods"),
        P("reed_mews", [[385, 248], [440, 248], [440, 350], [444, 360], [444, 370]]),
        P("reed_creek_walk", [[494, 242], [494, 276], [503, 282], [503, 370]]),
    ],
    # HERON: "artists by the creek". The Oasia tower (red mesh, creepers) holds the climbing gym, the Eames House
    # the art studios, a Barbican terrace behind the NW walk towers; a bamboo hall common house, Lina Bo Bardi's glass
    # house by the creek, a Stahl house, stilt houses, a Bawa courtyard house and a gallery shophouse facing the farms.
    "heron": [
        T("landing_heron_north", [385, 400, 393, 408]),
        B("heron_studios", "eames_house", [396, 400, 440, 414], "N", 8, "art studios"),
        B("heron_flats_n", "breeze_block_flats", [444, 400, 490, 416], "N", 16),
        B("heron_climb", "oasia_tower", [494, 400, 522, 428], "N", 30, "climbing gym + homes"),
        T("landing_heron_west", [385, 436, 393, 444]),
        B("heron_terrace", "barbican_terrace", [396, 430, 470, 452], "N", 21),
        S("heron_creek_square", [474, 432, 498, 462], [("planter", 480, 438, "willow"), ("pool", 486, 452, 700, 260), ("planter", 494, 440, "flowering cherry")], "a pool square by the casa"),
        B("heron_casa", "casa_de_vidro", [501, 438, 525, 462], "E", 10, "home"),
        B("heron_sukiya", "sukiya_villa", [385, 462, 415, 494], "W", 7, "home + guest house"),
        G("heron_orchard", [387, 497, 415, 514], gate_x=401, features=["orchard", "kiln yard"]),
        B("heron_hall", "bamboo_hall", [420, 466, 466, 494], "S", 12, "common house"),
        B("heron_creek_flats", "breeze_block_flats", [507, 470, 525, 512], "E", 16),
        B("heron_stahl", "stahl_house", [470, 497, 500, 524], "E", 5, "home"),
        S("heron_lawn", [430, 497, 466, 526], [("tables", 456, 512), ("sail", 442, 506)], "the long lawn"),
        B("heron_bawa", "bawa_courtyard", [390, 518, 424, 550], "S", 8, "homes + kiln"),
        B("heron_shops", "coconut_shophouse", [430, 530, 468, 550], "S", 10, "gallery + homes"),
        B("heron_eichler", "eichler_atrium", [474, 530, 500, 550], "S", 5, "home"),
        B("heron_stilt_c", "stilt_house", [509, 534, 525, 550], "S", 7),
        P("heron_mews", [[385, 423], [490, 423]]),
        P("heron_creek_walk", [[470, 462], [470, 466], [504, 470], [504, 550]]),
    ],
    # SORREL: "the slab and the skyway". Le Corbusier's Unite on pilotis faces the Green (the grocery in its
    # street), a garden skyway on four towers crosses the cell at 17.5 m over three gardens, the Shiroiya hill of little
    # houses is the common house, with courtyard houses, an Eichler court and a butterfly row facing the farms.
    "sorrel": [
        S("sorrel_nw", [220, 400, 235, 424], [("planter", 227, 410, "flowering cherry")], "corner garden"),
        B("sorrel_unite", "unite_habitation", [238, 400, 334, 422], "N", 21, "grocery + homes"),
        B("sorrel_deli", "coconut_shophouse", [337, 400, 360, 420], "N", 9, "deli + homes"),
        T("landing_sorrel_west", [220, 436, 228, 444]),
        G("sorrel_sky_garden_w", [231, 428, 261, 454], gate_x=246, features=["market garden under the skyway"]),
        T("landing_sorrel_mid_w", [264, 436, 272, 444]),
        G("sorrel_sky_garden_c", [275, 428, 305, 454], gate_x=290, features=["dye and flower beds under the skyway", "long dining table"]),
        T("landing_sorrel_mid_e", [308, 436, 316, 444]),
        G("sorrel_sky_garden_e", [319, 428, 349, 454], gate_x=334, features=["herb garden under the skyway", "play corner"]),
        T("landing_sorrel_east", [352, 436, 360, 444]),
        B("sorrel_flats_w", "breeze_block_flats", [220, 458, 238, 518], "W", 16),
        B("sorrel_common", "shiroiya_hill", [262, 462, 318, 494], "S", 14, "common house"),
        B("sorrel_terrace", "barbican_terrace", [338, 458, 360, 518], "E", 21),
        G("sorrel_market_garden", [258, 497, 320, 524], gate_x=290, features=["market garden", "long dining table"]),
        B("sorrel_butterfly", "butterfly_row", [224, 528, 314, 550], "S", 7, "homes"),
        B("sorrel_x100", "eichler_x100", [326, 530, 356, 550], "S", 5, "home"),
        P("sorrel_mews", [[236, 425], [340, 425]]),
        P("sorrel_lane", [[254, 425], [254, 456], [324, 456], [324, 526], [360, 526]]),
    ],
    # CLOVER: "the maker village", by the food forest and the farms. Lever House (slab on an open podium) with Clover
    # Works fab lab in its podium, a Habitat-67 stack beside the two NE canopy towers, stilt houses
    # facing the food forest, a stacked-stone Corbero common house, the Eames House as a studio on the farm lane.
    "clover": [
        B("clover_ando", "ando_courtyard", [50, 400, 68, 420], "N", 8, "home + workshop"),
        B("clover_works", "lever_slab", [72, 400, 122, 432], "N", 27, "fab lab + homes"),
        S("clover_yard", [124, 400, 137, 440], [("bikes", 130, 408), ("tables", 130, 424)], "the works yard: bikes and tables"),
        B("clover_habitat", "habitat67", [139, 400, 179, 440], "N", 20, "homes + maker roof terraces"),
        T("landing_clover_north", [182, 400, 190, 408]),
        T("landing_clover_east", [182, 436, 190, 444]),
        B("clover_eichler_1", "eichler_atrium", [50, 440, 78, 460], "W", 5, "home"),
        B("clover_eichler_2", "eichler_atrium", [50, 463, 78, 483], "W", 5, "home"),
        B("clover_eichler_3", "eichler_atrium", [50, 486, 78, 506], "W", 5, "home"),
        B("clover_common", "corbero_house", [96, 458, 134, 486], "N", 10, "common house"),
        G("clover_garden", [81, 492, 160, 518], gate_x=115, features=["kitchen garden", "long dining table", "play corner"]),
        B("clover_hedgerow", "hedgerow_house", [141, 455, 163, 483], "N", 6, "home"),
        B("clover_repair", "coconut_shophouse", [168, 452, 190, 486], "E", 9, "repair cafe + homes"),
        B("clover_eames", "eames_house", [56, 534, 102, 550], "S", 8, "studio + home"),
        B("clover_eichler", "eichler_court", [110, 522, 166, 550], "S", 5, "homes"),
        B("clover_flats_se", "breeze_block_flats", [172, 494, 190, 550], "E", 16),
        P("clover_mews", [[84, 435], [84, 530], [104, 530]]),
        P("clover_cross", [[84, 452], [166, 452]]),
    ],
}

# user request (2026-11-07): Fallingwater straddling Willow Creek. Outside the seven cells on purpose. The creek
# boardwalk runs at x = 565 almost the whole way, so the only stretch with room for a >= 24 m deep plot over the creek
# that stays clear of it is the bow at y ~ 450 (creek centreline x 576.2-578.0 for y 425-475). Front E puts the kind's
# stream (local y = 0.55 d from the front, flowing to local +x = world +y, i.e. upstream end north) on world
# x = x1 - 0.55 d = 578.2, within 1.4 m of the creek. Its author prefers 35 x 32, but at d = 32 any plot whose stream
# sits on the creek would cover the boardwalk, so it is 35 x 25 (1.8 m clear of the boardwalk centreline).
EXTRA = [
    {"cell": "creek_corridor", "exception": "user request: Fallingwater over Willow Creek",
     **B("creek_fallingwater", "fallingwater", [566.9, 433, 591.9, 468], "E", 12, "home + guest house", ["cream", "rust", "ochre"],
         [{"pos_m": [591.9, 450.5], "type": "front door (meadow drive)"}])},
]

# user request (round 2): an ecofuturist central park in the green cell with a community-built castle playground
# (tools/city_build/kinds/park.py central_park draws the castle in its back-west corner). It replaces the Village Green lawn and
# the old natural playground; willow_school stays. build_city reads the ids "village_green" and "playground" by name
# (plan_trees rings blds["village_green"] with shade trees 5 m inside its edge, skipping blds["playground"] + 4 m), so:
#   * "playground"    = the central_park kit over the whole park (its rect shields the park from those ring trees);
#   * "village_green" = a 0.2 m marker open space at the centre of the park's great lawn: its ring loops produce no
#     trees, and SWCityOpenSpace "village_green" scatters its 12 picnics and 8 pairs of deck chairs within about
#     +-15 x +-12 m of it, i.e. on the new great lawn. The place id village_green sits in the park.
PARK = [
    {"id": "playground", "cell": "green", "footprint_m": [222, 258, 358, 370], "front": "S", "arch": "central_park",
     "floors": 1, "height_m": 12.0, "use": "park", "palette": ["natural timber", "clover green", "sky blue"],
     "entrances": [{"pos_m": [290, 370], "type": "main entrance (promenade)"}, {"pos_m": [336, 370], "type": "wetland gate"},
                   {"pos_m": [242, 370], "type": "meadow gate"}, {"pos_m": [290, 258], "type": "school forecourt"}],
     "seed": 4242, "exception": "user request: ecofuturist central park (id kept: build_city reads it)",
     "description": "ecofuturist central park: bioswale and reed wetland, solar-tree grove round a stage, great lawn in a grass bowl, seed dome, pollinator meadows, castle playground"},
    {"id": "village_green", "cell": "green", "footprint_m": [271.9, 319.9, 272.1, 320.1], "floors": 0, "height_m": 0,
     "description": "marker: picnics and deck chairs on the central park's great lawn (id kept: build_city reads it)",
     "palette": ["natural timber"], "entrances": [{"pos_m": [272, 320], "type": "open"}],
     "exception": "user request: ecofuturist central park (id kept: build_city reads it)"},
]

# canopy walk: inter-cell bridges keep their ids (moved along their lanes), plus spans inside the cells
BRIDGES = [
    ("bridge_fern_moss", [[190, 186], [220, 186]]),
    ("bridge_moss_commons", [[360, 115], [385, 115]]),
    ("bridge_commons_reed", [[455, 190], [455, 220]]),
    ("bridge_reed_heron", [[389, 370], [389, 400]]),
    ("bridge_heron_sorrel", [[385, 440], [360, 440]]),
    ("bridge_sorrel_clover", [[220, 440], [190, 440]]),
    ("bridge_clover_birch", [[186, 400], [186, 370]]),
    ("bridge_birch_fern", [[186, 220], [186, 190]]),
    # inside the cells
    ("walk_clover", [[186, 408], [186, 436]]),
    ("walk_heron", [[389, 408], [389, 436]]),
    ("walk_sorrel_1", [[228, 440], [264, 440]]),
    ("walk_sorrel_2", [[272, 440], [308, 440]]),
    ("walk_sorrel_3", [[316, 440], [352, 440]]),
]

# where the walk comes down to the ground and continues along a lane or mews (as it always did across the Commons)
GROUND_LINKS = [
    {"between": ["landing_commons_west", "landing_commons_south"], "via": "the Commons plaza"},
    {"between": ["landing_moss_west", "moss_east"], "via": "moss_mews_s and lane_x2 (moss_east keeps its stairs and lifts)"},
    {"between": ["landing_birch_north", "landing_birch_south"], "via": "lane_x1 along the Village Green"},
    {"between": ["landing_reed_north", "landing_reed_south"], "via": "reed_mews"},
]

# where each life-sim place now sits (only those that move; the rest stay where they are)
PLACES = {
    "reed_common": [402, 273],
    "practice_pods": [474, 362],
}

# street furniture: murals move to new buildings
MURALS = {"sorrel_north": "sorrel_unite", "fern_east": "fern_habitat", "heron_west": "heron_bawa"}


def kind_sizes():
    import sys
    sys.path.insert(0, str(ROOT))
    import importlib, pkgutil
    import tools.city_build.kinds as K
    out = {}
    for m in pkgutil.iter_modules(K.__path__):
        if m.name in K.SKIP or m.name.startswith("_"):
            continue
        try:
            out.update(getattr(importlib.import_module(f"tools.city_build.kinds.{m.name}"), "SIZES", {}))
        except Exception:
            pass
    return out


SIZES = kind_sizes()


def floors_for(h, kind):
    fl = SIZES.get(kind, {}).get("floors")
    n = _floors(h, kind)
    return max(fl[0], min(fl[1], n)) if fl else n


def _floors(h, kind):
    if h >= 9 and kind not in ("bamboo_hall", "casa_de_vidro"):
        return max(1, round(h / 3.5))
    return max(1, round(h / 4.0))


def front_mid(r, front):
    x0, y0, x1, y1 = r
    return {"N": [(x0 + x1) / 2, y0], "S": [(x0 + x1) / 2, y1], "W": [x0, (y0 + y1) / 2], "E": [x1, (y0 + y1) / 2]}[front]


def palette_for(cell, i, seed):
    alt = ALT[cell]
    rnd = random.Random(seed)
    base = alt[:3]
    k = i % 4
    if k == 0:
        return base
    pal = list(base)
    pal[rnd.randrange(3)] = alt[3 + rnd.randrange(3)]
    if k == 3:
        pal = pal[1:] + pal[:1]
    return pal


TREES = {
    "fern": ["flowering cherry", "birch", "apple", "maple"], "moss": ["jacaranda", "fig", "fruit", "flame"],
    "birch": ["oak", "maple", "flowering cherry", "birch"], "reed": ["jacaranda", "flame", "bamboo", "willow"],
    "clover": ["oak", "chestnut", "apple", "maple"], "sorrel": ["flowering cherry", "persimmon", "flame", "maple"],
    "heron": ["willow", "jacaranda", "flowering cherry", "shade"],
}


def grove(cell, e, items):
    """planter-bench trees on a jittered ~11 m grid and a few flowerbeds, clear of the given props and the cell's paths"""
    x0, y0, x1, y1 = e["r"]
    rnd = random.Random(sum(map(ord, e["id"])))
    taken = [(pr[1], pr[2]) for pr in e["props"]]
    lines = [it["line"] for it in items if it["t"] == "path"]

    def clear(x, y, r):
        if any(math.hypot(x - a, y - b) < r for a, b in taken):
            return False
        for pl in lines:
            for i in range(len(pl) - 1):
                (ax, ay), (bx, by) = pl[i], pl[i + 1]
                dx, dy = bx - ax, by - ay
                L = dx * dx + dy * dy or 1
                t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / L))
                if math.hypot(x - ax - t * dx, y - ay - t * dy) < 4:
                    return False
        return True

    out = []
    step = 8.5
    y = y0 + 5
    while y <= y1 - 4:
        x = x0 + 5 + (step / 2 if int((y - y0) / step) % 2 else 0)
        while x <= x1 - 4:
            px, py = x + rnd.uniform(-2, 2), y + rnd.uniform(-2, 2)
            if x0 + 3 <= px <= x1 - 3 and y0 + 3 <= py <= y1 - 3 and clear(px, py, 6) and rnd.random() < 0.75:
                out.append(("planter", round(px, 1), round(py, 1), rnd.choice(TREES[cell]), round(rnd.uniform(1.0, 1.45), 2)))
                taken.append((px, py))
            x += step
        y += step
    for _ in range(3):
        px, py = rnd.uniform(x0 + 4, x1 - 4), rnd.uniform(y0 + 3, y1 - 3)
        if clear(px, py, 4.5):
            out.append(("flowerbed", round(px, 1), round(py, 1)))
            taken.append((px, py))
    return out


def props_cm(props):
    out = []
    for pr in props:
        t = pr[0]
        p = [round(pr[1] * 100, 1), round(pr[2] * 100, 1)]
        if t == "planter":
            out.append({"t": "planter_bench", "p": p, "yaw": 0, "size": 320, "tree": pr[3], "scale": pr[4] if len(pr) > 4 else 1.1})
        elif t == "tables":
            out.append({"t": "tables", "p": p, "yaw": 90, "c": [236, 122, 100]})
        elif t == "sail":
            out.append({"t": "sail", "p": p, "yaw": 20, "size": 900, "c": [240, 232, 214]})
        elif t == "pool":
            out.append({"t": "pool", "p": p, "rx": pr[3], "ry": pr[4]})
        elif t == "flowerbed":
            out.append({"t": "flowerbed", "p": p, "yaw": 0, "lx": 500, "ly": 160})
        elif t == "bikes":
            out.append({"t": "bikes", "p": p, "yaw": 0, "n": 6})
    return out


def build_world():
    w = json.loads(SRC.read_text())
    out = copy.deepcopy(w)
    out["meta"]["version"] = "0.6-varied"
    out["meta"]["changes"] = list(w["meta"].get("changes", [])) + [
        "0.6 (world_varied.json): the seven courtyard blocks re-planned as a varied village of building kinds "
        "(tools/city_build/kinds); canopy walk re-routed over 17.5 m roofs, landing towers and new spans; see out/city_kinds/planner/NOTES.md"]
    for c in out["cells"]:
        if c["id"] in RES:
            c["type"] = "village_block"
            c.pop("floors", None)
    keep = [b for b in w["buildings"] if (b.get("cell") not in RES or b["id"] in KEEP_IDS) and b["id"] not in {e["id"] for e in PARK}]
    keep = [b for b in keep if b.get("type") != "canopy_landing" or b.get("cell") not in RES]
    new, paths = [], []
    for cell in RES:
        for n, e in enumerate(LAYOUT[cell]):
            if e["t"] == "b":
                kind = e["arch"]
                seed = sum(map(ord, e["id"])) * 7 + n
                use, et = USE.get(kind, ("homes", "front door"))
                b = {"id": e["id"], "cell": cell, "footprint_m": e["r"], "front": e["front"], "arch": kind,
                     "floors": floors_for(e["h"], kind), "height_m": float(e["h"]), "use": e["use"] or use,
                     "palette": e["pal"] or palette_for(cell, n, seed),
                     "entrances": e["ent"] or [{"pos_m": front_mid(e["r"], e["front"]), "type": et}], "seed": seed}
                if abs(e["h"] - WALK) < 0.01:
                    b["roof"] = "canopy walk deck at 17.5 m"
                new.append(b)
            elif e["t"] == "court":
                x0, y0, x1, y1 = e["r"]
                gx = e["gate_x"] if e["gate_x"] is not None else (x0 + x1) / 2
                new.append({"id": e["id"], "cell": cell, "type": "courtyard", "footprint_m": e["r"],
                            "features": e["features"] or ["shared garden beds", "fruit trees", "long dining table"],
                            "entrances": [{"pos_m": [gx, y0], "type": "gate"}, {"pos_m": [gx, y1], "type": "gate"}]})
            elif e["t"] == "lawn":
                x0, y0, x1, y1 = e["r"]
                e = dict(e, props=e["props"] + grove(cell, e, LAYOUT[cell]))
                new.append({"id": e["id"], "cell": cell, "type": "square", "footprint_m": e["r"], "floors": 0, "height_m": 0,
                            "description": e["desc"], "palette": ALT[cell][:3], "props": props_cm(e["props"]),
                            "entrances": [{"pos_m": [(x0 + x1) / 2, (y0 + y1) / 2], "type": "open"}]})
            elif e["t"] == "tower":
                host = e["on"]
                new.append({"id": e["id"], "cell": cell, "type": "canopy_landing", "on": host, "footprint_m": e["r"], "floors": 5,
                            "height_m": WALK, "description": "free-standing stair and lift tower of the canopy walk" if not host else f"stair and lift tower on {host}",
                            "materials": "CLT timber, woven bamboo screen", "palette": ["natural timber"]})
            elif e["t"] == "path":
                paths.append({"id": e["id"], "type": "trail", "role": "mews", "cell": cell, "polyline_m": e["line"]})
    for e in EXTRA:
        kind = e["arch"]
        seed = sum(map(ord, e["id"])) * 7
        new.append({"id": e["id"], "cell": e["cell"], "footprint_m": e["r"], "front": e["front"], "arch": kind,
                    "floors": floors_for(e["h"], kind), "height_m": float(e["h"]), "use": e["use"], "palette": e["pal"],
                    "entrances": e["ent"], "seed": seed, "exception": e["exception"],
                    "description": "Frank Lloyd Wright's Fallingwater: cantilevered terraces over the creek's falls"})
    new += [dict(e) for e in PARK]
    # order: the original non-residential buildings in their order, then the new ones
    out["buildings"] = keep + new
    out["paths"] = w["paths"] + paths
    for p in out["paths"]:
        if p.get("type") == "rooftop_path":
            p["notes"] = ("Canopy walk at 17.5 m: sky bridges over the lanes land on 17.5 m roofs (habitat67, kampung, "
                          "breeze-block, barbican terraces, moss_east) or landing towers; spans inside the cells link them.")
    out["sky_bridges"]["segments"] = [{"id": i, "span_m": s} for i, s in BRIDGES]
    out["sky_bridges"]["ground_links"] = GROUND_LINKS
    out["sky_bridges"]["notes"] = ("Every span lands on a canopy-landing tower (stair + lift) or on moss_east's roof deck. Elevated runs: "
                                   "birch N - fern corner - moss W; birch S - clover - the Sorrel skyway - heron - reed SW. "
                                   "ground_links: where the walk comes down and continues along a lane or mews.")
    for pl in out["places"]:
        if pl["id"] in PLACES:
            pl["pos_m"] = PLACES[pl["id"]]
    for f in out["street_furniture"]:
        if f.get("on_building") in MURALS:
            f["on_building"] = MURALS[f["on_building"]]
    return out


def draw(world, png):
    from PIL import Image, ImageDraw, ImageFont
    S_ = 3
    im = Image.new("RGB", (600 * S_, 600 * S_), (196, 214, 170))
    d = ImageDraw.Draw(im)
    R = lambda r: [r[0] * S_, r[1] * S_, r[2] * S_, r[3] * S_]
    for l in world["lanes"]["segments"]:
        d.rectangle(R(l["rect_m"]), fill=(222, 210, 190))
    for c in world["cells"]:
        d.rectangle(R(c["bounds_m"]), outline=(120, 120, 120))
    for p in world["paths"]:
        if p.get("polyline_m"):
            d.line([(q[0] * S_, q[1] * S_) for q in p["polyline_m"]], fill=(170, 150, 120), width=3 * S_)
    cols = {}
    for b in world["buildings"]:
        r = b["footprint_m"]
        t = b.get("type")
        if t == "courtyard":
            d.rectangle(R(r), fill=(150, 196, 110), outline=(80, 120, 60))
        elif t == "square" or b.get("floors", 0) == 0:
            d.rectangle(R(r), fill=(170, 210, 130), outline=(100, 140, 80))
        elif t == "canopy_landing":
            d.rectangle(R(r), fill=(120, 80, 40))
        else:
            h = b.get("height_m", 5)
            g = int(max(40, 230 - h * 5.5))
            d.rectangle(R(r), fill=(g, g, int(g * 0.95)), outline=(30, 30, 30))
            fx, fy = front_mid(r, b.get("front", "N")) if b.get("front") else (None, None)
            if fx is not None:
                d.ellipse([fx * S_ - 5, fy * S_ - 5, fx * S_ + 5, fy * S_ + 5], fill=(220, 40, 40))
            lbl = f"{b.get('arch', b['id'])[:14]}\n{h:g}m"
            d.text((r[0] * S_ + 4, r[1] * S_ + 3), lbl, fill=(255, 255, 255) if g < 140 else (0, 0, 0))
    for s in world["sky_bridges"]["segments"]:
        (ax, ay), (bx, by) = s["span_m"]
        d.line([(ax * S_, ay * S_), (bx * S_, by * S_)], fill=(200, 120, 20), width=4 * S_)
    for pl in world["places"]:
        x, y = pl["pos_m"]
        d.rectangle([x * S_ - 6, y * S_ - 6, x * S_ + 6, y * S_ + 6], fill=(40, 90, 220))
        d.text((x * S_ + 8, y * S_ - 6), pl["id"], fill=(20, 40, 140))
    png.parent.mkdir(parents=True, exist_ok=True)
    im.save(png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", default=str(ROOT / "out" / "city_kinds" / "planner" / "plan.png"))
    ap.add_argument("--out", default=str(DST))
    args = ap.parse_args()
    world = build_world()
    Path(args.out).write_text(json.dumps(world, indent=1) + "\n")
    draw(world, Path(args.png))
    n = sum(1 for b in world["buildings"] if b.get("arch"))
    print(f"wrote {args.out}: {n} kind buildings, {len(world['sky_bridges']['segments'])} sky spans; plan {args.png}")


if __name__ == "__main__":
    main()
