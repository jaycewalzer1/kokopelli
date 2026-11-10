"""One file holding everything needed to continue after the last finished tick."""
import json
import os
from pathlib import Path


def save(out_dir, data):
    # Write then rename: a rename is atomic, so a crash leaves the old checkpoint or the new one, never half of one.
    path = Path(out_dir) / "checkpoint.json"
    temp = path.with_suffix(".tmp")
    with temp.open("w") as file:
        json.dump(data, file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def load(out_dir):
    path = Path(out_dir) / "checkpoint.json"
    return json.loads(path.read_text()) if path.exists() else None
