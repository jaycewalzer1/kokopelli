"""The city moodboard: pictures of how the agents' city should look and feel. Claude sources them, and each one waits for review.
The person keeps or removes each one and says why in its note. board.json is the index that people and agents read.
Removed pictures stay in it with their reason, since what the city shouldn't look like is as useful as what it should."""
import base64
import hashlib
import json
import threading
import time
import uuid
from pathlib import Path

from core.settings import ROOT

FOLDER = ROOT / "city" / "moodboard"
MAX_BYTES = 20 * 1024 * 1024
# A picture is known by its first bytes, never by the name or type the sender claims.
KINDS = {b"\x89PNG\r\n\x1a\n": ".png", b"\xff\xd8\xff": ".jpg", b"GIF87a": ".gif", b"GIF89a": ".gif"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
STATUSES = ("proposed", "kept", "removed")
SECTIONS = [
    {"id": "streets", "name": "Streets and getting around", "ask": "Street widths, paths, trams, bikes, crossings, what moves and how fast."},
    {"id": "buildings", "name": "Buildings and skyline", "ask": "Heights, shapes and how buildings meet the street and the sky."},
    {"id": "green", "name": "Plants, food and water", "ask": "Where things grow, how food is made, and where water shows."},
    {"id": "energy", "name": "Energy and machines", "ask": "Solar, wind and the machines people can see and fix."},
    {"id": "materials", "name": "Materials and details", "ask": "Surfaces up close: wood, earth, glass, metal, signs and wear."},
    {"id": "light", "name": "Light and weather", "ask": "Time of day, shade, heat, rain and the colors of the air."},
    {"id": "life", "name": "People and daily life", "ask": "Markets, workshops, play, rest: what a normal day looks like."},
]
UNSORTED = "unsorted"
_lock = threading.Lock()


def _folder(folder):
    return Path(folder or FOLDER)


def _read(folder):
    path = folder / "board.json"
    if path.is_file():
        return json.loads(path.read_text())
    return {"about": __doc__, "sections": SECTIONS, "images": []}


def _write(folder, board):
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / "board.json.tmp"
    temporary.write_text(json.dumps(board, indent=2) + "\n")
    temporary.replace(folder / "board.json")


def _kind(data):
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return next((suffix for start, suffix in KINDS.items() if data.startswith(start)), None)


def _section(board, section):
    ids = {item["id"] for item in board["sections"]}
    if section not in ids | {UNSORTED}:
        raise ValueError(f"No section called {section!r}.")
    return section


def _find(board, image_id):
    for image in board["images"]:
        if image["id"] == image_id:
            return image
    raise KeyError(f"No picture {image_id!r} on the board.")


def board(folder=None):
    return _read(_folder(folder))


def add(data_base64, title="", source="", origin=None, folder=None):
    """Put one picture up for review. The same picture added twice is kept once."""
    folder = _folder(folder)
    data = base64.b64decode(data_base64, validate=True)
    if len(data) > MAX_BYTES:
        raise ValueError(f"That picture is over {MAX_BYTES // 1024 // 1024} MB.")
    suffix = _kind(data)
    if not suffix:
        raise ValueError("That file isn't a PNG, JPEG, GIF or WebP picture.")
    digest = hashlib.sha256(data).hexdigest()
    with _lock:
        current = _read(folder)
        for image in current["images"]:
            if image["sha256"] == digest:
                return {**image, "duplicate": True}
        image_id = uuid.uuid4().hex[:12]
        (folder / "images").mkdir(parents=True, exist_ok=True)
        (folder / "images" / f"{image_id}{suffix}").write_bytes(data)
        image = {"id": image_id, "file": f"images/{image_id}{suffix}", "status": "proposed", "section": UNSORTED, "note": "",
                 "title": str(title).strip(), "source": str(source).strip(), "origin": origin or {}, "sha256": digest,
                 "added_at": time.time()}
        current["images"].append(image)
        _write(folder, current)
    return image


def update(image_id, fields, folder=None):
    """Change a picture's status, section or note. Nothing else about it can change."""
    folder = _folder(folder)
    with _lock:
        current = _read(folder)
        image = _find(current, image_id)
        if "status" in fields:
            if fields["status"] not in STATUSES:
                raise ValueError(f"A picture can only be {', '.join(STATUSES)}.")
            image["status"] = fields["status"]
            image["reviewed_at"] = time.time()
        if "section" in fields:
            image["section"] = _section(current, fields["section"])
        if "note" in fields:
            image["note"] = str(fields["note"]).strip()
        _write(folder, current)
    return image


def image_file(image_id, folder=None):
    """The file for a picture, found through the index, so a request can only name a picture on the board."""
    folder = _folder(folder)
    path = folder / _find(_read(folder), image_id)["file"]
    return path, IMAGE_TYPES[path.suffix]
