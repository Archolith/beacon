"""A recreated server rebinds its port while the previous instance's sockets sit in TIME_WAIT.

Regression for the 2026-09-27 incident: a beacon container sharing its proxy's network
namespace crash-looped on ``http_bind_failed`` for about a minute after a rebuild, because the
old instance's closed connections left TIME_WAIT on the port and the listener had no
``SO_REUSEADDR``. POSIX only; Windows never sets the flag (it would allow port stealing).
"""

from __future__ import annotations

import errno
import os
import socket

import pytest

from beacon.main import _new_listener

pytestmark = pytest.mark.skipif(os.name == "nt", reason="SO_REUSEADDR is set on POSIX only")


def _time_wait_port() -> int:
    """Leave the server side of a closed connection in TIME_WAIT on a fresh loopback port."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = int(server.getsockname()[1])
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    conn, _ = server.accept()
    conn.close()  # the server closes first, so the server side goes to TIME_WAIT
    client.recv(1)  # observe the FIN
    client.close()
    server.close()
    return port


def test_plain_socket_cannot_rebind_during_time_wait() -> None:
    port = _time_wait_port()
    plain = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError) as info:
            plain.bind(("127.0.0.1", port))
        assert info.value.errno == errno.EADDRINUSE
    finally:
        plain.close()


def test_listener_rebinds_during_time_wait() -> None:
    port = _time_wait_port()
    listener = _new_listener()
    try:
        listener.bind(("127.0.0.1", port))
        listener.listen(1)
    finally:
        listener.close()


def test_listener_still_refuses_a_port_someone_is_listening_on() -> None:
    first = _new_listener()
    first.bind(("127.0.0.1", 0))
    first.listen(1)
    port = int(first.getsockname()[1])
    second = _new_listener()
    try:
        with pytest.raises(OSError) as info:
            second.bind(("127.0.0.1", port))
            second.listen(1)
        assert info.value.errno == errno.EADDRINUSE
    finally:
        second.close()
        first.close()
