"""Shared loopback-only owned-transport resilience matrix; no model service is used."""

from collections import Counter
import argparse
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "tests/fixtures/contracts/transport-security/resilience.json"
POLICY = json.loads(MATRIX.read_text())
CASES = {row["id"]: row for row in POLICY["cases"]}
CAPABILITIES = json.loads(
    (
        ROOT
        / "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-VECTORS-v0.3-CORRECTION-01.json"
    ).read_text()
)["examples"]["capabilities"]
BODY = json.dumps(CAPABILITIES).encode()
COUNTS, LOCK = Counter(), threading.Lock()


def payload(mode):
    if mode == "wrong_body_version":
        return json.dumps({**CAPABILITIES, "contract_version": "0.3"}).encode()
    if mode == "wrong_shape":
        return b'{"contract_version":"0.2"}'
    if mode == "invalid_json":
        return b"{"
    if mode == "duplicate_key":
        return b'{"contract_version":"0.2",' + BODY[1:]
    if mode == "invalid_utf8":
        return b'{"x":"\xff"}'
    if mode in ("unsafe_integer", "fraction", "surrogate"):
        value = {
            "unsafe_integer": b"9007199254740992",
            "fraction": b"1.0",
            "surrogate": b'"\\ud800"',
        }[mode]
        return BODY[:-1] + b',"extra":' + value + b"}"
    if mode == "exact_limit":
        return BODY + b" " * (1048576 - len(BODY))
    return BODY


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
                COUNTS["wrong_encoding"] += 1
        if mode not in CASES:
            self.send_error(400)
            return
        try:
            self.reply(mode)
        except (OSError, ssl.SSLError):
            pass  # Expected peer closure after bounded rejection or expiry.
        finally:
            self.close_connection = True

    def reply(self, mode):
        body = payload(mode)
        if mode == "slow_headers":
            time.sleep(0.6)
        self.send_response(307 if mode == "redirect" else 200)
        if mode != "missing_version":
            self.send_header(
                "EzLLMRouter-Contract-Version", "0.3" if mode == "wrong_version" else "0.2"
            )
        if mode == "duplicate_version":
            self.send_header("EzLLMRouter-Contract-Version", "0.3")
        self.send_header("Connection", "close")
        if mode == "redirect":
            self.send_header("Location", "/redirected")
        if mode in ("gzip", "deflate", "empty_encoding", "identity", "multiple_encoding"):
            encoding = (
                ""
                if mode == "empty_encoding"
                else "identity"
                if mode == "multiple_encoding"
                else mode
            )
            self.send_header("Content-Encoding", encoding)
        if mode == "multiple_encoding":
            self.send_header("Content-Encoding", "gzip")
        if mode in ("chunked", "stream_oversize", "broken_chunk"):
            self.send_header("Transfer-Encoding", "chunked")
        else:
            length = (
                20000000 if mode == "oversize" else len(body) + (10 if mode == "truncated" else 0)
            )
            self.send_header("Content-Length", str(length))
            if mode == "conflicting_lengths":
                self.send_header("Content-Length", str(length + 1))
        self.end_headers()
        self.wfile.flush()
        if mode == "slow_body":
            time.sleep(0.6)
        if mode == "stream_oversize":
            body = b"x" * (1048576 + 1)
        if mode in ("chunked", "stream_oversize", "broken_chunk"):
            for offset in range(0, len(body), 16384):
                chunk = body[offset : offset + 16384]
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            if mode != "broken_chunk":
                self.wfile.write(b"0\r\n\r\n")
        else:
            self.wfile.write(body)


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        cert, key = Path(directory) / "cert.pem", Path(directory) / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        env = {**os.environ, "EZLLMROUTER_TEST_MATRIX": str(MATRIX)}
        threads = []
        for scheme in ("http", "https"):
            server = stack.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), Handler))
            if scheme == "https":
                server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(
                target=lambda server=server: server.serve_forever(poll_interval=0.01)
            )
            thread.start()
            stack.callback(server.shutdown)
            threads.append(thread)
            env[
                "EZLLMROUTER_TEST_TLS_ORIGIN" if scheme == "https" else "EZLLMROUTER_TEST_ORIGIN"
            ] = f"{scheme}://127.0.0.1:{server.server_port}"
        try:
            yield env
        finally:
            stack.close()
            for thread in threads:
                thread.join(5)
                if thread.is_alive():
                    raise RuntimeError("resilience fixture did not stop")


def command(client, origin):
    if client == "go":
        return ["go", "test", "-run", "^TestHTTPTransport$", "-count=1", "."], ROOT / "clients/go"
    if client == "java":
        build = ROOT / "clients/java/build"
        return [
            "java",
            "-ea",
            "-cp",
            str(build / "ezllmrouter-client-0.3.0.jar") + os.pathsep + str(build / "test-classes"),
            "com.cognitivedynamics.ezllmrouter.ClientTest",
            "--http",
            origin,
        ], ROOT
    if client == "dotnet":
        return [
            "dotnet",
            str(
                ROOT
                / "clients/dotnet/EzLLMRouter.Client.Tests/bin/Release/net10.0/EzLLMRouter.Client.Tests.dll"
            ),
            "--http",
            origin,
        ], ROOT
    if client == "rust":
        return [
            "cargo",
            "test",
            "--offline",
            "--manifest-path",
            str(ROOT / "clients/rust/Cargo.toml"),
            "--test",
            "contracts",
            "native_http",
            "--",
            "--exact",
        ], ROOT
    return ["node", str(ROOT / "tests/client_languages/javascript_http.cjs")], ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=("go", "java", "dotnet", "rust", "js"), action="append")
    args = parser.parse_args()
    clients = args.client or ["go", "java"]
    COUNTS.clear()
    with fixture() as env:
        for client in clients:
            invocation, cwd = command(client, env["EZLLMROUTER_TEST_ORIGIN"])
            subprocess.run(invocation, cwd=cwd, env=env, check=True, timeout=120)
    expected = Counter(
        {row["id"]: row["requests"] * len(clients) for row in POLICY["cases"] if row["requests"]}
    )
    if COUNTS != expected:
        raise AssertionError(f"Unexpected request delivery or replay: {COUNTS}")
    print(
        f"HTTP fixture: {len(CASES)} cases per client; exact delivery counts and TLS-before-credential rejection passed."
    )


if __name__ == "__main__":
    main()
