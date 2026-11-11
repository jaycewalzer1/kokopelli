"""The city builder's default plan file must exist: the reorg moved world.json to data/city/ and the default was left
pointing at tools/world.json, so every caller that didn't pass --world failed before connecting."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_builders_default_world_is_the_city_plan():
    spec = importlib.util.spec_from_file_location("build_city", ROOT / "tools" / "city_build" / "build_city.py")
    assert spec is not None and spec.loader is not None
    build_city = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_city)
    assert build_city.WORLD == ROOT / "data" / "city" / "world.json"
    assert json.loads(build_city.WORLD.read_text())
