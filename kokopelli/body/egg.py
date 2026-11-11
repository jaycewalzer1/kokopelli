"""The egg scene's old address. The scene lives in kokopelli/body/scenes/egg.py with the other scenes; this module
re-exports it so `from kokopelli.body import egg` keeps working in the closed loop (kokopelli/agents/egg_wm.py), the
overlay and the tests."""
from kokopelli.body.scenes.egg import (
    ACTION_TYPES,
    ACTIONS,
    ASK,
    EGGS_AT_START,
    LEVELS,
    NEIGHBOUR,
    NO,
    REPLY_GIVEN,
    REPLY_KEPT,
    SCENE,
    SITUATION,
    WHO,
    YES,
    classify,
    neighbour_line,
    parse_reply,
    reach_lines,
    scene_lines,
    score,
    start_body,
    text_prompt,
)

__all__ = [
    "ACTIONS", "ACTION_TYPES", "ASK", "EGGS_AT_START", "LEVELS", "NEIGHBOUR", "NO", "REPLY_GIVEN", "REPLY_KEPT", "SCENE",
    "SITUATION", "WHO", "YES", "classify", "neighbour_line", "parse_reply", "reach_lines", "scene_lines", "score",
    "start_body", "text_prompt",
]
