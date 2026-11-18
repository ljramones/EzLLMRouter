"""The loopback publisher relays only to the fixed internal console."""
from pathlib import Path
import socket
import socketserver
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy/local"))
import console_ingress


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(self.request.recv(100))


class IngressTests(unittest.TestCase):
    def test_fixed_relay_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "echo.sock"
            with socketserver.ThreadingUnixStreamServer(str(path), Echo) as target:
                worker = threading.Thread(target=target.serve_forever, daemon=True)
                worker.start()
                with patch.object(console_ingress, "TARGET", path):
                    with console_ingress.Server(("127.0.0.1", 0), console_ingress.Handler) as ingress:
                        relay = threading.Thread(target=ingress.serve_forever, daemon=True)
                        relay.start()
                        with socket.create_connection(ingress.server_address, timeout=2) as client:
                            client.sendall(b"synthetic-console")
                            self.assertEqual(client.recv(100), b"synthetic-console")
                        ingress.shutdown()
                        relay.join(timeout=2)
                target.shutdown()
                worker.join(timeout=2)

    def test_only_ingress_publishes_loopback_and_trusted_namespace_stays_internal(self):
        compose = (ROOT / "deploy/local/compose.yaml").read_text()
        netns = compose.split("  netns:\n", 1)[1].split("  receiver:\n", 1)[0]
        worker = compose.split("  worker:\n", 1)[1].split("  service:\n", 1)[0]
        service = compose.split("  service:\n", 1)[1].split("  ingress:\n", 1)[0]
        ingress = compose.split("  ingress:\n", 1)[1].split("\nvolumes:\n", 1)[0]
        self.assertNotIn("ports:", netns)
        self.assertIn("network_mode: none", worker)
        self.assertIn('ports: ["127.0.0.1:8780:8780"]', ingress)
        self.assertIn("networks: [console_publish]", ingress)
        self.assertIn("local_private:\n    internal: true", compose)
        self.assertIn("console_link_data:/console", service)
        self.assertIn("console_link_data:/console", ingress)
        self.assertNotIn("local_private", ingress)
        self.assertNotIn("credentials", ingress)
        self.assertNotIn("- link_data:/link", ingress)
        self.assertEqual(console_ingress.TARGET, Path("/console/operator.sock"))


if __name__ == "__main__":
    unittest.main()
