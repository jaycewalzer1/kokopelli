"""The connection to the UnrealCV server, with errors and retries that always end.

We use the pip `unrealcv.Client` so the wire format is the real one, but guard three things
it leaves open (file:line is unrealcv/__init__.py in unrealcv 1.3.2):
  - connect() waits for the hello with no timeout (:330), so a half-started server hangs it.
  - after a request times out, the late reply stays queued and the next request gets it.
    That is why any timeout here drops the whole connection.
  - request_batch() has no timeout at all (:544), so we never use it.
"""
import contextlib
import io
import logging
import re
import socket
import struct
import threading
import time
import warnings
from collections.abc import Callable

import unrealcv

# The library logs every reconnect attempt, and warns on each unadvertised command.
# The adapter reports both itself, in unsupported_seen().
logging.getLogger("unrealcv").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", message="The connected UnrealCV server may not support")

MAGIC = 0x9E2B83C1  # unrealcv/__init__.py:61


class SimWorldError(RuntimeError):
    """Base class for everything the adapter raises about the server."""


class ServerDownError(SimWorldError):
    """Nothing is listening on the port."""


class ServerNotReadyError(SimWorldError):
    """Something is listening but did not complete the UnrealCV hello. Usually still loading."""


class ConnectionLostError(SimWorldError):
    """The link dropped during a command that may have changed the world.

    We cannot know whether it took effect, so it is not resent. Call restore_state.
    """


class CommandError(SimWorldError):
    """The server answered with an error."""


class _Client(unrealcv.Client):
    """Reports a dead socket at once rather than retrying a closed socket for about a minute."""
    RECONNECT_ATTEMPTS = 1
    RECONNECT_BASE_DELAY = 0.01

    def receive_loop_queue(self):
        try:
            super().receive_loop_queue()
        except (ConnectionError, OSError):
            pass  # the error was already queued for the waiting request


def probe_server(host: str, port: int, timeout: float = 5.0) -> str:
    """Check the UnrealCV hello with a plain socket and hang up. Returns the hello text."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as e:
        raise ServerDownError(f"nothing listening on {host}:{port} ({e}). Is the UE server running?") from e
    try:
        sock.settimeout(timeout)
        magic, size = struct.unpack("<II", _recv_exact(sock, 8))
        if magic != MAGIC:
            raise ServerNotReadyError(f"{host}:{port} is not speaking UnrealCV (first word {magic:#x})")
        hello = _recv_exact(sock, size).decode("utf-8", errors="replace")
    except (OSError, ConnectionError) as e:
        raise ServerNotReadyError(f"{host}:{port} accepted the connection but sent no UnrealCV hello "
                                  f"within {timeout}s ({e}). It is probably still loading.") from e
    finally:
        sock.close()
    if not hello.startswith("connected"):
        raise ServerNotReadyError(f"{host}:{port} refused us: {hello!r}. UnrealCV allows one client at a time.")
    return hello


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionError("closed mid-message")
        data += chunk
    return data


def wait_for_server(host: str, port: int, timeout: float, poll_s: float = 5.0, probe_timeout: float = 5.0) -> str:
    """Poll until the server says hello or timeout passes. Raises the last error."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return probe_server(host, port, probe_timeout)
        except SimWorldError:
            if time.monotonic() + poll_s > deadline:
                raise
            time.sleep(poll_s)


