"""Real process kills prove first-byte and reply uncertainty cannot replay work."""

from contextlib import closing
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import unittest

from ezllmrouter_server.store import SQLiteStore
from tests.development_slice import test_core as core
from tests.fixtures.crash_execution import coordinator
from tests.unit import test_process_durability as processes


@unittest.skipUnless(os.name == "posix", "inherited socket descriptors require POSIX")
class ExecutionCrashTests(unittest.TestCase):
    setUp = processes.ProcessDurabilityTests.setUp
    kill = staticmethod(processes.ProcessDurabilityTests.kill)

    def test_killed_plan_first_request_byte_and_published_replies_preserve_work_identity(self):
        for point in (
            "before_plan",
            "after_plan",
            "after_intent",
            "before_first_byte",
            "after_first_byte",
            "before_reply",
            "after_reply",
        ):
            with (
                self.subTest(point=point),
                closing_socket_pair() as pair,
            ):
                sender, peer = pair
                root = self.root / point
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-B",
                        "-m",
                        "tests.fixtures.crash_execution",
                        str(root),
                        point,
                        str(sender.fileno()),
                    ],
                    pass_fds=(sender.fileno(),),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self.addCleanup(self.kill, process)
                sender.close()
                if point.endswith("reply"):
                    body = json.dumps(core.REQUEST).encode()
                    peer.sendall(
                        b"POST /v1/submissions HTTP/1.1\r\nHost: 127.0.0.1:48761\r\nAuthorization: Bearer token.synthetic\r\nEzLLMRouter-Contract-Version: 0.2\r\nContent-Type: application/json\r\nContent-Length: "
                        + str(len(body)).encode()
                        + b"\r\n\r\n"
                        + body
                    )
                messages = queue.Queue()
                reader = threading.Thread(
                    target=lambda messages=messages, process=process: messages.put(
                        process.stdout.readline()
                    ),
                    daemon=True,
                )
                reader.start()
                try:
                    marker = messages.get(timeout=10)
                    if marker.strip() != "CHECKPOINT":
                        self.fail(
                            "execution child exited before its checkpoint: "
                            + process.stderr.read()[-2000:]
                        )
                    reader.join(1)
                    self.kill(process)
                    peer.settimeout(1)
                    observed = b""
                    while chunk := peer.recv(65536):
                        observed += chunk
                    self.assertEqual(
                        observed[:1],
                        b"P"
                        if point == "after_first_byte"
                        else b"H"
                        if point == "after_reply"
                        else b"",
                    )
                    metadata = json.loads((root / "execution.json").read_text())
                    if point == "after_plan":
                        self.assertTrue(metadata["signed_plan_digest"].startswith("sha256:"))
                    if point == "after_reply":
                        headers, body = observed.split(b"\r\n\r\n", 1)
                        declared = next(
                            line.split(b": ", 1)[1]
                            for line in headers.split(b"\r\n")
                            if line.startswith(b"Content-Length:")
                        )
                        self.assertEqual(len(body), int(declared))
                        self.assertEqual(
                            json.loads(body)["handle"]["submission_id"], metadata["sid"]
                        )
                    for _ in range(2):
                        with closing(SQLiteStore(root / "store.sqlite")) as store:
                            record = store.get(metadata["sid"])
                            self.assertEqual(record["attempt_id"], metadata["aid"])
                            self.assertEqual(
                                store.work_owner(metadata["work_key"])["submission_id"],
                                metadata["sid"],
                            )
                            self.assertEqual(
                                store.intent_count(metadata["sid"]),
                                int(point not in ("before_plan", "after_plan")),
                            )
                            self.assertEqual(
                                store.guard_record(metadata["aid"]) is not None,
                                "first_byte" in point,
                            )
                            if "plan_id" in metadata and point != "after_plan":
                                intent = json.loads(
                                    store.db.execute(
                                        "SELECT intent FROM intents WHERE submission_id=?",
                                        (metadata["sid"],),
                                    ).fetchone()[0]
                                )
                                self.assertEqual(intent["plan_id"], metadata["plan_id"])
                            self.assertEqual(
                                store.db.execute("SELECT count(*) FROM usage_revisions").fetchone()[
                                    0
                                ],
                                int(point.endswith("reply")),
                            )
                            self.assertEqual(
                                store.db.execute("PRAGMA quick_check").fetchone()[0], "ok"
                            )
                        fixture, runtime = coordinator(root)
                        try:
                            runtime.context_sender = lambda *_args: self.fail(
                                "restart replayed an existing attempt"
                            )
                            status, reply = runtime.submit(
                                core.REQUEST,
                                fixture.trusted,
                                credential="token.synthetic",
                                wait_ms=0,
                            )
                            self.assertIn(status, (200, 202))
                            self.assertEqual(reply["handle"]["submission_id"], metadata["sid"])
                            self.assertEqual(len(fixture.adapter.sent), 0)
                            self.assertEqual(fixture.store.get(metadata["sid"]), record)
                        finally:
                            runtime.close()
                            fixture.store.close()
                finally:
                    self.kill(process)


from contextlib import contextmanager


@contextmanager
def closing_socket_pair():
    left, right = socket.socketpair()
    try:
        yield left, right
    finally:
        left.close()
        right.close()
