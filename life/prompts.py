"""The generator's prompts, in three layers: core rules, the kind of stretch being written, and this call's data."""
import re

from life.windows import depth

CORE = """You write the world around one simulated person's life, one stretch of time at a time.

Rules:
- Write what the world does: places, routines, other people, things that happen.
- Never say what the person chooses, decides, feels, wants, thinks or plans. Another system decides those. Describe only what could be seen from outside.
- Most of life is ordinary. Prefer small, concrete, specific details over drama.
- Time moves forward and the person grows. Write what is different now. Do not reuse images, objects or phrases from MEMORY unless one matters to what happens next.
- Fit the person's age and the time and place. Do not contradict anything under KNOWN, MEMORY or EARLIER.
- Use the names given. Do not name new relatives unless the data has them.
- Reply with one JSON object and nothing else: no code fence, no commentary."""

EXAMPLES = {
    "life": 'Example of the setting\'s form, about someone else: "A dairy family in rural Wisconsin with little spare money and three older siblings. The farm\'s debts and the nearby county school will shape most of what is possible."',
    "period": 'Example of the setting\'s form, about someone else: "Days now revolve around the new daycare on weekdays. An aunt moves in for the winter, and bedtime shifts earlier."',
}

KINDS = {
    "life": "You are sketching a whole life from age 2 to 30 before it happens, as background notes: family circumstances, money, neighborhood and the long-running forces likely to shape it. Write no scene: no weather, objects or moments.",
    "period": "You are writing a period of time the way a biographer summarizes it: routines, who is around, and what changed. Write no scene: no single moments, and no weather or sensory detail unless it changed something.",
    "day": "You are writing one day. Give what this particular day holds, in order.",
    "scene": "You are writing a short moment inside a day. Stay in the immediate surroundings and keep it brief.",
}

OPENING = """Write the opening, before this stretch has happened.
Return exactly:
{"salience": 0.0, "setting": "1 to 3 sentences", "pressures": [{"text": "something that might come up", "odds": 0.0}], "open_questions": ["something unresolved"]}

salience is how much this stretch would stand out years later, compared with others of the same length:
0.0 to 0.3: ordinary, like about 8 in every 10
0.3 to 0.7: somewhat memorable
0.7 to 0.85: rare and clearly memorable
0.85 to 1.0: a few times in a whole life, such as a death, a birth, a serious accident or a move
A stretch where nothing changes is under 0.1. A hospital visit, a new school or a new sibling is at least 0.5.

pressures: 0 to 3 outside situations that may come up, each with odds from 0 to 1 that it does. Most ordinary stretches have 0 or 1.
open_questions: 0 to 2 short items."""

CLOSING = """Write the closing, now that this stretch is over.
Return exactly:
{"summary": "one plain sentence", "what_happened": "1 to 3 sentences"}

Pressures under RESOLVED have already been decided. Report them as decided: one marked didnt_arise did not happen.
The summary is what would still be remembered of this stretch later."""

# The resolver names new people "Person 1234" for now. Showing those would teach the model to write them.
PLACEHOLDER_NAME = re.compile(r"^Person \d+$")


def kind_of(level):
    if level == "life":
        return "life"
    if depth(level) < depth("day"):
        return "period"
    return "day" if level == "day" else "scene"


def _who(seed):
    family = ", ".join(f"{person['name']} ({person['relationship']})" for person in seed.family)
    lines = [seed.prompt, f"Born {seed.birth_date.isoformat()}"]
    lines += [f"{name}: {value}" for name, value in (("Place", seed.place), ("Era", seed.era), ("Family", family),
                                                     ("Temperament", seed.temperament)) if value]
    return "\n".join(lines)


def _when(context):
    window = context["window"]
    return (f"{window.level}: {window.label} ({window.start.date().isoformat()} to {window.end.date().isoformat()})\n"
            f"Age {context['age']:.1f}, {context['stage']['name'].replace('_', ' ')} stage")


def _known(state):
    # Money and skills are left out while the resolver only moves them at random.
    people = [f"{name} ({person['relationship']})" for name, person in sorted(state["people"].items())
              if not PLACEHOLDER_NAME.match(name)]
    return "\n".join(line for line in (state["place"] and f"Lives in {state['place']}", people and f"People: {', '.join(people)}") if line)


def _memory(memory):
    parts = []
    if memory["outline"]:
        parts.append("The period this falls in:\n" + "\n".join(f"- {item['label']}: {item['setting']}" for item in memory["outline"]))
    if memory["recent"]:
        lines = [f"- {item['label']}: {item.get('what_happened') or item['summary']}" for item in memory["recent"]]
        parts.append("Recently, nearest last:\n" + "\n".join(lines))
    if memory["vivid"]:
        parts.append("Stands out from further back:\n" + "\n".join(f"- {item['label']}: {item['summary']}" for item in memory["vivid"]))
    return "\n\n".join(parts) or "Nothing yet."


def _sections(*pairs):
    return "\n\n".join(f"{title}\n{body}" for title, body in pairs if body)


def opening_prompt(seed, context, anchors, focus):
    kind = kind_of(context["window"].level)
    system = "\n\n".join(part for part in (CORE, KINDS[kind], OPENING, EXAMPLES.get(kind)) if part)
    user = _sections(("PERSON", _who(seed)), ("KNOWN", _known(context["state"])), ("MEMORY", _memory(context["memory"])),
                     ("FIXED, HAPPENS DURING THIS STRETCH, SO NOT A PRESSURE", "\n".join(anchors)), ("THIS STRETCH TURNS TOWARD", focus), ("WRITE THE OPENING FOR", _when(context)))
    return system, user


def closing_prompt(seed, context):
    opening = context["opening"]
    system = "\n\n".join((CORE, KINDS[kind_of(context["window"].level)], CLOSING))
    texts = {pressure["id"]: pressure["text"] for pressure in opening["pressures"]}
    resolved = "\n".join(f"- {texts[item['id']]}: {item['outcome']}" for item in context["outcomes"])
    # An action is what could be seen from outside. Why they did it stays with the agent.
    actions = "\n".join(f"- {choice['verb']} ({choice['stance']})" for choice in context["choices"])
    parts = "\n".join(f"- {kid['label']}: {kid['summary']}" for kid in context["children"])
    user = _sections(("PERSON", _who(seed)), ("KNOWN", _known(context["state"])), ("MEMORY", _memory(context["memory"])),
                     ("THE OPENING WAS", opening["setting"]), ("EARLIER IN THIS STRETCH", parts), ("RESOLVED", resolved),
                     ("WHAT THEY DID", actions), ("WRITE THE CLOSING FOR", _when(context)))
    return system, user
