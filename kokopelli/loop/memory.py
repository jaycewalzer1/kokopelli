"""Samples how much RAM the whole machine is using, so a run reports what it really needed.

It watches the system rather than this process because Cosmos runs as a subprocess and MLX keeps models in memory that
per-process numbers miss. Anything else running on the machine is counted too, so the baseline is logged alongside.
"""
import re
import subprocess
import sys
import threading
from pathlib import Path

GB = 1024 ** 3
INTERVAL = 1.0


def used_gb():
    """RAM that can't be handed to something else right now, or None if this platform isn't covered."""
    if sys.platform == "darwin":
        text = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
        page = int(re.search(r"page size of (\d+)", text).group(1))
        pages = sum(int(re.search(rf"{name}:\s+(\d+)", text).group(1))
                    for name in ("Pages active", "Pages wired down", "Pages occupied by compressor"))
        return pages * page / GB
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values = {line.split(":")[0]: int(line.split()[1]) for line in meminfo.read_text().splitlines()}
        return (values["MemTotal"] - values["MemAvailable"]) * 1024 / GB
    return None


class MemorySampler:
    def __init__(self):
        self.baseline = used_gb()
        self.peak = self.baseline
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True)

    def start(self):
        if self.baseline is not None:
            self.thread.start()
        return self

    def _watch(self):
        while not self.stop_event.wait(INTERVAL):
            value = used_gb()
            if value is not None and value > (self.peak or 0):
                self.peak = value

    def take(self):
        """Return the peak since the last take, then start measuring again from the present."""
        peak, self.peak = self.peak, used_gb()
        return round(peak, 2) if peak is not None else None

    def close(self):
        self.stop_event.set()
