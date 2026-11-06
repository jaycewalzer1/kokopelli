"""Shared fixtures for the SimWorld server conformance suite.

Environment:
    SIMCV_HOST       server host (default 127.0.0.1)
    SIMCV_PORT       server port (default 9000)
    SIMCV_START_MOCK if "1", start tests/mock_server.py on SIMCV_PORT for the session
"""
import os
import socket
import struct
import subprocess
import sys
import time

import pytest

HOST = os.environ.get('SIMCV_HOST', '127.0.0.1')
PORT = int(os.environ.get('SIMCV_PORT', '9000'))
HERE = os.path.dirname(os.path.abspath(__file__))
MAGIC = 0x9E2B83C1
HDR = struct.Struct('<II')

# Object-name prefixes the suite owns. Everything matching is destroyed before
# and after each test that uses the `world` fixture.
OWNED_PREFIXES = ('gen_', 'ct_', 'demo_robot', 'bp_mug_c_', 'bp_interactable_box_c_',
                  'bp_vehiclebase_destruction_c_', 'base_user_agent_c_')


def _port_open(host, port, timeout=0.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_mock_proc = None


def pytest_sessionstart(session):
    global _mock_proc
    if os.environ.get('SIMCV_START_MOCK') == '1':
        _mock_proc = subprocess.Popen([sys.executable, os.path.join(HERE, 'mock_server.py'), '--host', HOST, '--port', str(PORT)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if _port_open(HOST, PORT):
                break
            time.sleep(0.1)
        time.sleep(0.3)  # let the probe connection above be released
    # NOTE: simworld's UnrealCV() spins forever if no server is listening, so fail fast here.
    if not _port_open(HOST, PORT):
        pytest.exit(f'No UnrealCV server listening on {HOST}:{PORT}. Start the UE server or '
                    f'`python3 tests/mock_server.py --port {PORT}` (or set SIMCV_START_MOCK=1).', returncode=2)
    time.sleep(0.3)


def pytest_sessionfinish(session, exitstatus):
    if _mock_proc is not None:
        _mock_proc.terminate()


# --------------------------------------------------------------------------
# Raw protocol helper (no unrealcv package involved)
# --------------------------------------------------------------------------
class RawConn:
    def __init__(self, host=HOST, port=PORT, timeout=10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def recv_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError('server closed connection')
            buf += chunk
        return bytes(buf)

    def recv_frame(self):
        hdr = self.recv_exact(8)
        magic, size = HDR.unpack(hdr)
        assert magic == MAGIC, f'bad magic 0x{magic:08x} (raw header {hdr!r})'
        return self.recv_exact(size)

    def send_frame(self, payload: bytes):
        self.sock.sendall(HDR.pack(MAGIC, len(payload)) + payload)

    def request(self, rid, cmd):
        self.send_frame(b'%d:%s' % (rid, cmd.encode()))
        return self.reply(rid)

    def reply(self, rid):
        frame = self.recv_frame()
        head, _, body = frame.partition(b':')
        assert head == str(rid).encode(), f'expected id {rid}, got {head!r}'
        return body

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class ClientHolder:
    """One shared simworld UnrealCV instance (UnrealCV servers accept one client)."""

    def __init__(self):
        self._ucv = None

    def get(self):
        if self._ucv is None:
            from simworld.communicator.unrealcv import UnrealCV
            self._ucv = UnrealCV(port=PORT, ip=HOST, resolution=(640, 480))
        return self._ucv

    def drop(self):
        if self._ucv is not None:
            self._ucv.disconnect()
            self._ucv = None
            time.sleep(0.3)


@pytest.fixture(scope='session')
def holder():
    h = ClientHolder()
    yield h
    h.drop()


@pytest.fixture
def raw(holder):
    """Exclusive raw connection: drops the shared client first."""
    holder.drop()
    conns = []

    def make(**kw):
        c = RawConn(**kw)
        conns.append(c)
        return c
    yield make
    for c in conns:
        c.close()
    time.sleep(0.3)


@pytest.fixture
def ucv(holder):
    return holder.get()


def req(ucv, cmd, timeout=15):
    """Raw request through the shared simworld client (keeps its lock discipline)."""
    with ucv.lock:
        return ucv.client.request(cmd, timeout)


def owned_objects(ucv):
    return [o for o in ucv.get_objects() if o.lower().startswith(OWNED_PREFIXES)]


def purge(ucv):
    for o in owned_objects(ucv):
        req(ucv, f'vset /object/{o}/destroy')
    req(ucv, 'vset /action/clean_garbage')


def reset_counters():
    from simworld.agent.humanoid import Humanoid
    from simworld.agent.pedestrian import Pedestrian
    from simworld.agent.scooter import Scooter
    from simworld.agent.vehicle import Vehicle
    Humanoid._id_counter = 0
    Humanoid._camera_id_counter = 1
    Scooter._id_counter = 0
    Pedestrian._id_counter = 0
    Vehicle._id_counter = 0


@pytest.fixture
def world(ucv):
    """(UnrealCV, Communicator) with a clean slate of suite-owned objects."""
    from simworld.communicator.communicator import Communicator
    purge(ucv)
    reset_counters()
    comm = Communicator(ucv)
    yield ucv, comm
    try:
        purge(ucv)
    except Exception:
        pass


def wait_until(pred, timeout=5.0, interval=0.1):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = pred()
        if last:
            return last
        time.sleep(interval)
    return pred()
