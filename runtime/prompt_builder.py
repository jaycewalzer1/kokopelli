"""Builds both prompts. Every string that reaches a model passes through the leak guard here."""
from runtime.actions import ACTION_HELP
from runtime.leak_guard import check

MAX_WM_CHARS = 1800


def compact_state(state):
    """PhysicalState as short text. Cosmos has no depth or segmentation input in this runner, so text is all it gets."""
    agent = state["agent"]
    npcs = "; ".join(f"{name} at ({npc['pos'][0]:.0f},{npc['pos'][1]:.0f})" for name, npc in state["npcs"].items())
    objects = "; ".join(f"{name} at ({item['pos'][0]:.0f},{item['pos'][1]:.0f}), {item['state']}"
                        for name, item in state["objects"].items())
    return (f"{state['time_of_day']}, {state['weather']}. Camera at ({agent['pos'][0]:.0f},{agent['pos'][1]:.0f}) "
            f"facing {agent['facing']}. People: {npcs}. Objects: {objects}.")


def life_text(context):
    """Where the agent is in its life, without what's pressing on the moment, which the agent should discover."""
    lines = [f"{node['level']}: {node['label']}. {node['setting']}" for node in context["nodes"]]
    lines += [f"Earlier, {item['label']}: {item['summary']}" for item in context["recent"]]
    return "\n".join(lines)


def build_wm_prompt(context, state, action, style, now):
    """Sources a and c of the tick. Source b, the last frames, goes in as conditioning rather than text."""
    deepest = context["nodes"][-1] if context["nodes"] else None
    events = [text for node in context["nodes"] for text in node["pressures"]][-2:]
    figures = ", ".join(f"{person['name']} ({person['relationship']})" for person in context["figures"])
    parts = [style, f"Scene: {deepest['setting']}" if deepest else "", f"Happening: {' '.join(events)}" if events else "",
             f"Key people: {figures}." if figures else "", f"Now: {compact_state(state)}",
             f"The person just chose: {action['type']} {action.get('target', action.get('text', ''))}".rstrip() + "."]
    text = " ".join(part for part in parts if part)[:MAX_WM_CHARS]
    payload = {"context": context, "text": text}
    check(payload, now, "world_model_prompt")
    return text, payload


def build_agent_prompt(context, notes, visible, frame_count, now):
    """What the agent knows: what it just saw, its own notes and its place in life. It never sees PhysicalState."""
    text = life_text(context)
    written = "\n".join(f"[{note['t']}] {note['text']}" for note in notes) or "(none yet)"
    prompt = (f"You are living this life. The time is {now}.\n\nYour life right now:\n{text}\n\n"
              f"Your notes:\n{written}\n\nThe {frame_count} images are what you just saw, in order.\n"
              f"You can see: {', '.join(visible) or 'nothing nearby'}.\n\nDecide what to do for the next 30 seconds.\n"
              f"{ACTION_HELP}")
    payload = {"life": text, "notes": notes, "prompt": prompt}
    check(payload, now, "agent_prompt")
    return prompt, payload
