"""Frozen-interface counterexamples; these tests do not enable a sender mechanism."""

import asyncio
import glob
import hashlib
import inspect
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WHEELS = ROOT / "gateway-inputs/dev04/wheels"
EXPECTED = {
    "httpcore": "2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55",
    "httpx": "d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad",
    "anyio": "6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101",
}
for package in (
    "httpcore",
    "httpx",
    "anyio",
    "h11",
    "certifi",
    "idna",
    "sniffio",
    "typing_extensions",
):
    matches = glob.glob(str(WHEELS / (package + "-*.whl")))
    if len(matches) != 1:
        raise RuntimeError("frozen wheel mismatch: " + package)
    wheel = Path(matches[0])
    if package in EXPECTED and hashlib.sha256(wheel.read_bytes()).hexdigest() != EXPECTED[package]:
        raise RuntimeError("frozen wheel hash mismatch: " + package)


import httpcore  # noqa: E402
import httpx  # noqa: E402
from httpcore._backends.anyio import AnyIOStream  # noqa: E402
from anyio._backends._asyncio import SocketStream  # noqa: E402


class FakeTransport:
    def __init__(self, state):
        self.state = state

    def write(self, item):
        self.state["writes"].append((bytes(item), self.state["revoked"]))
        self.state["wrote"].set()

    def is_closing(self):
        return False


class FakeProtocol:
    exception = None

    def __init__(self, writable):
        self.write_event = asyncio.Event()
        if writable:
            self.write_event.set()


class CheckedStream(httpcore.AsyncNetworkStream):
    """The proposed supported hook, intentionally left vulnerable for this test."""

    def __init__(self, lower, state, checked):
        self.lower, self.state, self.checked = lower, state, checked

    async def write(self, buffer, timeout=None):
        if self.state["revoked"]:
            raise RuntimeError("revoked before stream entry")
        self.checked.set()
        await self.lower.write(buffer, timeout=timeout)


class FrozenFreshnessInterfaceTests(unittest.TestCase):
    def test_supported_backend_hook_is_below_httpx_constructor(self):
        self.assertEqual(httpcore.__version__, "1.0.9")
        self.assertEqual(httpx.__version__, "0.28.1")
        self.assertIn("network_backend", inspect.signature(httpcore.AsyncConnectionPool).parameters)
        self.assertNotIn("network_backend", inspect.signature(httpx.AsyncHTTPTransport).parameters)
        self.assertTrue(inspect.iscoroutinefunction(httpcore.AsyncNetworkStream.write))

    def test_revoke_after_stream_check_before_pinned_anyio_first_write(self):
        async def scenario():
            state = {"revoked": False, "writes": [], "wrote": asyncio.Event()}
            checked = asyncio.Event()
            lower = AnyIOStream(SocketStream(FakeTransport(state), FakeProtocol(True)))
            stream = CheckedStream(lower, state, checked)

            async def revoke():
                await checked.wait()
                state["revoked"] = True

            await asyncio.gather(
                asyncio.create_task(revoke()),
                asyncio.create_task(stream.write(b"POST /v1/chat/completions HTTP/1.1\r\n\r\n", 1)),
            )
            return state["writes"]

        writes = asyncio.run(scenario())
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0][1], "the actual pinned SocketStream wrote after revocation")

    def test_cancellation_after_pinned_socket_write_is_uncertain(self):
        async def scenario():
            state = {"revoked": False, "writes": [], "wrote": asyncio.Event()}
            lower = AnyIOStream(SocketStream(FakeTransport(state), FakeProtocol(False)))
            task = asyncio.create_task(
                lower.write(b"POST /v1/chat/completions HTTP/1.1\r\n\r\n", 1)
            )
            await state["wrote"].wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            return task.cancelled(), state["writes"]

        cancelled, writes = asyncio.run(scenario())
        self.assertTrue(cancelled)
        self.assertEqual(len(writes), 1, "cancellation did not undo the earlier write")


if __name__ == "__main__":
    unittest.main(verbosity=2)
