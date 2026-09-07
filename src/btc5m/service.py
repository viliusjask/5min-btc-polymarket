"""Small service-lifecycle helpers; no trading or credential access."""

from __future__ import annotations

import json
import os
import socket
import tempfile
from pathlib import Path
from typing import Any


def notify(message: str) -> None:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
            channel.settimeout(1)
            channel.connect(address)
            channel.sendall(message.encode())
    except OSError:
        pass  # Failed notification cannot affect committed accounting; supervisor sees timeout.


def atomic_json(path: Path, data: Any) -> None:
    """Publish only a complete, synced file and sync its directory entry."""
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
        ) as stream:
            temporary = stream.name
            json.dump(data, stream, default=str, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
