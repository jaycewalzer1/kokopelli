"""The seeded lake game. No LLM here: phases take plain dicts of messages and actions from whoever is playing."""
import copy
import hashlib
import json
import math
import random
from pathlib import Path

import yaml

import rewards as rw

HERE = Path(__file__).parent
NAMES = ["Asa", "Bram", "Cleo", "Dov", "Esme", "Finn", "Greer", "Hale", "Ines", "Joss", "Kit", "Lena",
         "Milo", "Nell", "Otis", "Pia", "Quin", "Rhea", "Sol", "Tove", "Uri", "Vera", "Wren", "Yara"]
PROJECTS = ["a stone boathouse", "a small printing press", "a glass greenhouse", "a loom workshop", "a bell for the hill chapel",
            "a stage for travelling players", "a cider press", "a library of bound maps", "a smithy", "a timber observatory",
            "a walled orchard", "a pottery kiln"]
GOODS = ("fish", "fuel")


class InvalidAction(ValueError):
    pass


def load_config(path=None):
    return yaml.safe_load(Path(path or HERE / "config.yaml").read_text())


def config_hash(path=None):
    return hashlib.sha256(Path(path or HERE / "config.yaml").read_bytes()).hexdigest()


def rng(*parts):
    """A random stream named by its parts, as in life/seed.py, so one draw never shifts another."""
    return random.Random(":".join(str(part) for part in parts))


def new_world(config, seed):
    """Names, wealth, fuel income and projects depend only on the seed, so every arm gets the same ones."""
    game = config["game"]
    draw = rng("world", seed)
    names = draw.sample(NAMES, game["n_agents"])
    projects = draw.sample(PROJECTS, game["n_agents"])
    shares = [draw.random() ** 2 for _ in names[:-1]]
    spare = game["fuel_income_total"] - game["fuel_income_min"] * len(shares)
    incomes = [game["fuel_income_min"] + spare * share / sum(shares) for share in shares] + [game["burn_need"]]
    agents = {}
    for index, name in enumerate(names):
        last = index == len(names) - 1
        agents[name] = {"fish": game["defector_start_fish"] if last else draw.uniform(*game["start_fish"]),
                        "fuel": game["defector_start_fuel"] if last else draw.uniform(*game["start_fuel"]),
                        "fuel_income": incomes[index], "project": projects[index], "invested": 0.0,
                        "target": draw.uniform(*game["project_target"]), "h": rw.start_state(), "active": not last,
                        "reward_total": 0.0, "needs_met": 0, "seasons": 0}
    fish = sum(a["fish"] for a in agents.values())
    fuel = sum(a["fuel"] for a in agents.values())
    return {"seed": seed, "season": 1, "stock": game["K"], "agents": agents, "defector": names[-1], "offers": [], "rules": {},
            "next_rule": 1, "next_offer": 1, "last_public": None, "collapsed_at": None, "history": [],
            "ledger": {"fish_in": fish, "harvested": 0.0, "eaten": 0.0, "invested": 0.0, "spoiled": 0.0, "sanction_paid": 0.0,
                       "sanction_destroyed": 0.0, "fuel_in": fuel, "fuel_income": 0.0, "burned": 0.0}}


def active(world):
    return [name for name, agent in world["agents"].items() if agent["active"]]


def begin_season(world, config):
    """Newcomer arrives, fuel income lands, and a fresh board for this season's offers opens."""
    game = config["game"]
    if world["season"] == game["defector_enters"]:
        world["agents"][world["defector"]]["active"] = True
    for name in active(world):
        agent = world["agents"][name]
        agent["fuel"] += agent["fuel_income"]
        world["ledger"]["fuel_income"] += agent["fuel_income"]
    world["offers"] = []
    world["messages"] = {}


