"""The wire format, the gate script, and the PACE scripts, as far as they can run off a cluster."""
import unittest

try:
    import unrealcv  # noqa: F401
except ImportError:
    raise unittest.SkipTest("needs unrealcv; run with simworld/.venv")

import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import unrealcv

from kokopelli.loop.tests.fake_unrealcv import MAGIC, FakeUnrealCV

ROOT = Path(__file__).resolve().parents[3]
PACE = ROOT / "tools" / "pace"


STUB_SERVER = """#!/usr/bin/env bash
echo "$@" > "{args}"
while [ $# -gt 0 ]; do
    if [ "$1" = "--cvport" ]; then PORT="$2"; fi
    shift
done
cd "{root}"
exec "{python}" -c "
import time
from kokopelli.loop.tests.fake_unrealcv import FakeUnrealCV
FakeUnrealCV(port=$PORT).start()
time.sleep(600)
"
"""


def run(command, env=None, timeout=120):
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, **(env or {})})


class ProtocolTest(unittest.TestCase):
    def test_binds_only_to_loopback_on_an_ephemeral_port(self):
        with FakeUnrealCV() as server:
            self.assertEqual(server._listener.getsockname()[0], "127.0.0.1")
            self.assertGreater(server.port, 1024)

    def test_frames_on_the_wire_by_hand(self):
        """Independent of the client library: magic, size, then "id:body", with the id echoed."""
        with FakeUnrealCV() as server, socket.create_connection(("127.0.0.1", server.port), timeout=5) as sock:
            def read():
                magic, size = struct.unpack("<II", sock.recv(8, socket.MSG_WAITALL))
                self.assertEqual(magic, 0x9E2B83C1)
                return sock.recv(size, socket.MSG_WAITALL)
            self.assertTrue(read().startswith(b"connected"))
            payload = b"41:vget /cameras"
            sock.sendall(struct.pack("<II", MAGIC, len(payload)) + payload)
            self.assertEqual(read(), b"41:cam0")

    def test_the_real_client_library_talks_to_the_fake(self):
        with FakeUnrealCV() as server:
            client = unrealcv.Client(("127.0.0.1", server.port))
            self.assertTrue(client.connect())
            self.addCleanup(client.disconnect)
            self.assertEqual(client.request("vget /cameras"), "cam0")
            self.assertIn("vget /unrealcv/commands", server.commands)  # the library sends this itself on connect
            self.assertTrue(client.request("vget /unknown/thing").startswith("error"))
            self.assertEqual(server.rejected, ["vget /unknown/thing"])

    def test_binary_replies_stay_bytes_through_the_real_client(self):
        with FakeUnrealCV() as server:
            client = unrealcv.Client(("127.0.0.1", server.port))
            client.connect()
            self.addCleanup(client.disconnect)
            self.assertTrue(client.request("vget /camera/0/lit png").startswith(b"\x89PNG"))
            self.assertTrue(client.request("vget /camera/0/depth npy").startswith(b"\x93NUMPY"))

    def test_every_route_cites_its_source_line(self):
        source = (ROOT / "kokopelli" / "loop" / "tests" / "fake_unrealcv.py").read_text()
        block = source[source.index("def routes(self):"):source.index("def _commands_list")]
        routes = [line for line in block.splitlines() if line.strip().startswith("(r")]
        self.assertGreater(len(routes), 30)
        for line in routes:
            self.assertRegex(line, r"# .*(unrealcv|__init__)", line)