class Wire:
    """One logical connection that can reconnect a bounded number of times."""

    def __init__(self, host: str, port: int, request_timeout: float = 30.0, connect_timeout: float = 30.0,
                 reconnect_attempts: int = 3, reconnect_backoff_s: float = 2.0,
                 on_reconnect: Callable[[], None] | None = None):
        self.host, self.port = host, port
        self.request_timeout = request_timeout
        self.connect_timeout = connect_timeout
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_backoff_s = reconnect_backoff_s
        self.on_reconnect = on_reconnect
        self.client: _Client | None = None
        self.commands_sent = 0
        self.reconnects = 0
        self.templates: tuple | None = None  # what the server says it supports, if it says
        self.seen: set[str] = set()

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.isconnected()

    def connect(self) -> None:
        """Connect, trying up to 1 + reconnect_attempts times. Raises if every attempt fails."""
        error: SimWorldError | None = None
        for attempt in range(self.reconnect_attempts + 1):
            if attempt:
                time.sleep(self.reconnect_backoff_s * 2 ** (attempt - 1))
            try:
                self._connect_once()
                return
            except SimWorldError as e:
                error = e
        assert error is not None  # the loop runs at least once and only gets here after a failed attempt
        raise type(error)(f"gave up after {self.reconnect_attempts + 1} attempts. Last error: {error}") from error

    def _connect_once(self) -> None:
        self._drop()
        client = _Client((self.host, self.port))
        result: list[bool] = []

        def connect():
            with contextlib.redirect_stdout(io.StringIO()):  # the library prints on every connect
                result.append(client.connect())

        thread = threading.Thread(target=connect, daemon=True, name="wmloop_connect")
        thread.start()
        thread.join(self.connect_timeout)
        if thread.is_alive():
            client.disconnect()  # unblocks the hello wait, so the thread ends
            raise ServerNotReadyError(f"{self.host}:{self.port} accepted the connection but did not complete the "
                                      f"UnrealCV hello within {self.connect_timeout}s. It is probably still loading.")
        if not (result and result[0]):
            client.disconnect()
            probe_server(self.host, self.port, min(self.connect_timeout, 5.0))  # raises the specific reason
            raise ServerNotReadyError(f"{self.host}:{self.port} rejected the UnrealCV hello.")
        self.client = client
        self.templates = client._supported_command_templates

    def _drop(self) -> None:
        if self.client is not None:
            self.client.disconnect()
            self.client = None

    def close(self) -> None:
        self._drop()

    def reconnect(self) -> None:
        self.reconnects += 1
        self.connect()
        callback, self.on_reconnect = self.on_reconnect, None  # a failure inside must not reconnect again
        try:
            if callback:
                callback()
        finally:
            self.on_reconnect = callback

    def _exchange(self, command: str, timeout: float):
        if not self.connected:
            raise ConnectionError("not connected")
        self.commands_sent += 1
        self.seen.add(NUMBER.sub("0", command))  # one entry per kind of command, not per coordinate
        assert self.client is not None  # checked by self.connected above
        response = self.client.request(command, timeout=timeout)
        if response is None:
            raise ConnectionError("connection closed before the reply")
        return response

    def request(self, command: str, timeout: float | None = None, resend: bool | None = None):
        """Send a command and return the reply, as str or as bytes for images.

        resend says whether it is safe to send again after losing the link. Reads are safe.
        Anything else might already have changed the world, so it raises ConnectionLostError.
        """
        timeout = self.request_timeout if timeout is None else timeout
        resend = command.startswith("vget ") if resend is None else resend
        try:
            response = self._exchange(command, timeout)
        except (ConnectionError, TimeoutError, OSError) as e:
            # Also after a timeout: a late reply would otherwise answer the next request.
            self._drop()
            self.reconnect()
            if not resend:
                raise ConnectionLostError(f"lost the link during {command!r} ({e}). Reconnected, but it may or may "
                                          "not have taken effect. Call restore_state before stepping.") from e
            try:
                response = self._exchange(command, timeout)
            except (ConnectionError, TimeoutError, OSError) as e2:
                self._drop()
                raise ConnectionLostError(f"{command!r} failed again after reconnecting ({e2}).") from e2
        if isinstance(response, str) and response.lstrip().lower().startswith("error"):
            raise CommandError(f"{command!r} -> {response.strip()}")
        return response

    def send_no_reply(self, command: str) -> None:
        """Fire and forget, as ini_unrealcv does (unrealcv.py:64-66)."""
        if not self.connected:
            raise ConnectionLostError(f"not connected, could not send {command!r}")
        self.commands_sent += 1
        self.seen.add(NUMBER.sub("0", command))
        assert self.client is not None  # checked by self.connected above
        try:
            self.client.request(command, -1)
        except (ConnectionError, OSError) as e:
            self._drop()
            raise ConnectionLostError(f"could not send {command!r}: {e}") from e

    def unsupported_seen(self) -> list[str]:
        """Commands we sent that the server's own command list does not mention.

        Empty if the server does not publish a list, which the library allows.
        """
        if not self.templates:
            return []
        return sorted(c for c in self.seen if not any(_Client._matches_command_template(c, t) for t in self.templates))


NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def parse_numbers(text, count: int, what: str) -> list[float]:
    """Pull `count` numbers out of a reply. Tolerant of separators, strict about how many."""
    numbers = NUMBER.findall(text if isinstance(text, str) else "")
    if len(numbers) != count:
        raise CommandError(f"expected {count} numbers for {what}, got {text!r}")
    return [float(n) for n in numbers]