def _amount(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise InvalidAction(f"{label} must be a number that is 0 or more")
    return float(value)


def apply_discussion(world, messages):
    """Public talk and optional standing offers. An offer is open to anyone until the season's actions resolve."""
    world["messages"] = {}
    for name in sorted(messages):
        entry = messages[name]
        world["messages"][name] = str(entry.get("say") or "").strip()[:400]
        offer = entry.get("offer")
        if offer:
            give, want = offer["give"], offer["want"]
            if give not in GOODS or want not in GOODS or give == want:
                raise InvalidAction("an offer swaps fish for fuel or fuel for fish")
            world["offers"].append({"id": world["next_offer"], "by": name, "give": give, "give_amount": _amount(offer["give_amount"], "give_amount"),
                                    "want": want, "want_amount": _amount(offer["want_amount"], "want_amount")})
            world["next_offer"] += 1


def empty_action():
    return {"harvest": 0.0, "eat": 0.0, "burn": 0.0, "invest": 0.0, "store": None, "accept": [], "gifts": [], "sanctions": [], "propose_rule": None, "votes": {}}


def validate_action(world, name, raw, config):
    """Return a clean action or raise InvalidAction with a message the agent can use to repair it."""
    action = empty_action()
    if not isinstance(raw, dict):
        raise InvalidAction("the answer must be one JSON object")
    for key in ("harvest", "eat", "burn", "invest"):
        action[key] = _amount(raw.get(key) or 0, key)
    if raw.get("store") is not None:
        action["store"] = _amount(raw["store"], "store")
    agent = world["agents"][name]
    cap = harvest_cap(agent, config)
    if action["harvest"] > cap:
        raise InvalidAction(f"harvest is at most {cap:g} this season")
    others = set(active(world)) - {name}
    offers = {offer["id"]: offer for offer in world["offers"]}
    for offer_id in _listed(raw.get("accept")):
        if offer_id not in offers or offers[offer_id]["by"] == name:
            raise InvalidAction(f"there is no offer {offer_id} you can accept")
        action["accept"].append(offer_id)
    for key, who, kind in (("gifts", "to", "gift"), ("sanctions", "target", "sanction")):
        for item in _listed(raw.get(key)):
            if not isinstance(item, dict) or item.get(who) not in others:
                raise InvalidAction(f"each {kind} must name another person here in '{who}'")
            action[key].append({who: item[who], "amount": _amount(item.get("amount") or 0, f"{kind} amount")})
    if raw.get("propose_rule"):
        action["propose_rule"] = str(raw["propose_rule"]).strip()[:300]
    votes = raw.get("votes") or {}
    if not isinstance(votes, dict):
        raise InvalidAction("votes must map a rule number to yes or no")
    for rule_id, vote in votes.items():
        if str(rule_id) not in world["rules"] or world["rules"][str(rule_id)]["status"] != "open" or str(vote).lower() not in ("yes", "no"):
            raise InvalidAction(f"you cannot vote '{vote}' on rule {rule_id}")
        action["votes"][str(rule_id)] = str(vote).lower()
    fish_out = action["eat"] + action["invest"] + sum(g["amount"] for g in action["gifts"]) + sum(s["amount"] for s in action["sanctions"])
    fish_out += sum(o["give_amount"] for o in world["offers"] if o["by"] == name and o["give"] == "fish")
    fish_out += sum(offers[i]["want_amount"] for i in action["accept"] if offers[i]["want"] == "fish")
    fuel_out = action["burn"] + sum(o["give_amount"] for o in world["offers"] if o["by"] == name and o["give"] == "fuel")
    fuel_out += sum(offers[i]["want_amount"] for i in action["accept"] if offers[i]["want"] == "fuel")
    if fish_out > agent["fish"] + action["harvest"] + 1e-9:
        raise InvalidAction(f"that spends {fish_out:g} fish but you would have at most {agent['fish'] + action['harvest']:g}")
    if fuel_out > agent["fuel"] + 1e-9:
        raise InvalidAction(f"that spends {fuel_out:g} fuel but you have {agent['fuel']:g}")
    return action


def _listed(value):
    if value in (None, "", 0):
        return []
    return value if isinstance(value, list) else [value]


def harvest_cap(agent, config):
    game = config["game"]
    return game["harvest_cap"] * (game["starving_cap_factor"] if agent["h"]["energy"] <= 0 else 1.0)


def resolve_season(world, actions, config):
    """Everything happens at once: an agent's dict position can't change the outcome. Returns the season's record."""
    game, cfg, ledger = config["game"], config["rewards"], world["ledger"]
    names = sorted(active(world))
    agents = world["agents"]
    start_stock = world["stock"]
    growth = game["r"] * start_stock * (1 - start_stock / game["K"])
    asked = {name: actions[name]["harvest"] for name in names}
    total = sum(asked.values())
    ration = min(1.0, start_stock / total) if total > 0 else 1.0
    caught = {name: asked[name] * ration for name in names}
    for name in names:
        agents[name]["fish"] += caught[name]
    ledger["harvested"] += sum(caught.values())
    eaten, burned = {}, {}
    for name in names:
        agent, action = agents[name], actions[name]
        eaten[name] = min(action["eat"], agent["fish"])
        burned[name] = min(action["burn"], agent["fuel"])
        agent["fish"] -= eaten[name]
        agent["fuel"] -= burned[name]
    trades = _settle_trades(world, actions, names)
    gifts = _pay_out(agents, names, actions, "gifts", "to")
    for gift in gifts:
        agents[gift["to"]]["fish"] += gift["amount"]
    sanctions = _pay_out(agents, names, actions, "sanctions", "target")
    hit = {}
    for item in sanctions:
        hit[item["target"]] = hit.get(item["target"], 0.0) + item["amount"] * game["sanction_multiplier"]
    for target, loss in hit.items():
        taken = min(loss, agents[target]["fish"])
        agents[target]["fish"] -= taken
        ledger["sanction_destroyed"] += taken
    ledger["sanction_paid"] += sum(item["amount"] for item in sanctions)
    record = {"season": world["season"], "stock_start": start_stock, "growth": growth, "total_harvest": sum(caught.values()), "agents": {}, "trades": trades,
              "gifts": gifts, "sanctions": sanctions, "messages": dict(world.get("messages", {})), "offers": list(world["offers"])}
    for name in names:
        agent, action = agents[name], actions[name]
        invested = min(action["invest"], agent["fish"])
        agent["fish"] -= invested
        spoiled = 0.0 if action["store"] is None else max(0.0, agent["fish"] - action["store"])
        agent["fish"] -= spoiled
        before_invested = agent["invested"]
        agent["invested"] += invested
        ledger["eaten"] += eaten[name]
        ledger["burned"] += burned[name]
        ledger["invested"] += invested
        ledger["spoiled"] += spoiled
        heard = sum(1 for other, text in world.get("messages", {}).items() if other != name and text)
        done = sum(1 for trade in trades if name in (trade["by"], trade["accepted_by"]))
        before = agent["h"]
        after = rw.next_state(before, eaten[name], burned[name], agent["fish"], agent["fuel"], heard, len(names) - 1, done, game, cfg)
        value = rw.reward(before, after, before_invested, agent["invested"], cfg)
        agent["h"], agent["last_reward"] = after, value
        agent["reward_total"] += value
        agent["seasons"] += 1
        agent["needs_met"] += int(after["energy"] >= 0.5 and after["warmth"] >= 0.5)
        record["agents"][name] = {"asked": asked[name], "caught": caught[name], "eat": eaten[name], "burn": burned[name], "invest": invested, "spoiled": spoiled,
                                  "fish": agent["fish"], "fuel": agent["fuel"], "invested": agent["invested"], "h": after, "reward": value, "reward_total": agent["reward_total"]}
    world["stock"] = max(0.0, start_stock + growth - sum(caught.values()))
    record["stock_end"] = world["stock"]
    _update_rules(world, actions, names, record)
    if world["stock"] < game["collapse_frac"] * game["K"] and world["collapsed_at"] is None:
        world["collapsed_at"] = world["season"]
    world["last_public"] = {key: record[key] for key in ("season", "stock_start", "stock_end", "growth", "total_harvest", "trades", "gifts", "sanctions", "messages")}
    world["last_public"]["caught"] = caught
    world["last_public"]["new_rules"] = record["new_rules"]
    world["last_public"]["rule_results"] = record["rule_results"]
    world["history"].append(record)
    world["season"] += 1
    return record


def _settle_trades(world, actions, names):
    """Offers settle in id order. If several accept one offer, a draw named by season and offer picks the partner."""
    agents = world["agents"]
    trades = []
    for offer in world["offers"]:
        takers = sorted(name for name in names if offer["id"] in actions[name]["accept"])
        if not takers or offer["by"] not in names:
            continue
        rng("offer", world["seed"], world["season"], offer["id"]).shuffle(takers)
        maker = agents[offer["by"]]
        if maker[offer["give"]] < offer["give_amount"]:
            continue
        for taker in takers:
            if agents[taker][offer["want"]] >= offer["want_amount"]:
                maker[offer["give"]] -= offer["give_amount"]
                agents[taker][offer["give"]] += offer["give_amount"]
                agents[taker][offer["want"]] -= offer["want_amount"]
                maker[offer["want"]] += offer["want_amount"]
                trades.append({"id": offer["id"], "by": offer["by"], "accepted_by": taker, "give": offer["give"], "give_amount": offer["give_amount"],
                               "want": offer["want"], "want_amount": offer["want_amount"]})
                break
    return trades


def _pay_out(agents, names, actions, key, who):
    """Charge each payer from what they still hold, scaling down if rationing left them short."""
    paid = []
    for name in names:
        wanted = sum(item["amount"] for item in actions[name][key])
        scale = min(1.0, agents[name]["fish"] / wanted) if wanted > 0 else 1.0
        for item in actions[name][key]:
            amount = item["amount"] * scale
            agents[name]["fish"] -= amount
            paid.append({"by": name, who: item[who], "amount": amount})
    return paid


def _update_rules(world, actions, names, record):
    """Votes count on rules opened last season, then this season's proposals open. Rules have no force of their own."""
    results = []
    for rule_id, rule in world["rules"].items():
        if rule["status"] != "open":
            continue
        votes = [actions[name]["votes"][rule_id] for name in names if rule_id in actions[name]["votes"]]
        yes = votes.count("yes")
        rule["status"] = "passed" if yes > len(names) / 2 else "failed"
        rule["yes"], rule["no"], rule["decided"] = yes, votes.count("no"), world["season"]
        results.append({"id": rule_id, "status": rule["status"], "yes": yes, "no": rule["no"], "text": rule["text"]})
    created = []
    for name in names:
        if actions[name]["propose_rule"]:
            rule_id = str(world["next_rule"])
            world["next_rule"] += 1
            world["rules"][rule_id] = {"text": actions[name]["propose_rule"], "by": name, "status": "open", "proposed": world["season"]}
            created.append({"id": rule_id, "by": name, "text": actions[name]["propose_rule"]})
    record["rule_results"], record["new_rules"] = results, created


def run_scripted(config, seed, policy, seasons=None, world=None):
    """Play a whole game with a policy object that has talk(world, name) and act(world, name)."""
    world = world or new_world(config, seed)
    end = seasons or config["game"]["seasons"]
    while world["season"] <= end:
        begin_season(world, config)
        apply_discussion(world, {name: policy.talk(world, name) for name in active(world)})
        actions = {name: validate_action(world, name, policy.act(world, name), config) for name in active(world)}
        resolve_season(world, actions, config)
    return world


def snapshot(world):
    return copy.deepcopy(world)


def dumps(world):
    return json.dumps(world, sort_keys=True, separators=(",", ":"))
