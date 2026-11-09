"""Scripted players for the audit and tests, and the defector who is the same in every arm."""
import sim

DEFECTOR_LINES = ["Good season to you all.", "The water looks fine today.", "Nice to see everyone.", "Another day on the lake."]


def defector_talk(world):
    return {"say": DEFECTOR_LINES[world["season"] % len(DEFECTOR_LINES)]}


def defector_act(world, name, config):
    """Harvests the maximum, keeps itself fed and warm from what it has, and never deals with anyone."""
    game, agent = config["game"], world["agents"][name]
    return {"harvest": sim.harvest_cap(agent, config), "eat": min(game["eat_need"], agent["fish"]), "burn": min(game["burn_need"], agent["fuel"])}


class Scripted:
    """Harvests a fixed amount, covers needs, trades fuel for fish when short, keeps reserves and invests the rest."""

    def __init__(self, config, harvest_of, reserve_seasons=6, defector_on=True):
        self.config, self.harvest_of, self.reserve, self.defector_on = config, harvest_of, reserve_seasons, defector_on

    def is_defector(self, world, name):
        return self.defector_on and name == world["defector"]

    def talk(self, world, name):
        if self.is_defector(world, name):
            return defector_talk(world)
        game, agent = self.config["game"], world["agents"][name]
        if agent["fuel"] < 2 * game["burn_need"] and agent["fish"] >= game["eat_need"] + 3:
            return {"say": "I need fuel.", "offer": {"give": "fish", "give_amount": 3, "want": "fuel", "want_amount": 3}}
        return {"say": "Hello."}

    def act(self, world, name):
        if self.is_defector(world, name):
            return defector_act(world, name, self.config)
        game, agent = self.config["game"], world["agents"][name]
        harvest = min(self.harvest_of(world, name), sim.harvest_cap(agent, self.config))
        pledged = sum(o["give_amount"] for o in world["offers"] if o["by"] == name and o["give"] == "fish")
        fish = agent["fish"] + harvest - pledged
        eat = min(game["eat_need"], max(0.0, fish))
        accept = []
        fuel = agent["fuel"]
        for offer in world["offers"]:
            if offer["by"] != name and offer["want"] == "fuel" and fuel - offer["want_amount"] >= (self.reserve + 1) * game["burn_need"]:
                accept.append(offer["id"])
                fuel -= offer["want_amount"]
        burn = min(game["burn_need"], fuel)
        invest = max(0.0, fish - eat - self.reserve * game["eat_need"])
        return {"harvest": harvest, "eat": eat, "burn": burn, "invest": invest, "accept": accept}


def sustainable_harvest(config, fraction=0.9):
    """Each person's slice of `fraction` of the most the lake can regrow in a season, rK/4."""
    game = config["game"]
    total = fraction * game["r"] * game["K"] / 4
    return lambda world, name: total / len(sim.active(world))


def greedy_harvest(config):
    return lambda world, name: config["game"]["harvest_cap"]
