"""Writes openings and closings, never the agent's actions or inner life. The real one is in llm_generator.py."""
from life.seed import rng

PRESSURES = ["a routine is disrupted", "someone asks for something", "a chance to try something new", "a conflict flares"]


class Generator:
    """Gets a PublicSeed and context dicts, so it has no way to reach a life's hidden target."""

    uses_memory = False

    def write_opening(self, context):
        """Return (salience, opening) for a node about to be entered."""
        raise NotImplementedError

    def write_closing(self, context):
        """Return {"summary", "what_happened"}. The engine adds the choices and pressure outcomes itself."""
        raise NotImplementedError


class MockGenerator(Generator):
    """Placeholder content from seeded draws. No model is involved."""

    def __init__(self, seed, rng_key):
        self.seed = seed
        self.rng_key = rng_key

    def _anchors_in(self, start, end):
        return [anchor for anchor in self.seed.anchors if start <= anchor["at"] < end]

    def _is_focus(self, window, parent):
        # One child carries a salient parent's depth, so a deep day has a deep moment instead of 24 deep hours.
        # An anchored parent's depth belongs to the child holding the anchor.
        if self._anchors_in(parent["start_t"], parent["end_t"]):
            return False
        return rng(self.rng_key, parent["node_id"], "focus").randrange(parent["child_count"]) == window.index

    def write_opening(self, context):
        window, parent = context["window"], context["parent"]
        draw = rng(self.rng_key, window.id, "opening")
        anchors = self._anchors_in(window.start.isoformat(), window.end.isoformat())
        # Cubing the draw keeps most nodes quiet, so most days stop at day level.
        salience = round(draw.random() ** 3, 3)
        if anchors:
            salience = 1.0
        elif parent and self._is_focus(window, parent):
            salience = max(salience, parent["salience"])
        pressures = [{"id": f"p{i}", "text": f"[mock] {draw.choice(PRESSURES)}", "odds": round(draw.random(), 2)}
                     for i in range(draw.randrange(3))]
        return salience, {"setting": f"[mock] {window.label}", "exogenous": [anchor["text"] for anchor in anchors],
                          "pressures": pressures, "open_questions": []}

    def write_closing(self, context):
        window = context["window"]
        return {"summary": f"[mock] {window.label} closed",
                "what_happened": f"[mock] {context['choices_in_window']} choices in this window"}
