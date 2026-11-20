"""Loopback-only native transport checks. No service instance or model is used."""

from collections import Counter
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES = json.loads(
    (
        ROOT
        / "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-VECTORS-v0.3-CORRECTION-01.json"
    ).read_text()
)["examples"]["capabilities"]
BODY = json.dumps(CAPABILITIES).encode()
COUNTS = Counter()
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        mode = self.headers.get("Authorization", "").removeprefix("Bearer synthetic-native-")
        with LOCK:
            COUNTS[mode] += 1
            if self.path != "/v1/capabilities":
                COUNTS["foreign_path"] += 1
        if self.headers.get("Accept-Encoding") != "identity":
            with LOCK:
                COUNTS["wrong_encoding"] += 1
        self.send_response(307 if mode == "redirect" else 200)
        self.send_header("EzLLMRouter-Contract-Version", "0.2")
        self.send_header("Connection", "close")
        if mode == "redirect":
            self.send_header("Location", "/redirected")
        if mode == "compressed":
            self.send_header("Content-Encoding", "gzip")
        if mode in ("chunked", "stream_oversize"):
            self.send_header("Transfer-Encoding", "chunked")
        else:
            length = (
                20000000 if mode == "oversize" else len(BODY) + (10 if mode == "truncated" else 0)
            )
            self.send_header("Content-Length", str(length))
        self.end_headers()
        self.wfile.flush()
        if mode == "slow":
            time.sleep(0.6)
        try:
            if mode == "stream_oversize":
                chunk = b"x" * 65536
                for _ in range(128):
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            elif mode == "chunked":
                for offset in range(0, len(BODY), 17):
                    chunk = BODY[offset : offset + 17]
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
            else:
                self.wfile.write(BODY)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=("go", "java", "dotnet", "rust", "js"), action="append")
    args = parser.parse_args()
    clients = args.client or ["go", "java"]
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        env = {**os.environ, "EZLLMROUTER_TEST_ORIGIN": origin}
        try:
            if "go" in clients:
                subprocess.run(
                    ["go", "test", "-run", "^TestHTTPTransport$", "-count=1", "."],
                    cwd=ROOT / "clients/go",
                    env=env,
                    check=True,
                    timeout=60,
                )
            if "java" in clients:
                build = ROOT / "clients/java/build"
                subprocess.run(
                    [
                        "java",
                        "-ea",
                        "-cp",
                        str(build / "ezllmrouter-client-0.3.0.jar")
                        + os.pathsep
                        + str(build / "test-classes"),
                        "com.cognitivedynamics.ezllmrouter.ClientTest",
                        "--http",
                        origin,
                    ],
                    env=env,
                    check=True,
                    timeout=60,
                )
            if "dotnet" in clients:
                subprocess.run(
                    [
                        "dotnet",
                        str(
                            ROOT
                            / "clients/dotnet/EzLLMRouter.Client.Tests/bin/Release/net10.0/EzLLMRouter.Client.Tests.dll"
                        ),
                        "--http",
                        origin,
                    ],
                    env=env,
                    check=True,
                    timeout=60,
                )
            if "rust" in clients:
                subprocess.run(
                    [
                        "cargo",
                        "test",
                        "--manifest-path",
                        str(ROOT / "clients/rust/Cargo.toml"),
                        "--test",
                        "contracts",
                        "native_http",
                        "--",
                        "--exact",
                    ],
                    env=env,
                    check=True,
                    timeout=120,
                )
            if "js" in clients:
                subprocess.run(
                    ["node", str(ROOT / "tests/client_languages/javascript_http.cjs")],
                    env=env,
                    check=True,
                    timeout=60,
                )
        finally:
            server.shutdown()
            thread.join(timeout=5)
    expected = Counter(
        {
            mode: len(clients)
            for mode in (
                "success",
                "redirect",
                "compressed",
                "oversize",
                "chunked",
                "truncated",
                "slow",
            )
        }
    )
    if "js" in clients:
        expected["stream_oversize"] = 1
    if COUNTS != expected:
        raise AssertionError(f"Unexpected request delivery or replay: {COUNTS}")
    print(
        "HTTP fixture: valid replies preserved, expected transport faults rejected, and no request replay."
    )


if __name__ == "__main__":
    main()
