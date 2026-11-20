#!/usr/bin/env python3
"""Privately provision one local identity credential through the operator API.

Run in the owner Terminal after the DEV-07 profile is ready. This helper never
prints the credential and never retries a management write after uncertainty.
"""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import sys
import uuid


STATE = Path(__file__).resolve().parent / ".state"
HOST = "127.0.0.1"
PORT = 8780
ORIGIN = f"http://{HOST}:{PORT}"


def exchange(connection, path, body, cookie=None, csrf=None):
    headers = {"Host": f"{HOST}:{PORT}", "Origin": ORIGIN, "Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-EzLLMRouter-CSRF"] = csrf
    connection.request("POST", path, body=json.dumps(body, separators=(",", ":")), headers=headers)
    response = connection.getresponse()
    raw = response.read(4096)
    if response.status != 200:
        raise RuntimeError("operator API rejected provisioning with HTTP " + str(response.status))
    return json.loads(raw), response.getheader("Set-Cookie")


def sync_directory(folder):
    descriptor = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main():
    if len(sys.argv) != 3 or not sys.argv[2].isdigit() or int(sys.argv[2]) < 1:
        raise SystemExit("usage: provision.py PRINCIPAL_ID EXPECTED_REVISION")
    principal = sys.argv[1]
    if (
        not principal
        or len(principal) > 128
        or any(
            c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for c in principal
        )
    ):
        raise SystemExit("invalid principal ID")
    folder = STATE / "provisioned"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.chmod(0o700)
    target = folder / (principal + ".credential")
    # Reserve the destination before the one-time API call. Never overwrite an
    # older credential file or issue another provision just to repeat output.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    receipt = folder / (principal + ".provision.json")
    receipt_created, provision_started = False, False
    try:
        password = (STATE / "operator-password").read_text().strip()
        connection = http.client.HTTPConnection(HOST, PORT, timeout=10)
        try:
            login, cookie = exchange(connection, "/operator/v1/login", {"password": password})
            if login.get("role") != "registry_admin" or not cookie:
                raise RuntimeError("local owner administration unavailable")
            operation = {
                "operation_id": "op." + uuid.uuid4().hex,
                "principal_id": principal,
                "expected_revision": int(sys.argv[2]),
            }
            receipt_descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            receipt_created = True
            with os.fdopen(receipt_descriptor, "w") as handle:
                json.dump(operation, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            sync_directory(folder)
            # From this point a failure can follow a committed issuance. Keep
            # the reserved credential and durable operation identity for review.
            provision_started = True
            result, _ = exchange(
                connection,
                "/operator/v1/provision",
                operation,
                cookie=cookie.split(";", 1)[0],
                csrf=login["csrf"],
            )
            secret = result.get("one_time_credential")
            if type(secret) is not str or len(secret) < 32:
                raise RuntimeError("one-time credential unavailable; inspect principal revision")
            with os.fdopen(descriptor, "w") as handle:
                descriptor = -1
                handle.write(secret + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            sync_directory(folder)
            print("Provisioned " + principal + "; private credential file: " + str(target))
        finally:
            connection.close()
    except BaseException as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if provision_started:
            exc.add_note(
                "Provisioning may have issued a credential. Retained "
                + str(target)
                + " and operation receipt "
                + str(receipt)
                + "; inspect the principal revision before any further provisioning."
            )
        else:
            target.unlink(missing_ok=True)
            if receipt_created:
                receipt.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
