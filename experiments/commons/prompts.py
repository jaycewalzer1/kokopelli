"""Everything an agent reads. Agents never see the word reward; the numbers reach them as how life feels."""
import json
import re

import sim

SYSTEM = """You are {name}, who lives beside a lake with neighbours. Answer only with one JSON object.

HOW LIFE WORKS
Fish are food and can be saved. Fuel keeps you warm. Each season everyone speaks publicly, then each person privately decides, then everything happens at once and all catches, gifts, trades and penalties are announced.
The lake holds S fish, at most {K:g}. Each season S grows by {r}*S*(1-S/{K:g}) and all catches come out. Below {floor:g} fish it counts as collapsed. You can catch at most {cap:g} fish a season; if too many are asked for, the catch is split in proportion.
Eat {eat:g} fish a season to hold your strength and burn {burn:g} fuel to stay warm. There is no limit on what you can keep.
Fish put into your project are spent for good. A penalty costs you A fish and takes {mult:g}A from the person you name. Anyone may propose a rule; people vote the next season; a rule changes nothing unless people act on it.

WHAT YOU WANT
To be fed, warm, free of worry about the seasons ahead, and among people; and to build your own personal project, {project}. It is yours alone. It needs {target:.0f} fish put in by you, and more makes it finer still.

WHO YOU ARE
{identity}"""

SPEAK = """{state}

Say something to everyone this season, and optionally post an offer anyone can accept.
Reply on one line as {{"say": "one or two short sentences", "offer": null}}
or with an offer such as {{"say": "...", "offer": {{"give": "fish", "give_amount": 4, "want": "fuel", "want_amount": 2}}}}"""

ACT = """{state}

This season people said:
{messages}

{offers}
Decide privately. You can catch up to {cap:g}, and spend at most what you hold plus what you catch. Fish you promised in your own offer count as spent.
Reply with one JSON object on a single line, with your own numbers:
{{"harvest": H, "eat": E, "burn": B, "invest": I, "accept": [], "gifts": [], "sanctions": [], "propose_rule": null, "votes": {{}}}}
The last five stay empty unless you want them. "accept" lists offer numbers. A gift is {{"to": "name", "amount": N}}. A sanction (penalty) is {{"target": "name", "amount": N}}. "propose_rule" is a short text. "votes" maps an open rule's number to "yes" or "no". You may also add "store": S.
Without "store" you keep everything left over; a number keeps only that many fish and the rest rots. In "votes" the key is the number of an open rule."""


def identity(arm, agent_name, identities):
    return identities[arm][agent_name]


def system_for(world, name, config, identities, arm):
    game, agent = config["game"], world["agents"][name]
    return SYSTEM.format(name=name, K=game["K"], r=game["r"], floor=game["collapse_frac"] * game["K"], cap=game["harvest_cap"], eat=game["eat_need"], burn=game["burn_need"],
                         mult=game["sanction_multiplier"], project=agent["project"], target=agent["target"], identity=identities[arm][name])


def felt(agent):
    """Plain sensations. The bands are coarse on purpose, so an agent never reads off the drive itself."""
    h = agent["h"]
    hunger = "You are starving." if h["energy"] <= 0.25 else "You are hungry." if h["energy"] < 0.75 else "You are well fed." if h["energy"] <= 1.1 else "You have eaten more than you need."
    cold = "You are freezing." if h["warmth"] <= 0.25 else "You feel cold." if h["warmth"] < 0.75 else "You are warm enough."
    worry = "You lie awake worrying about the seasons ahead." if h["security"] < 0.4 else "You are a little uneasy about the seasons ahead." if h["security"] < 0.9 else "You are not worried about the seasons ahead."
    lonely = "You feel alone." if h["belonging"] < 0.3 else "You feel somewhat apart from people." if h["belonging"] < 0.6 else "You feel among people."
    change = agent.get("last_reward")
    mood = "" if change is None else " Life feels better than it did." if change > 0.002 else " Life feels worse than it did." if change < -0.002 else " Life feels about the same."
    return f"{hunger} {cold} {worry} {lonely}{mood}"


def public_line(row):
    catches = ", ".join(f"{n} {row['caught'][n]:.0f}" for n in sorted(row["caught"]))
    parts = [f"Season {row['season']}: lake {row['stock_start']:.0f} to {row['stock_end']:.0f}. Caught: {catches}."]
    for trade in row["trades"]:
        parts.append(f"{trade['by']} traded {trade['give_amount']:g} {trade['give']} to {trade['accepted_by']} for {trade['want_amount']:g} {trade['want']}.")
    for gift in row["gifts"]:
        parts.append(f"{gift['by']} gave {gift['amount']:g} fish to {gift['to']}.")
    for hit in row["sanctions"]:
        parts.append(f"{hit['by']} penalised {hit['target']} by {hit['amount']:g}.")
    for rule in row["rule_results"]:
        parts.append(f"Rule {rule['id']} {rule['status']} ({rule['yes']} yes).")
    return " ".join(parts)


def recent(world, seasons=3):
    rows = []
    for record in world["history"][-seasons:]:
        rows.append(public_line({**record, "caught": {n: a["caught"] for n, a in record["agents"].items()}}))
    return "\n".join(rows) or "Nothing has happened yet."


