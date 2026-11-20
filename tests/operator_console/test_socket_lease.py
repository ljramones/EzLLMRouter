"""Normal restart reclaims only a dead profile socket, never a live endpoint."""

from pathlib import Path
import socket
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

from socket_lease import remove_stale_socket


class SocketLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "link.sock"

    def test_missing_and_refused_socket(self):
        remove_stale_socket(self.path)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(self.path))
        self.assertTrue(self.path.exists())
        remove_stale_socket(self.path)
        self.assertFalse(self.path.exists())

    def test_live_socket_remains_untouched(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(self.path))
            listener.listen(1)
            with self.assertRaisesRegex(RuntimeError, "already active"):
                remove_stale_socket(self.path)
            self.assertTrue(self.path.exists())

    def test_symlink_and_regular_file_refused(self):
        self.path.write_text("not a socket")
        with self.assertRaisesRegex(RuntimeError, "not a socket"):
            remove_stale_socket(self.path)
        link = Path(self.tmp.name) / "link-alias.sock"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            remove_stale_socket(link)
        self.assertTrue(self.path.exists())


if __name__ == "__main__":
    unittest.main()
