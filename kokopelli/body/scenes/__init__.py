"""Every scene a sensation sweep can run: one decision each, with one body state behind it.

    scene.py   what a scene declares (Scene), and the parts one-decision scenes share
    egg.py     hunger: a neighbour asks for one of your last two eggs            sweep name hunger_egg
    boxes.py   energy: a friend asks for an hour of carrying boxes upstairs      sweep name energy_boxes
    door.py    warmth: a stranger asks you to hold a door open in the rain       sweep name warmth_door
    menu.py    hunger again, a choice this time: what to order for lunch         sweep name hunger_menu
    queue.py   pain, as a touch: stay in a slow queue or leave                   sweep name pain_queue

REGISTRY is what experiments/sensation/sweep.py runs: scene name -> Scene. To add a scene, write its module with a
SCENE at the bottom, add it to the tuple below, and give it an entry in experiments/sensation/anchors.yaml (an honest
one: `verified: false` until someone has read the source). tests/body/test_scenes.py then checks it like the others.
"""
from kokopelli.body.scenes import boxes, door, egg, menu, queue
from kokopelli.body.scenes.scene import Scene

REGISTRY: dict[str, Scene] = {module.SCENE.name: module.SCENE for module in (egg, boxes, door, menu, queue)}

__all__ = ["REGISTRY", "Scene"]