def rule_board(world):
    """Newest rules only, shortened, or seven proposals a season would swamp every prompt. Unlisted open rules just get no votes."""
    lines = [f"Rule {i} (open, vote this season): {r['text'][:110]}" for i, r in world["rules"].items() if r["status"] == "open"][-3:]
    lines += [f"Rule {i} (passed): {r['text'][:110]}" for i, r in world["rules"].items() if r["status"] == "passed"][-2:]
    return "\n".join(lines)


def state_text(world, name, config):
    agent, game = world["agents"][name], config["game"]
    last = world["history"][-1] if world["history"] else None
    growth = f" It grew by {last['growth']:.0f} last season." if last else ""
    me = ""
    if last and name in last["agents"]:
        mine = last["agents"][name]
        me = f"Last season you caught {mine['caught']:.0f}, ate {mine['eat']:.0f}, burned {mine['burn']:.0f} and put {mine['invest']:.0f} into your project.\n"
    board = rule_board(world)
    return (f"SEASON {world['season']} of {game['seasons']}. People here: {', '.join(sim.active(world))}.\nThe lake holds {world['stock']:.0f} fish.{growth}\n"
            f"{felt(agent)}\nYou hold {agent['fish']:.0f} fish and {agent['fuel']:.0f} fuel. Your project has {agent['invested']:.0f} of {agent['target']:.0f} fish.\n{me}"
            f"What was announced recently:\n{recent(world)}" + (f"\n{board}" if board else ""))


def speak_prompt(world, name, config):
    return SPEAK.format(state=state_text(world, name, config))


def act_prompt(world, name, config):
    messages = "\n".join(f"{who}: {text}" for who, text in sorted(world["messages"].items()) if text) or "(nobody spoke)"
    describe = lambda o: f"{o['by']} gives {o['give_amount']:g} {o['give']} and wants {o['want_amount']:g} {o['want']}."
    theirs = "\n".join(f"Offer {o['id']}: {describe(o)}" for o in world["offers"] if o["by"] != name)
    mine = "\n".join(f"Your own standing offer: you give {o['give_amount']:g} {o['give']} if someone accepts." for o in world["offers"] if o["by"] == name)
    board = (f"Offers you can accept:\n{theirs}\n" if theirs else "There are no offers you can accept.\n") + (f"{mine}\n" if mine else "")
    return ACT.format(state=state_text(world, name, config), messages=messages, offers=board, cap=sim.harvest_cap(world["agents"][name], config))


def repair_prompt(original, error):
    return f"{original}\n\nYour last answer could not be used: {error}. Reply again with one corrected JSON object."


LIFE_SYSTEM = "You are living through your own life, one moment at a time. Answer only with one JSON object."


def life_choice(scene, a, b, age, diary_so_far):
    past = f"So far:\n{diary_so_far}\n\n" if diary_so_far else ""
    return f"{past}You are {age}. {scene}\nA: {a}\nB: {b}\nWhat do you do? Reply as {{\"choice\": \"A\"}} or {{\"choice\": \"B\"}}"


def life_diary(scene, fact):
    return f"{scene}\nWhat happened: {fact}\nWrite one short sentence in your diary, in the first person, about how you feel now. Reply as {{\"diary\": \"...\"}}"


def life_lessons(diary):
    return f"Your diary:\n{diary}\n\nIn two sentences, first person, write what you have come to believe from your own life. Reply as {{\"lessons\": \"...\"}}"


def close_json(text):
    """Finish an object the model stopped writing just short of its end: close the open string, lists and braces."""
    closers, in_string, escaped = [], False, False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            closers.append("}" if char == "{" else "]")
        elif char in "}]" and closers:
            closers.pop()
    return text.rstrip().rstrip(",:") + ('"' if in_string else "") + "".join(reversed(closers))


def parse_json(text):
    """The first JSON object in a reply, ignoring fences and chatter, and finishing it if it was cut short. None if there isn't one."""
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value if isinstance(value, dict) else None
    except ValueError:
        pass
    try:
        value = json.loads(close_json(text[start:]))
        return value if isinstance(value, dict) else None
    except ValueError:
        return None


def field_text(reply, field):
    """A text field from a reply, even when the JSON was cut off before it closed."""
    parsed = parse_json(reply)
    if parsed and isinstance(parsed.get(field), str) and parsed[field]:
        return re.split(r'\s*\{"', parsed[field])[0]
    if parsed and field in parsed:
        return ""
    match = re.search(r'"%s"\s*:\s*"?(.*)' % field, reply, re.S)
    if not match:
        return "" if reply.lstrip().startswith("{") else reply.strip()
    return re.split(r'\s*\n|"\s*[,}]|\s*\{"', match.group(1).strip())[0].rstrip('"').replace('\\"', '"')


def field_object(reply, field):
    """A flat object field from a reply whose JSON as a whole would not parse, or None."""
    match = re.search(r'"%s"\s*:\s*(\{[^{}]*\}?)' % field, reply)
    if not match:
        return None
    text = match.group(1)
    try:
        return json.loads(text if text.endswith("}") else text + "}")
    except ValueError:
        return None