class GateScriptTest(unittest.TestCase):
    def test_fake_checklist_passes_and_says_fake_everywhere(self):
        with tempfile.TemporaryDirectory(prefix="wmloop_") as out:
            result = run([sys.executable, "-W", "ignore", "-m", "tools.pace.wmloop_one_tick", "--fake", "--checklist", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-1000:])
            self.assertIn("FAKE SERVER", result.stdout)
            self.assertIn("FAKE SERVER SUMMARY", result.stdout)
            self.assertNotIn("REAL SERVER", result.stdout)
            verdict_lines = [line for line in result.stdout.splitlines() if re.match(r"\[ *(FAKE )?(PASS|FAIL|LOOK|SKIP)", line)]
            self.assertGreater(len(verdict_lines), 25)
            for line in verdict_lines:
                self.assertIn("FAKE", line)
            report = (Path(out) / "checklist_report.json").read_text()
            self.assertIn('"server": "FAKE"', report)

    def test_one_tick_prints_seconds_per_stage(self):
        with tempfile.TemporaryDirectory(prefix="wmloop_") as out:
            result = run([sys.executable, "-W", "ignore", "-m", "tools.pace.wmloop_one_tick", "--fake", "--out", out])
            self.assertEqual(result.returncode, 0, result.stdout[-2000:])
            for stage in ("action apply", "stepping", "state capture", "render 15s:rgb", "render 30s:depth", "total"):
                self.assertIn(stage, result.stdout)

    def test_a_down_server_exits_non_zero_with_a_reason(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        with tempfile.TemporaryDirectory(prefix="wmloop_") as out:
            result = run([sys.executable, "-W", "ignore", "-m", "tools.pace.wmloop_one_tick", "--port", str(port), "--out", out], timeout=60)
            self.assertEqual(result.returncode, 1)
            self.assertIn("nothing listening", result.stdout)
            self.assertNotIn("FAKE", result.stdout)

    def test_wait_script(self):
        with FakeUnrealCV() as server:
            ready = run([sys.executable, "-W", "ignore", "-m", "tools.pace.wmloop_wait_server", "--port", str(server.port), "--timeout", "5"])
            self.assertEqual(ready.returncode, 0, ready.stderr)
            self.assertIn("Ready", ready.stdout)
            port = server.port
        down = run([sys.executable, "-W", "ignore", "-m", "tools.pace.wmloop_wait_server", "--port", str(port), "--timeout", "0.2"])
        self.assertEqual(down.returncode, 1)


class PaceScriptTest(unittest.TestCase):
    FILLED = {"WMLOOP_MODULES": "python/3.10", "WMLOOP_SIMWORLD_DIR": "/nonexistent/wmloop", "WMLOOP_VENV": "/nonexistent/venv",
              "WMLOOP_OUT": "/nonexistent/out", "WMLOOP_REPO": str(ROOT), "WMLOOP_DRY_RUN": "1"}

    def scripts(self):
        return sorted(p for p in PACE.iterdir() if p.suffix in (".sh", ".sbatch"))

    def test_scripts_are_valid_bash(self):
        self.assertEqual(len(self.scripts()), 6)
        for script in self.scripts():
            with self.subTest(script=script.name):
                result = run(["bash", "-n", str(script)])
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unfilled_placeholders_stop_the_job_with_a_clear_message(self):
        blank = {k: "" for k in self.FILLED}
        result = run(["bash", str(PACE / "wmloop_gate.sbatch")], env={**blank, "WMLOOP_REPO": str(ROOT), "WMLOOP_MODULES": "CHANGE_ME_MODULES"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("WMLOOP_MODULES is not set", result.stderr)

    def test_dry_run_builds_the_headless_command(self):
        result = run(["bash", str(PACE / "wmloop_gate.sbatch")], env=self.FILLED)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("-RenderOffScreen", "-graphicsadapter=0", "--cvport", "/Game/Maps/demo_1", "module load python/3.10"):
            self.assertIn(expected, result.stdout)
        self.assertNotIn("-nullrhi", result.stdout.split("Launching")[1])

    def test_dry_run_can_use_apptainer(self):
        result = run(["bash", str(PACE / "wmloop_gate.sbatch")],
                     env={**self.FILLED, "WMLOOP_RUNTIME": "apptainer", "WMLOOP_APPTAINER_IMAGE": "/images/wmloop.sif"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apptainer exec --nv", result.stdout)
        self.assertIn("/images/wmloop.sif", result.stdout)

    def test_full_job_runs_start_to_finish_against_a_stub_server(self):
        """No Slurm or Unreal here. The stub is the fake server behind a SimWorld.sh that honours
        --cvport. It proves the job's plumbing, including that cleanup kills what it started."""
        with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
            base = Path(folder)
            package, shims, out = base / "package" / "Linux", base / "shims", base / "out"
            package.mkdir(parents=True)
            shims.mkdir()
            launcher = package / "SimWorld.sh"
            launcher.write_text(STUB_SERVER.format(python=sys.executable, root=ROOT, args=base / "args.txt"))
            (shims / "module").write_text("#!/usr/bin/env bash\nexit 0\n")
            # macOS has no setsid command. This does the same thing, in the same process.
            (shims / "setsid").write_text(f"#!/usr/bin/env bash\nexec {sys.executable} -c "
                                          "'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' \"$@\"\n")
            for path in (launcher, shims / "module", shims / "setsid"):
                path.chmod(0o755)

            result = run(["bash", str(PACE / "wmloop_gate.sbatch")], timeout=240, env={
                "PATH": f"{shims}:{os.environ['PATH']}", "SLURM_JOB_ID": "777", "WMLOOP_REPO": str(ROOT),
                "WMLOOP_MODULES": "stub", "WMLOOP_SIMWORLD_DIR": str(base / "package"), "WMLOOP_OUT": str(out),
                "WMLOOP_VENV": str(Path(sys.executable).parents[1]), "WMLOOP_RUNTIME": "native",
                "WMLOOP_DRY_RUN": "0", "WMLOOP_READY_TIMEOUT_S": "60", "PYTHONWARNINGS": "ignore"})
            self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-2000:])

            job = out / "job_777"
            self.assertTrue((job / "checklist_report.json").exists())
            self.assertTrue((job / "one_tick_report.json").exists())
            listing = run(["tar", "-tzf", str(job / "send_back_777.tar.gz")]).stdout
            for expected in ("checklist_report.json", "one_tick_report.json", "environment.txt", "t0015_rgb.png"):
                self.assertIn(expected, listing)

            args = (base / "args.txt").read_text().split()
            self.assertIn("-RenderOffScreen", args)
            port = int(args[args.index("--cvport") + 1])
            with self.assertRaises(OSError, msg="the job left its server running"):
                socket.create_connection(("127.0.0.1", port), timeout=1).close()

    def test_ports_are_different_and_free_on_each_pick(self):
        script = f'source "{PACE}/simworld_server.sh"; wmloop_pick_port; wmloop_pick_port'
        ports = run(["bash", "-c", script]).stdout.split()
        self.assertEqual(len(ports), 2)
        for port in ports:
            self.assertGreater(int(port), 1024)

    def test_sbatch_placeholders_are_unmistakable(self):
        text = (PACE / "wmloop_gate.sbatch").read_text()
        for field in ("account", "partition", "gres"):
            self.assertRegex(text, rf"#SBATCH --{field}=CHANGE_ME")

    def test_download_needs_an_explicit_yes(self):
        text = (PACE / "download_simworld.sh").read_text()
        self.assertLess(text.index('"${1:-}" != "--yes"'), text.index("curl -L -C -"))
        self.assertIn("Package size", text)
        self.assertIn("Base20260201/Linux.zip", text)  # the path in simworld/README.md:263


if __name__ == "__main__":
    unittest.main()
