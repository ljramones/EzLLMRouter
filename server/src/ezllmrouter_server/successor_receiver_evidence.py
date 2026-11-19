"""Read bounded, durable observations from the owned independent synthetic receiver."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import stat


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate receiver receipt key")
        value[key] = item
    return value


class DurableReceiverReceipts:
    """The path is fixed by the isolated assembly, never supplied by an API caller."""

    def __init__(self, path):
        self.path = Path(path)

    def find(self, attempt_id, *, body_sha256, body_bytes, route):
        metadata = self.path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4 * 1024 * 1024:
            raise ValueError("receiver receipt file unavailable or unbounded")
        matching = []
        for line in self.path.read_bytes().splitlines(keepends=True):
            if len(line) > 8192 or not line.endswith(b"\n"):
                raise ValueError("incomplete or unbounded receiver receipt")
            row = json.loads(line.decode("utf-8", "strict"), object_pairs_hook=_unique_pairs)
            if type(row) is not dict or row.get("attempt_id") != attempt_id:
                continue
            if (set(row) != {"kind", "attempt_id", "path", "body_sha256", "body_bytes",
                             "received_at_ns", "usage_component"} or
                    row["kind"] != "native_usage_receipt" or row["path"] != route or
                    row["body_sha256"] != body_sha256 or row["body_bytes"] != body_bytes or
                    type(row["received_at_ns"]) is not int or row["received_at_ns"] <= 0):
                raise ValueError("receiver receipt does not bind guarded attempt")
            component = row["usage_component"]
            if (type(component) is not dict or
                    set(component) != {"component", "presence", "evidence", "quantity", "source_ref"} or
                    component["presence"] != "known" or component["evidence"] != "reported" or
                    component["source_ref"] != "receiver.synthetic.dev12" or
                    component["component"] not in {"search_units", "document_units", "query_units"} or
                    type(component["quantity"]) is not int or not 0 <= component["quantity"] <= 256):
                raise ValueError("receiver native evidence invalid")
            matching.append((row, "sha256:" + sha256(line).hexdigest()))
        if len(matching) != 1:
            raise ValueError("unique retained receiver receipt required")
        return matching[0]
