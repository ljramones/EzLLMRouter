"""Small local Chrome DevTools client for the one-use operator browser check."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import time
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


class DevTools:
    def __init__(self, endpoint):
        url = urlsplit(endpoint)
        self.sock = socket.create_connection((url.hostname, url.port), timeout=15)
        self.sock.settimeout(30)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        headers = (
            f"GET {url.path} HTTP/1.1\r\nHost: {url.hostname}:{url.port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(headers.encode("ascii"))
        response = bytearray()
        while not response.endswith(b"\r\n\r\n"):
            response.extend(self.sock.recv(1))
            if len(response) > 8192:
                raise RuntimeError("DevTools handshake too large")
        expected = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode(), usedforsecurity=False
            ).digest()
        )
        if (
            not response.startswith(b"HTTP/1.1 101")
            or b"Sec-WebSocket-Accept: " + expected not in response
        ):
            raise RuntimeError("DevTools handshake rejected")
        self.sequence = 0
        self.dialogs = []

    def close(self):
        self.sock.close()

    def _exact(self, count):
        data = bytearray()
        while len(data) < count:
            block = self.sock.recv(count - len(data))
            if not block:
                raise RuntimeError("DevTools socket closed")
            data.extend(block)
        return bytes(data)

    def _send(self, payload, opcode=1):
        data = payload.encode() if isinstance(payload, str) else payload
        length = len(data)
        head = bytearray([0x80 | opcode])
        if length < 126:
            head.append(0x80 | length)
        elif length < 65536:
            head.extend((0x80 | 126, *length.to_bytes(2, "big")))
        else:
            head.extend((0x80 | 127, *length.to_bytes(8, "big")))
        mask = secrets.token_bytes(4)
        self.sock.sendall(
            bytes(head) + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        )

    def _read(self):
        first, second = self._exact(2)
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(self._exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self._exact(8), "big")
        mask = self._exact(4) if second & 0x80 else None
        data = self._exact(length)
        if mask:
            data = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        opcode = first & 0x0F
        if opcode == 9:
            self._send(data, 10)
            return self._read()
        if opcode == 8:
            raise RuntimeError("DevTools closed WebSocket")
        if opcode != 1:
            return self._read()
        return json.loads(data)

    def _request(self, method, params=None):
        self.sequence += 1
        number = self.sequence
        self._send(json.dumps({"id": number, "method": method, "params": params or {}}))
        return number

    def call(self, method, params=None):
        number = self._request(method, params)
        while True:
            item = self._read()
            if item.get("method") == "Page.javascriptDialogOpening":
                self.dialogs.append(item.get("params", {}).get("message", ""))
                self._request("Page.handleJavaScriptDialog", {"accept": True})
            if item.get("id") != number:
                continue
            if "error" in item:
                raise RuntimeError(method + ": " + str(item["error"]))
            return item.get("result", {})

    def evaluate(self, expression):
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": True,
            },
        )
        if "exceptionDetails" in result:
            detail = result["exceptionDetails"]
            description = detail.get("exception", {}).get(
                "description", detail.get("text", "error")
            )
            raise RuntimeError("browser script failed: " + str(description)[:400])
        return result.get("result", {}).get("value")

    def screenshot(self, path):
        encoded = self.call("Page.captureScreenshot", {"format": "png"})["data"]
        Path(path).write_bytes(base64.b64decode(encoded))


class HeadlessChrome:
    def __init__(self, run, url="http://127.0.0.1:8780/"):
        self.run = Path(run)
        self.url = url
        self.log = None
        self.process = None
        self.client = None
        self.profile = None

    def __enter__(self):
        if not CHROME.is_file():
            raise RuntimeError("Google Chrome executable unavailable")
        profile = self.run / "chrome-profile"
        profile.mkdir(mode=0o700, exist_ok=False)
        self.profile = profile
        self.log = (self.run / "chrome.stderr.txt").open("wb")
        self.process = subprocess.Popen(
            [
                str(CHROME),
                "--headless=new",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                "--window-size=1440,1000",
                "--disable-background-networking",
                "--disable-component-update",
                "--no-sync",
                "--user-data-dir=" + str(profile),
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=self.log,
        )
        port_file = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 20
        while not port_file.is_file():
            if self.process.poll() is not None:
                raise RuntimeError("headless Chrome exited before DevTools was ready")
            if time.monotonic() > deadline:
                raise RuntimeError("headless Chrome readiness deadline")
            time.sleep(0.1)
        port = int(port_file.read_text().splitlines()[0])
        request = Request(
            f"http://127.0.0.1:{port}/json/new?" + quote(self.url, safe=""), method="PUT"
        )
        with urlopen(request, timeout=5) as response:
            target = json.load(response)
        self.client = DevTools(target["webSocketDebuggerUrl"])
        self.client.call("Page.enable")
        self.client.call("Runtime.enable")
        return self.client

    def __exit__(self, *_):
        if self.client:
            self.client.close()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()
        if self.profile:
            shutil.rmtree(self.profile)
