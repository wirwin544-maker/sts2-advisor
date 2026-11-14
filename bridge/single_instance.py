"""Single bridge owner via a loopback bind, released automatically on exit.

This does not accept incoming connections. It only prevents simultaneous bridge
pollers (autostart + manual startup, or two copied installations) from running.
"""
from __future__ import annotations

import socket


def claim_instance(port: int = 15581) -> socket.socket | None:
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        guard.bind(('127.0.0.1', port))
        guard.listen(1)
        return guard
    except OSError:
        guard.close()
        return None
