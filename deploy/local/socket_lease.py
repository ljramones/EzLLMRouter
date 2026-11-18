"""Reclaim only a refused Unix socket left by this profile's normal stop."""
from pathlib import Path
import socket


def remove_stale_socket(path):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError("socket symlink collision")
    if not path.exists():
        return
    if not path.is_socket():
        raise RuntimeError("socket path is not a socket")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(0.5)
        try:
            client.connect(str(path))
        except ConnectionRefusedError:
            path.unlink()
        else:
            raise RuntimeError("socket already active")
