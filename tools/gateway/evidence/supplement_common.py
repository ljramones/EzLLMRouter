"""Shared transport and custody helpers for separately scoped historical proofs."""

from datetime import datetime, timezone
from hashlib import sha256
import http.client
import json
import os
import sqlite3


def digest(raw):
    return sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def now():
    return datetime.now(timezone.utc)


def durable_json(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True).encode() + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return digest(raw)


def capacity_db(path):
    if path.is_symlink():
        raise ValueError("linked capacity record")
    db = sqlite3.connect(path, isolation_level=None, timeout=5)
    db.execute("PRAGMA synchronous=FULL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS allocations "
        "(allocation_key TEXT PRIMARY KEY, record TEXT NOT NULL)"
    )
    return db


def _insert_once(path, key, value):
    raw = canonical(value).decode()
    db = capacity_db(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT record FROM allocations WHERE allocation_key=?", (key,)
        ).fetchone()
        if existing is not None:
            if existing[0] != raw:
                raise AssertionError("single-use allocation conflict")
            outcome = "already_recorded"
        else:
            db.execute("INSERT INTO allocations VALUES (?,?)", (key, raw))
            outcome = "recorded"
        db.commit()
        returned = db.execute(
            "SELECT record FROM allocations WHERE allocation_key=?", (key,)
        ).fetchone()
        if returned is None or returned[0] != raw:
            raise AssertionError("durable allocation readback differs")
        return outcome
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def read_status(runtime, submission_id):
    token = runtime.credentials["DIRECT_DOCUMENT"]
    connection = http.client.HTTPConnection("127.0.0.1", runtime.service_port, timeout=10)
    try:
        connection.request(
            "GET",
            "/v1/submissions/" + submission_id,
            headers={"Authorization": "Bearer " + token, "EzLLMRouter-Contract-Version": "0.3"},
        )
        reply = connection.getresponse()
        raw = reply.read()
        return {
            "http_status": reply.status,
            "response_headers": dict(reply.getheaders()),
            "body_sha256": digest(raw),
            "body": json.loads(raw),
        }
    finally:
        connection.close()


def retained_rows(runtime):
    names = (
        "dev12_campaign_attempts",
        "dev12_submissions",
        "dev12_send_ownership",
        "dev12_usage_revisions",
        "dev12_evidence_events",
        "work_key_owners",
    )
    with runtime.store._lock:
        result = {}
        for name in names:
            cursor = runtime.store.db.execute("SELECT * FROM " + name + " ORDER BY rowid")
            columns = [column[0] for column in cursor.description]
            result[name] = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    return result
