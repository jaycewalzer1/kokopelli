"""The loop: one cursor moving through simulated time, one write per step."""
import time
from datetime import datetime

from life.agent import RandomAgent
from life.generator import MockGenerator
from life.memory import consolidate, recall
from life.resolver import Resolver
from life.windows import age_at, children, depth, depth_limit_for, find, life_window, stage_at
from settings import LIFE_BUDGET


class BudgetExceeded(Exception):
    pass


class Budget:
    """Hard limits on generator writes and wall-clock time. Each write will be one LLM call once those exist."""

    def __init__(self, generator_calls=None, seconds=None):
        self.generator_calls = LIFE_BUDGET["generator_calls"] if generator_calls is None else generator_calls
        self.seconds = LIFE_BUDGET["seconds"] if seconds is None else seconds
        self.used = 0
        self.started = time.monotonic()

    def spend(self):
        if self.used >= self.generator_calls:
            raise BudgetExceeded(f"used all {self.generator_calls} generator calls")
        if time.monotonic() - self.started >= self.seconds:
            raise BudgetExceeded(f"used all {self.seconds} seconds")
        self.used += 1

    def remaining(self):
        return {"generator_calls": self.generator_calls - self.used,
                "seconds": round(max(0, self.seconds - (time.monotonic() - self.started)), 1)}


class Engine:
    def __init__(self, store, run_id, mode="mock", budget=None, generator=None, agent=None, resolver=None, deepest=None):
        if mode != "mock":
            raise NotImplementedError("real LLM mode isn't built yet")
        self.store, self.run_id = store, run_id
        self.seed = store.public_seed(run_id)
        self.birth = self.seed.birth_date
        rng_key = store.rng_key(run_id)
        self.generator = generator or MockGenerator(self.seed, rng_key)
        self.agent = agent or RandomAgent(rng_key)
        self.resolver = resolver or Resolver(rng_key)
        self.budget = budget or Budget()
        # Stop every line at this level whatever its salience, to cover more of a life with fewer writes.
        self.deepest = deepest
        self._state = store.state(run_id)
        self._state_seq = store.last_seq(run_id)

    def state(self):
        self._state = self.store.state(self.run_id, base=self._state, after_seq=self._state_seq)
        self._state_seq = self.store.last_seq(self.run_id)
        return self._state

    def _context(self, window, parent=None):
        age = age_at(self.birth, window.start)
        context = {"window": window, "age": age, "stage": stage_at(age), "state": self.state(), "parent": parent}
        if self.generator.uses_memory:
            context["memory"] = recall(self.store, self.run_id, window)
        return context

    def _limit(self, salience):
        limit = depth_limit_for(salience)
        return self.deepest if self.deepest and depth(limit) > depth(self.deepest) else limit

    def finished(self):
        life = self.store.node(self.run_id, life_window(self.birth).id)
        return life is not None and life["closing"] is not None

    def step(self):
        """Make one write. Returns what happened, or None if the life is over."""
        with self.store.atomic():
            node = self.store.cursor(self.run_id)
            if node is None:
                return None if self.finished() else self._open(life_window(self.birth), None)
            window = find(node["node_id"], self.birth)
            if depth(window.level) >= depth(self.store.effective_limit(node)):
                return self._choice_point(window, node)
            return self._next_child(window, node)

    def _next_child(self, window, node):
        kids = children(window, self.birth)
        opened = len(self.store.child_nodes(self.run_id, node["node_id"]))
        if opened == len(kids):
            return self._close(window, node, stance=None, choices=[])
        parent = {**node, "child_count": len(kids), "depth_limit": self.store.effective_limit(node)}
        return self._open(kids[opened], parent)

    def _open(self, window, parent):
        self.budget.spend()
        salience, opening = self.generator.write_opening(self._context(window, parent))
        self.store.open_node(self.run_id, window, salience, self._limit(salience), opening)
        return {"did": "open", "node_id": window.id}

    def _choice_point(self, window, node):
        if self.resolver.escalates(window):
            self.store.escalate(self.run_id, node["node_id"])
            return {"did": "escalate", "node_id": node["node_id"]}
        context = self._context(window)
        self.store.append_event(self.run_id, node["node_id"], window.start, "choice_point",
                                {"options": context["stage"]["action_space"]})
        action = self.agent.choose({**context, "opening": node["opening"]})
        self.store.append_event(self.run_id, node["node_id"], window.start, "choice", action)
        return self._close(window, node, stance=action["stance"], choices=[action])

    def _close(self, window, node, stance, choices):
        self.budget.spend()
        outcomes = self.resolver.resolve_pressures(window, node["opening"]["pressures"], stance)
        for kind, data in self.resolver.consequences(window, outcomes, self.state()):
            self.store.append_event(self.run_id, node["node_id"], window.start, kind, data)
        context = {**self._context(window), "opening": node["opening"], "outcomes": outcomes, "choices": choices,
                   "choices_in_window": self.store.count_events(self.run_id, node["start_t"], node["end_t"], "choice")}
        if self.generator.uses_memory:
            context["children"] = consolidate(self.store, self.run_id, node["node_id"])
        closing = {**self.generator.write_closing(context), "pressures": outcomes, "choices": choices}
        self.store.close_node(self.run_id, node["node_id"], closing)
        return {"did": "close", "node_id": node["node_id"]}

    def _reached(self, target):
        node = self.store.node(self.run_id, target.id)
        if node is not None and node["closing"] is not None:
            return True
        # A target finer than the depth limit never opens, so also stop once time has passed it.
        cursor = self.store.cursor(self.run_id)
        return cursor is not None and datetime.fromisoformat(cursor["start_t"]) >= target.end

    def run(self, stop=None, until=None, step_delay=0):
        """Step until something stops the run. Returns why: done, reached, stopped, or budget."""
        target = find(until, self.birth) if until else None
        while True:
            if step_delay:
                time.sleep(step_delay)
            if stop is not None and stop.is_set():
                return "stopped"
            if target is not None and self._reached(target):
                return "reached"
            try:
                if self.step() is None:
                    return "done"
            except BudgetExceeded:
                return "budget"
