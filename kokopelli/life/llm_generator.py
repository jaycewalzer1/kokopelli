"""The generator backed by the local model. A bad answer costs one node, never the whole run."""
import json
import re
import time

from kokopelli.life.generator import Generator
from kokopelli.life.memory import FAILED
from kokopelli.life.prompts import closing_prompt, kind_of, opening_prompt
from kokopelli.life.seed import rng
from kokopelli.settings import LIFE_FOCUS, LIFE_LLM


class BadAnswer(ValueError):
    """The model's text wasn't the JSON its prompt asked for."""


def _object(raw):
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise BadAnswer("no JSON object")
    try:
        return json.loads(match.group())
    except json.JSONDecodeError as error:
        raise BadAnswer(f"invalid JSON: {error}") from None


def _text(answer, key):
    value = answer.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BadAnswer(f"{key} must be non-empty text")
    return value.strip()


def _probability(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise BadAnswer(f"{name} must be a number from 0 to 1")
    return round(float(value), 3)


def parse_opening(raw):
    answer = _object(raw)
    pressures = answer.get("pressures", [])
    questions = answer.get("open_questions", [])
    if not isinstance(pressures, list) or not isinstance(questions, list):
        raise BadAnswer("pressures and open_questions must be lists")
    # Ids come from here, not the model, so a closing can never be asked about a pressure that isn't unique.
    parsed = [{"id": f"p{i}", "text": _text(pressure, "text"), "odds": _probability(pressure.get("odds"), "odds")}
              for i, pressure in enumerate(pressures[:3]) if isinstance(pressure, dict)]
    return _probability(answer.get("salience"), "salience"), {"setting": _text(answer, "setting"), "pressures": parsed,
                                                             "open_questions": [str(item) for item in questions[:2]]}


def parse_closing(raw):
    answer = _object(raw)
    return {"summary": _text(answer, "summary"), "what_happened": _text(answer, "what_happened")}


class LLMGenerator(Generator):
    uses_memory = True

    def __init__(self, seed, rng_key, complete=None, log_path=None, tag=""):
        self.seed, self.rng_key, self.log_path, self.tag = seed, rng_key, log_path, tag
        if complete is None:
            # Imported here so that everything else in kokopelli/life/ runs without loading the model.
            from kokopelli.wm.llm_model import chat as complete
        self.complete = complete

    def _ask(self, write, window, system, user, parse):
        """Try until the answer parses. Returns the parsed answer, or None once the tries run out."""
        for attempt in range(LIFE_LLM["attempts"]):
            # Named per try, so a retry gets a fresh sample, and a run resumed after a crash gets the same one.
            sample = rng(self.rng_key, window.id, write, attempt).randrange(2 ** 31)
            started = time.monotonic()
            result = self.complete(system, user, max_tokens=LIFE_LLM["max_tokens"], temperature=LIFE_LLM["temperature"], seed=sample)
            error = None
            try:
                parsed = parse(result.text)
            except BadAnswer as bad:
                parsed, error = None, str(bad)
            self._log(write, window, attempt, system, user, result, time.monotonic() - started, error)
            if parsed is not None:
                return parsed
        return None

    def _log(self, write, window, attempt, system, user, result, seconds, error):
        if not self.log_path:
            return
        print(f"{time.strftime('%H:%M:%S')} {self.tag} {write} {window.id} try {attempt + 1} {seconds:.1f}s"
              f"{' FAILED: ' + error if error else ''}", flush=True)
        with open(self.log_path, "a") as log:
            log.write(json.dumps({
                "at": time.time(), "tag": self.tag, "write": write, "node": window.id, "level": window.level, "attempt": attempt,
                "ok": error is None, "error": error, "seconds": round(seconds, 2), "system": system, "user": user, "raw": result.text,
                "prompt_tokens": result.prompt_tokens, "generation_tokens": result.generation_tokens,
                "generation_tps": result.generation_tps, "peak_memory_gb": result.peak_memory,
                "finish_reason": result.finish_reason}) + "\n")

    def write_opening(self, context):
        window = context["window"]
        anchors = [anchor["text"] for anchor in self.seed.anchors if window.start.isoformat() <= anchor["at"] < window.end.isoformat()]
        # Moments inside a day stay with whatever the day is about.
        focus = rng(self.rng_key, window.id, "focus").choice(LIFE_FOCUS) if kind_of(window.level) in ("period", "day") else ""
        system, user = opening_prompt(self.seed, context, anchors, focus)
        answer = self._ask("opening", window, system, user, parse_opening)
        if answer is None:
            return 0.0, {"setting": f"{FAILED} {window.label}", "exogenous": anchors, "pressures": [], "open_questions": []}
        salience, opening = answer
        return 1.0 if anchors else salience, {**opening, "exogenous": anchors}

    def write_closing(self, context):
        window = context["window"]
        system, user = closing_prompt(self.seed, context)
        answer = self._ask("closing", window, system, user, parse_closing)
        return answer or {"summary": f"{FAILED} {window.label}", "what_happened": f"{FAILED} the model gave no usable answer"}
