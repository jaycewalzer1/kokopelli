"""The lunch's words (kokopelli/agents/lunch_wm.py): the two personas and situations, the lunch topic, the world-model
prompt, the reply-format notes, what Lunch tells a mind (LunchWords), and the residents who stay quiet unless spoken
to."""
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:   # imported through lunch_wm, which set up the path already, this is a no-op
    sys.path.insert(0, str(HERE))
import live  # noqa: E402
ROOT = live.ROOT
for _p in (ROOT, ROOT / "kokopelli" / "wm" / "controls"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from live import Cast, bearing, compass, rough  # noqa: E402
from live_wm import REACH_M  # noqa: E402
from lunch_fixes import TALK_SHOWN  # noqa: E402

HEAR_M = live.HEAR_M

# Qwen sometimes put its words in "diary" with no "text" (bodies demo); these show it the exact shape.
FORMAT_NOTE = ('\nAlways write "action" as an object with its fields inside it. To speak, put your exact words in "text": '
               '{"type": "say", "text": "Iris! There you are."}. The diary is a private note, nobody hears it.')
RETRY_SHAPE = ('{"thought": "<one sentence>", "action": {"type": "say", "text": "<the words you say out loud>"}, '
               '"diary": "<optional note>"}')
IRIS_WHO = ("You are Iris, 41, a beekeeper who keeps the hives on the Fern Court roofs and fixes bikes at Clover Works "
            "two days a week. You live in Fern Court, two doors from Mara. You're dry-humoured and practical, and you "
            "notice weather, insects and anything with a broken spoke.")
MARA_SITUATION = ("It's Saturday, just before half past twelve. Yesterday you and your neighbour Iris agreed to meet at "
                  "The Kettle (kettle_cafe) for lunch today, get something to eat together, then sit and catch up. You "
                  "haven't really talked in two weeks: you want to hear how her bees are doing, and to tell her that "
                  "Loom & Thread asked you to design the banners for the harvest fair. Iris is 41, a beekeeper, about "
                  "your height, usually in a canvas jacket.")
IRIS_SITUATION = ("It's Saturday, just before half past twelve. You just came out of Rise Bakery with a loaf for the "
                  "weekend. Yesterday you and your neighbour Mara agreed to meet at The Kettle (kettle_cafe) for lunch "
                  "today, get something to eat together, then sit and talk. You have news: one of your hives swarmed on "
                  "Thursday and you caught the swarm in the Fern Court plum tree. Mara is 34, a textile designer, "
                  "warm and chatty.")
LUNCH_TOPIC = {"lunch|soup|sandwich|eat|food|hungry|menu": "Lunch today is nettle soup with rye, or a halloumi flatbread. "
               "Two bowls are on the end of the bar, help yourselves, and grab the table by the window."}
WM_PROMPT = ("First-person view of someone walking through a sunny solarpunk village around midday, at eye level. "
             "Timber apartment buildings with planted balconies, vines and green roofs line paved streets and footpaths; "
             "flowering shrubs, fruit trees and community gardens; solar panels and copper domes on the roofs; neighbours "
             "walking, chatting and carrying things; a cafe with tables outside; wooded hills on the horizon, deep blue sky "
             "with white clouds. Live-action video, natural light, realistic materials, steady handheld camera.")

# --view-prompts (P5, off by default): one world-model prompt per view, for the varied city around Fern Court
# (data/city/world.json: fern_kettle and fern_rise are three-storey coconut_shophouse buildings in sage, cream, brass and
# coral; Kettle Square has cafe tables under a sail; fern_hall is a bamboo hall), with every person described by the
# same words in every view (LOOKS, from tools/bodies/looks.json plus the clothes the personas mention). The bodies are
# still drawn in grey underwear (no outfits in Bodies.json), so the clothes here are the prompt-side way to dress them.
LOOKS = {
    "mara": ("a woman of about thirty with fair, lightly freckled skin and long, loosely wavy dark-brown hair, wearing a "
             "rust-red linen shirt with rolled sleeves and loose cream trousers"),
    "iris": ("a tall woman of about forty with dark brown skin and short natural black curls, wearing a tan canvas work "
             "jacket over a charcoal t-shirt and olive trousers"),
    "ana": ("a young woman with medium-brown skin and a dark ponytail, wearing a sage-green apron over a white t-shirt"),
}
FERN_COURT = ("Fern Court, a car-free solarpunk neighbourhood at midday in early autumn: three-storey timber shophouses "
              "in sage, cream and coral with brass trim, vines trailing off their roof edges and planters on every "
              "balcony; ground floors are open shopfronts, a bakery and a cafe called The Kettle. Kettle Square has "
              "small cafe tables under a white sail canopy. A tall open bamboo hall, low courtyard houses, fruit trees, "
              "wildflower beds and a pale stone footpath with moss between the stones. Clear blue sky with a few white "
              "clouds, warm overhead sun, soft short shadows.")
VIEW_STYLE = ("Live-action footage filmed at eye level from a person's own point of view as they walk, a natural "
              "handheld sway, 24 mm lens, everything in focus, realistic materials and skin, true-to-life colour.")


def view_prompt(viewer, others):
    """The world-model prompt for `viewer`'s eyes: the place, then each person they may see, worded the same in every
    view so a person looks the same in both films."""
    seen = [f"{LOOKS[o]}" for o in others if o in LOOKS and o != viewer]
    people = (" People you may see: " + "; ".join(seen) + ". They stand and walk naturally, with natural faces and hands."
              if seen else "")
    return f"{VIEW_STYLE} {FERN_COURT}{people}"


def prompts_for(args, ids):
    """Each stream's world-model prompt: --wm-prompt for all, or with --view-prompts one per view."""
    if not getattr(args, "view_prompts", False):
        return {k: args.wm_prompt for k in ids}
    return {k: view_prompt(k, [*ids, "ana"]) for k in ids}


def people(args, nav):
    meet = nav.places[args.meet]["name"]
    args.meet_name = meet
    sit_m = MARA_SITUATION.replace("The Kettle (kettle_cafe)", f"{meet} ({args.meet})")
    sit_i = IRIS_SITUATION.replace("The Kettle (kettle_cafe)", f"{meet} ({args.meet})")
    who_m, who_i = live.DEFAULT_WHO, IRIS_WHO
    if getattr(args, "life", None):   # --life (lunch_life.py): add each person's generated past under the persona
        from lunch_life import with_past
        who_m, who_i = with_past(who_m, args.life, "mara"), with_past(who_i, args.life, "iris")
    args.first = {"id": "mara", "name": "Mara", "who": who_m, "situation": sit_m,
                  "start_note": "You just stepped out of the Fern Common House."}
    args.second = {"id": "iris", "name": "Iris", "who": who_i, "situation": sit_i,
                   "start_note": "You just stepped out of Rise Bakery with a loaf under your arm."}


class QuietCast(Cast):
    """live.Cast, but a resident only answers a line when it's her first greeting, a topic or place she knows, or she's
    named. Otherwise the barista answered every line Mara and Iris said to each other ("Ha, fair enough.")."""

    def reply(self, pid, text, listener_xy):
        p = self.people[pid]
        first = pid not in self.met
        named = p["name"].split()[0].lower() in text.lower()
        line = super().reply(pid, text, listener_xy)
        if not first and not named and line in p.get("fallback", ()):
            return None
        return line


def lunch_cast(nav):
    """live.py's residents, quiet unless spoken to, with the barista at the meeting place able to talk about lunch
    (npcs.json is not edited)."""
    cast = QuietCast(nav, HERE / "npcs.json")
    for p in cast.people.values():
        if p.get("stay_at") == "kettle_cafe":
            p["topics"] = {**LUNCH_TOPIC, **p["topics"]}
    return cast


class LunchWords:
    """What Lunch tells a mind (needs self.world, self.nav, self.cast, self.minds)."""

    # --- what a mind is told
    def describe(self, mind):
        bodies = self.world.bodies()
        me = bodies[mind.id]
        here, near = self.nav.place_at(me.xy), self.nav.place_at(me.xy, 40.0)
        where = (f"at {self.nav.places[here]['name']}" if here else
                 f"out in the streets near {self.nav.places[near]['name']}" if near else "out in the streets")
        lines = [f"Time: {self.world.clock[:5]}.", f"You are {where}, {me.posture}, carrying {me.held or 'nothing'}."]
        if mind.route:
            lines.append(f"You are walking to {self.nav.places[mind.goal_place]['name']}, "
                         f"{rough(self.nav.length(me.xy, mind.route))} to go.")
        close = []
        other = self.minds[mind.other]
        d = math.dist(me.xy, bodies[other.id].xy)
        if d <= HEAR_M:
            close.append(f"- {other.id}: {other.name}, your neighbour, {rough(d)} {bearing(me.xy, me.yaw, bodies[other.id].xy)}")
        for pid, xy in self.world.npcs():
            d = math.dist(me.xy, xy)
            if d <= HEAR_M and self.cast:
                p = self.cast.people[pid]
                close.append(f"- {pid}: {p['name']}, {p['role']}, {rough(d)} {bearing(me.xy, me.yaw, xy)}")
        lines.append("Who is right next to you (close enough to talk):\n" + ("\n".join(close) if close else "- nobody"))
        d = math.dist(me.xy, bodies[other.id].xy)
        if d <= HEAR_M:   # a bare list line wasn't enough: Iris wrote "Mara's inside" with Mara 2 m away (bodies demo)
            lines.append(f"{other.name} is here with you now ({rough(d)}), out in the open: talk to her directly, "
                         f"she hears everything you say.")
        reach = [f"- {oid}" for oid, xy, held in self.world.objects() if not held and math.dist(me.xy, xy) <= REACH_M]
        if reach:
            lines.append("Within arm's reach:\n" + "\n".join(reach))
        lines.append("Anyone or anything farther away, you only know from what you see in the picture.")
        ranked = sorted(self.nav.places.items(), key=lambda kv: math.dist(me.xy, self.nav.doors[kv[0]]))
        lines.append("Places you know in the village (nearest first):\n" + "\n".join(
            f"- {pid}: {p['name']} ({p['category'].replace('_', ' ')}), {rough(math.dist(me.xy, self.nav.doors[pid]))} "
            f"{compass(me.xy, self.nav.doors[pid])}" for pid, p in ranked[:14]))
        return "\n".join(lines)

    def prompt(self, mind):
        heard = "\n".join(mind.heard) if mind.heard else "(nothing)"
        notes = "\n".join(f"- {d}" for d in mind.diary[-8:]) or "(none yet)"
        recent = "\n".join(f"- {r}" for r in mind.recent[-6:]) or "(nothing yet)"
        talk = ""
        if "memory" in getattr(self, "fixes", ()):   # lunch_fixes.py: otherwise an answer is gone one step after it's heard
            shown = mind.talk[-TALK_SHOWN:]
            talk = ("The conversation so far (oldest first; don't ask again what was already answered):\n"
                    + ("\n".join(f"- {t}" for t in shown) if shown else "- (nothing said yet)") + "\n")
        return (f"{mind.who}\n\nSituation: {mind.situation}\n\n"
                f"The image is what you see right now, through your own eyes.\n\n{self.describe(mind)}\n\n"
                f"{talk}What you did and said recently:\n{recent}\nWhat just happened: {mind.last}\nWhat you heard:\n{heard}\n\n"
                f"Your notes so far:\n{notes}\n\n{live.ACTIONS}{FORMAT_NOTE}")
