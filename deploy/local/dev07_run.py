#!/usr/bin/env python3
"""One-use, owner-Terminal DEV-07 synthetic target and migration run.

The runner never forwards a credential on argv or records one in its packet.
Each namespace is single use; after an uncertain send the run stops for review.
"""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import http.client
import json
import os
import re
import shutil
import sys
import time

from deploy.local.check import OperatorClient, wait_health
from deploy.local import local_profile
from deploy.local.command_support import capture


STATE = local_profile.STATE
NAMESPACE = re.compile(r"dev07-[a-z0-9-]{8,32}\Z")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def profile_summary(output):
    """local_profile.py reports stages before its one final machine-readable row."""
    lines = output.splitlines()
    require(bool(lines), "profile summary missing")
    value = json.loads(lines[-1])
    require(type(value) is dict, "profile summary shape")
    return value


class Run:
    def __init__(self, namespace):
        require(NAMESPACE.fullmatch(namespace) is not None, "invalid fresh run namespace")
        self.name = namespace
        self.path = STATE / "dev07-runs" / namespace
        self.path.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.path.chmod(0o700)
        self.events = []
        self.counter = 0
        self.tokens = []
        self.build = None
        self.accepted = []
        self.last_authority_revision = None

    def save(self, label, value):
        # Only redacted, bounded metadata is saved. An unexpected secret in a
        # diagnostic becomes a marker, never a packet field.
        raw = json.dumps(value, sort_keys=True, indent=2)
        for token in self.tokens:
            raw = raw.replace(token, "[REDACTED]")
        (self.path / (label + ".json")).write_text(raw + "\n")
        self.events.append({"step": label, "at_ns": time.time_ns()})

    def command(self, label, argv, *, input_value=None, timeout=120, env=None):
        data = None if input_value is None else json.dumps(input_value)
        completed = capture(
            argv,
            cwd=local_profile.ROOT,
            payload=data,
            timeout=timeout,
            env=env,
        )
        safe_out = local_profile.redact(completed.stdout)
        safe_err = local_profile.redact(completed.stderr)
        for token in self.tokens:
            safe_out = safe_out.replace(token, "[REDACTED]")
            safe_err = safe_err.replace(token, "[REDACTED]")
        (self.path / (label + ".stdout")).write_text(safe_out[-12000:])
        (self.path / (label + ".stderr")).write_text(safe_err[-3000:])
        (self.path / (label + ".exit")).write_text(str(completed.returncode) + "\n")
        if completed.returncode:
            raise RuntimeError(
                label + " exited " + str(completed.returncode) + ": " + safe_err[-300:]
            )
        return completed.stdout.strip()

    def profile(self, label, action, env=None):
        return self.command(
            label,
            [sys.executable, str(local_profile.LOCAL / "local_profile.py"), action],
            timeout=1800,
            env=env,
        )

    def compose(self, label, *args, timeout=15):
        return self.command(
            label,
            local_profile.compose_args(*args),
            timeout=timeout,
            env=local_profile.environment(self.build),
        )

    def operator(self, password):
        client, overview = wait_health(password, seconds=15)
        require(
            overview["build"]["fingerprint"] == self.build["fingerprint"], "running source mismatch"
        )
        return client, overview

    def op(self):
        self.counter += 1
        return "op." + self.name + "." + str(self.counter)

    def mutate(self, client, action, subject, expected, data):
        reply = client.call(
            "POST",
            "/operator/v1/registry",
            {
                "operation_id": self.op(),
                "action": action,
                "subject": subject,
                "expected_revision": expected,
                "data": data,
            },
        )
        self.last_authority_revision = reply["authority_revision"]
        self.save(
            "mutation-" + str(self.counter),
            {
                "action": action,
                "subject": subject,
                "authority_revision": reply["authority_revision"],
                "record_revision": reply["record"]["revision"],
            },
        )
        return reply["record"]

    def provision(self, client, principal):
        reply = client.call(
            "POST",
            "/operator/v1/provision",
            {
                "operation_id": self.op(),
                "principal_id": principal["principal_id"],
                "expected_revision": principal["revision"],
            },
        )
        secret = reply.get("one_time_credential")
        require(type(secret) is str and len(secret) >= 32, "one-time credential unavailable")
        self.tokens.append(secret)
        private = self.path / (principal["principal_id"] + ".credential")
        with private.open("x") as handle:
            handle.write(secret + "\n")
        private.chmod(0o600)
        return reply["record"], secret

    def actor(self, label, language, token, mode, configuration_ref=None):
        image = local_profile.environment(self.build)[
            "EZLLMROUTER_DEV07_PYACTOR_IMAGE"
            if language == "python"
            else "EZLLMROUTER_DEV07_JSACTOR_IMAGE"
        ]
        executable = (
            ["python", "/app/actors/dev07_actor.py"]
            if language == "python"
            else ["node", "/app/consumer/dev07_actor.cjs"]
        )
        args = {
            "token": token,
            "mode": mode,
            "configuration_ref": configuration_ref,
            "step_id": "step." + self.name + "." + label,
            "generation": "gen." + self.name + "." + label,
        }
        argv = [
            *local_profile.DOCKER,
            "run",
            "--rm",
            "-i",
            "--pull=never",
            "--network",
            "container:" + self.netns,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "10001:10001" if language == "python" else "1000:1000",
            image,
            *executable,
        ]
        output = self.command("actor-" + label, argv, input_value=args, timeout=45)
        result = json.loads(output)
        require(
            type(result) is dict and result.get("kind") == ("denied" if mode == "deny" else mode),
            "actor result shape",
        )
        if mode in ("text", "no_store", "tool"):
            self.accepted.extend(result["submission_ids"])
        self.save("actor-" + label, result)
        return result

    def metadata(self, name, path, service):
        code = (
            "import pathlib; p=pathlib.Path(" + repr(path) + "); "
            "print(p.read_text() if p.exists() else '')"
        )
        raw = self.compose(name, "exec", "-T", service, "python", "-c", code)
        return [json.loads(line) for line in raw.splitlines() if line.strip()]

    def arrivals(self, label):
        code = "import pathlib; p=pathlib.Path('/data/arrivals.jsonl'); print(p.read_text() if p.exists() else '')"
        raw = self.compose(label, "exec", "-T", "receiver", "python", "-c", code)
        return [json.loads(line) for line in raw.splitlines() if line.strip()]

    def detail(self, client, sid):
        return client.call("GET", "/operator/v1/activity/" + sid)

    def wait_for(self, label, check, seconds=6):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = check()
            if value:
                return value
            time.sleep(0.05)
        raise RuntimeError(label + " observation deadline")

    def release(self, label):
        code = (
            "import http.client; c=http.client.HTTPConnection('127.0.0.1',8766,timeout=3); "
            "c.request('POST','/control/release'); r=c.getresponse(); r.read(); "
            "assert r.status==200; c.close()"
        )
        self.compose(label, "exec", "-T", "receiver", "python", "-c", code)


def register(run, client):
    prefix = "fixture." + run.name
    a, b = prefix + ".a", prefix + ".b"
    for ref, label, model, rates in (
        (a, "Alpha model", "model.demo", {"input_uncached": "2", "output_text": "8"}),
        (b, "Beta model", "model.demo.alt", {"input_uncached": "5", "output_text": "10"}),
    ):
        item = run.mutate(
            client,
            "create_model",
            ref,
            0,
            {
                "display_name": label,
                "model": model,
                "model_version": "v1",
                "owner": "owner.local",
                "capabilities": ["text", "tools"] if ref == a else ["text"],
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        item = run.mutate(
            client,
            "publish_price",
            ref,
            item["revision"],
            {
                "price_version": ref + ".price.v1",
                "currency": "USD",
                "rates": rates,
                "source": "synthetic fixture",
                "usage_semantics_version": "synthetic.text.v1",
            },
        )
        run.mutate(
            client,
            "model_state",
            ref,
            item["revision"],
            {"status": "enabled", "reason": "DEV-07 finite synthetic exercise"},
        )
    people = {}
    for suffix, kind, owner in (
        ("alpha", "service", "owner.alpha"),
        ("beta", "service", "owner.beta"),
        ("control", "service", "owner.control"),
        ("reader", "human", "owner.reader"),
        ("ordinary", "human", "owner.ordinary"),
    ):
        pid = prefix + "." + suffix
        item = run.mutate(
            client,
            "create_principal",
            pid,
            0,
            {"display_name": "DEV-07 " + suffix, "kind": kind, "owner": owner},
        )
        item, token = run.provision(client, item)
        item = run.mutate(
            client,
            "principal_state",
            pid,
            item["revision"],
            {"status": "active", "reason": "DEV-07 finite synthetic exercise"},
        )
        if suffix == "reader":
            item = run.mutate(
                client, "set_role", pid, item["revision"], {"role": "read_only_operator"}
            )
        people[suffix] = (item, token)
    for suffix, ref in (("alpha", a), ("beta", b), ("control", b)):
        pid = people[suffix][0]["principal_id"]
        run.mutate(
            client,
            "set_grant",
            pid,
            0,
            {
                "configuration_ref": ref,
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
    return a, b, people


def administration_negatives(run, client, a, b, people):
    before = len(run.arrivals("receiver-before-admin-negatives"))
    reader = OperatorClient(people["reader"][1])
    reader.login()
    ordinary = OperatorClient(people["ordinary"][1])
    ordinary.login()
    require(
        len(ordinary.call("GET", "/operator/v1/principals")["items"]) == 1,
        "ordinary identity sees another principal",
    )
    for actor, action in ((reader, "read-only write"), (ordinary, "ordinary write")):
        try:
            actor.call(
                "POST",
                "/operator/v1/registry",
                {
                    "operation_id": run.op(),
                    "action": "edit_model",
                    "subject": a,
                    "expected_revision": client.call("GET", "/operator/v1/models/" + a)["model"][
                        "revision"
                    ],
                    "data": {"display_name": "Forbidden edit"},
                },
            )
        except RuntimeError as exc:
            require("403" in str(exc), action + " did not fail with 403")
        else:
            raise RuntimeError(action + " unexpectedly succeeded")
    try:
        ordinary.call("GET", "/operator/v1/principals/" + people["alpha"][0]["principal_id"])
    except RuntimeError as exc:
        require("404" in str(exc), "ordinary out-of-scope read status")
    else:
        raise RuntimeError("ordinary out-of-scope read succeeded")
    try:
        OperatorClient(people["alpha"][1]).login()
    except RuntimeError as exc:
        require("401" in str(exc), "service credential console status")
    else:
        raise RuntimeError("service credential logged into human console")
    revision = client.call("GET", "/operator/v1/models/" + a)["model"]["revision"]
    body = json.dumps(
        {
            "operation_id": run.op(),
            "action": "edit_model",
            "subject": a,
            "expected_revision": revision,
            "data": {"display_name": "Forbidden edit"},
        }
    )
    for label, origin, csrf in (
        ("invalid-origin", "http://evil.invalid", client.csrf),
        ("missing-csrf", "http://127.0.0.1:8780", None),
    ):
        connection = http.client.HTTPConnection("127.0.0.1", 8780, timeout=3)
        headers = {
            "Host": "127.0.0.1:8780",
            "Origin": origin,
            "Content-Type": "application/json",
            "Cookie": client.cookie,
        }
        if csrf:
            headers["X-EzLLMRouter-CSRF"] = csrf
        try:
            connection.request("POST", "/operator/v1/registry", body=body, headers=headers)
            response = connection.getresponse()
            response.read()
            require(response.status == 403, label + " did not fail with 403")
        finally:
            connection.close()
    require(
        client.call("GET", "/operator/v1/models/" + a)["model"]["revision"] == revision,
        "rejected API write changed model",
    )
    for principal, ref in (
        (people["beta"][0]["principal_id"], a),
        (people["ordinary"][0]["principal_id"], b),
    ):
        explanation = client.call(
            "GET",
            "/operator/v1/access/explain?principal_id="
            + principal
            + "&configuration_ref="
            + ref
            + "&purpose=execution&task_class=class.demo",
        )
        require(not explanation["allowed"], "Explain access widened an ungranted identity")
    require(
        len(run.arrivals("receiver-after-admin-negatives")) == before,
        "administration reads or negatives sent a model request",
    )
    run.save(
        "administration-negatives",
        {
            "read_only_write": 403,
            "ordinary_write": 403,
            "ordinary_other_principal": 404,
            "service_console_login": 401,
            "invalid_origin": 403,
            "missing_csrf": 403,
            "explain_dispatched": False,
        },
    )


def revocation(run, client, case, a, b, people):
    alpha_id, alpha_token = people["alpha"][0]["principal_id"], people["alpha"][1]
    control_token = people["control"][1]
    before = run.arrivals("receiver-before-" + case)
    prior_controls = len(run.metadata("prior-controls-" + case, "/data/controls.jsonl", "receiver"))
    held = run.actor(case + "-held", "python", control_token, "pending_hold", b)
    held_sid = held["submission_id"]
    run.wait_for(
        "receiver held", lambda: len(run.arrivals("receiver-held-" + case)) == len(before) + 1
    )
    run.wait_for(
        "hold control",
        lambda: any(
            row["event"] == "hold_entered_after_receiver_arrival"
            for row in run.metadata("hold-controls-" + case, "/data/controls.jsonl", "receiver")[
                prior_controls:
            ]
        ),
    )
    queued = run.actor(case + "-queued", "python", alpha_token, "pending_text", a)
    queued_sid = queued["submission_id"]

    def queued_record():
        try:
            value = run.detail(client, queued_sid)
            return value if value.get("attempt_id") else None
        except RuntimeError:
            return None

    queued_detail = run.wait_for("queued attempt", queued_record)
    attempt = queued_detail["attempt_id"]
    require(attempt is not None, "queued attempt identity unavailable")
    # A durable guard receipt and an existing held receiver request establish
    # the before-first-write boundary without inspecting httpcore internals.
    run.wait_for(
        "guarded attempt awaiting first write",
        lambda: run.detail(client, queued_sid)["dispatch_receipt"]["present"],
    )
    require(
        len(run.arrivals("receiver-queued-" + case)) == len(before) + 1,
        "queued request reached receiver before revocation",
    )
    if case == "grant":
        grant = client.call("GET", "/operator/v1/principals/" + alpha_id)["grants"]
        current = next(row for row in grant if row["configuration_ref"] == a)
        changed = run.mutate(
            client,
            "set_grant",
            alpha_id,
            current["revision"],
            {
                "configuration_ref": a,
                "status": "removed",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        restore = (
            "set_grant",
            alpha_id,
            changed["revision"],
            {
                "configuration_ref": a,
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
    elif case == "principal":
        current = client.call("GET", "/operator/v1/principals/" + alpha_id)["principal"]
        changed = run.mutate(
            client,
            "principal_state",
            alpha_id,
            current["revision"],
            {"status": "suspended", "reason": "DEV-07 queued revocation"},
        )
        restore = (
            "principal_state",
            alpha_id,
            changed["revision"],
            {"status": "active", "reason": "DEV-07 controlled restoration"},
        )
    else:
        current = client.call("GET", "/operator/v1/models/" + a)["model"]
        changed = run.mutate(
            client,
            "model_state",
            a,
            current["revision"],
            {"status": "disabled", "reason": "DEV-07 queued revocation"},
        )
        restore = (
            "model_state",
            a,
            changed["revision"],
            {"status": "enabled", "reason": "DEV-07 controlled restoration"},
        )
    run.save(
        "revocation-ack-" + case,
        {
            "case": case,
            "changed_record_revision": changed["revision"],
            "authority_revision": run.last_authority_revision,
            "queued_attempt": attempt,
            "ack_monotonic_ns": time.monotonic_ns(),
        },
    )
    run.release("receiver-release-" + case)
    held_detail = run.wait_for(
        "held completion",
        lambda: (lambda x: x if x["submission_state"] == "completed" else None)(
            run.detail(client, held_sid)
        ),
        10,
    )
    blocked = run.wait_for(
        "queued terminal",
        lambda: (lambda x: x if x["submission_state"] not in ("admitted", "running") else None)(
            run.detail(client, queued_sid)
        ),
        10,
    )
    # The guard commits its attempt-linked receipt before entering the lower
    # pool. That receipt is expected even though no first byte is accepted.
    require(
        blocked["error_code"] in ("FDC_REJECTED", "PLAN_INVALID_OR_STALE")
        and blocked["intent"]["present"]
        and blocked["dispatch_receipt"]["present"],
        "queued revocation lost its pre-send intent or receipt",
    )
    require(held_detail["dispatch_receipt"]["present"], "held positive lost send receipt")
    run.accepted.append(held_sid)
    after = run.arrivals("receiver-after-" + case)
    require(
        len(after) == len(before) + 1 and not any(x["attempt_id"] == attempt for x in after),
        "revoked queued attempt arrived",
    )
    send_rows = [
        row
        for row in run.metadata("send-events-" + case, "/data/send-events.jsonl", "service")
        if row.get("attempt_id") == attempt
    ]
    require(
        len(send_rows) == 1
        and send_rows[0].get("first_acceptance_events") == 0
        and send_rows[0].get("first_bytes_accepted_by_local_socket") is False,
        "queued attempt lacks a zero-first-write sender observation",
    )
    time.sleep(5.2)
    require(len(run.arrivals("receiver-horizon-" + case)) == len(after), "late revoked arrival")
    run.mutate(client, *restore)
    restored = run.actor(case + "-restored", "python", alpha_token, "text", a)
    require(restored["selected_model"] == "model.demo", "restored route mismatch")
    restored_arrivals = run.arrivals("receiver-restored-" + case)
    require(
        len(restored_arrivals) == len(before) + 2
        and not any(x["attempt_id"] == attempt for x in restored_arrivals),
        "restored positive or queued negative receiver inventory mismatch",
    )
    run.save(
        "revocation-" + case,
        {
            "held_submission": held_sid,
            "queued_submission": queued_sid,
            "queued_attempt": attempt,
            "queued_error": blocked["error_code"],
            "held_completed": True,
            "queued_first_acceptance_events": 0,
            "new_receiver_requests": len(restored_arrivals) - len(before),
            "restored_submission": restored["submission_ids"][0],
            "finite_horizon_seconds": 5.2,
        },
    )


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: dev07_run.py dev07-FRESH-NAMESPACE")
    require(os.environ.get("EZLLMROUTER_ARTIFACT_ROOT"), "declared frozen artifact root required")
    run = Run(sys.argv[1])
    try:
        # Save older command logs separately before local_profile.py writes new command names.
        if (STATE / "commands").is_dir():
            shutil.copytree(STATE / "commands", run.path / "pre-dev07-commands")
        run.build = local_profile.current()
        password = (STATE / "operator-password").read_text().strip()
        _, previous = wait_health(password, seconds=15)
        counts = previous["counts"]
        require(
            counts["submissions"] >= 7
            and counts["completed"] == counts["submissions"]
            and counts["unknown_outcomes"] == 0,
            "old profile not quiescent",
        )
        run.save(
            "pre-upgrade-profile",
            {
                "build": previous["build"],
                "counts": counts,
                "receiver_arrivals": len(run.arrivals("receiver-pre-upgrade")),
            },
        )
        backup = profile_summary(run.profile("pre-migration-backup", "backup"))
        require(
            backup["submissions"] == counts["submissions"],
            "backup and quiescent profile submission counts differ",
        )
        env = dict(os.environ)
        run.profile("offline-prepare", "prepare", env)
        run.build = local_profile.current()
        run.profile("build-scoped-images", "build-images", env)
        run.profile("build-installed-actors", "build-actors", env)
        run.profile("upgrade-restart", "restart", env)
        client, overview = run.operator(password)
        initial = run.arrivals("receiver-initial")
        run.netns = run.compose("netns-id", "ps", "-q", "netns")
        require(bool(re.fullmatch(r"[0-9a-f]{12,64}", run.netns)), "netns identity unavailable")
        a, b, people = register(run, client)
        administration_negatives(run, client, a, b, people)
        alpha, beta = people["alpha"][1], people["beta"][1]
        positive = []
        positive.append(run.actor("alpha-a-v1", "python", alpha, "text", a))
        positive.append(run.actor("beta-b", "js", beta, "text", b))
        denied = run.actor("alpha-b-denied", "js", alpha, "deny", b)
        require(denied["code"] == "POLICY_DENIED", "missing grant accepted")
        run.mutate(
            client,
            "set_grant",
            people["alpha"][0]["principal_id"],
            0,
            {
                "configuration_ref": b,
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        positive.append(run.actor("alpha-b-granted", "js", alpha, "text", b))
        model = client.call("GET", "/operator/v1/models/" + a)["model"]
        run.mutate(
            client,
            "publish_price",
            a,
            model["revision"],
            {
                "price_version": a + ".price.v2",
                "currency": "USD",
                "source": "synthetic fixture",
                "rates": {"input_uncached": "3", "output_text": "12"},
                "usage_semantics_version": "synthetic.text.v1",
            },
        )
        positive.append(run.actor("alpha-a-v2", "python", alpha, "text", a))
        require(
            positive[0]["price_version"] == a + ".price.v1"
            and positive[-1]["price_version"] == a + ".price.v2"
            and positive[0]["cost"]["amount_decimal"] == "0.000026"
            and positive[-1]["cost"]["amount_decimal"] == "0.000039",
            "actual receiver usage was not priced at v1/v2",
        )
        old = run.detail(client, positive[0]["submission_ids"][0])
        require(
            old["usage"]["price_version"] == a + ".price.v1"
            and old["usage"]["cost"]["amount_decimal"] == "0.000026",
            "published A-v2 repriced historical A-v1 work",
        )
        positive.append(run.actor("alpha-a-no-store", "python", alpha, "no_store", a))
        positive.append(run.actor("alpha-a-tool", "python", alpha, "tool", a))
        for case in ("grant", "principal", "model"):
            revocation(run, client, case, a, b, people)
        arrivals = _verify_independent_receiver_correlation(client, initial, positive, run)
        # Leave an explicit revoked grant for the restart anti-resurrection readback.
        alpha_id = people["alpha"][0]["principal_id"]
        grant = next(
            x
            for x in client.call("GET", "/operator/v1/principals/" + alpha_id)["grants"]
            if x["configuration_ref"] == b
        )
        run.mutate(
            client,
            "set_grant",
            alpha_id,
            grant["revision"],
            {
                "configuration_ref": b,
                "status": "removed",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        before_restart = len(arrivals)
        run.profile("persistence-restart", "restart", env)
        client, after = run.operator(password)
        require(
            after["counts"]["submissions"] >= overview["counts"]["submissions"] + 13,
            "completed submission metadata lost on restart",
        )
        require(
            len(run.arrivals("receiver-after-restart")) == before_restart,
            "ordinary restart added provider request",
        )
        explain = client.call(
            "GET",
            "/operator/v1/access/explain?principal_id="
            + alpha_id
            + "&configuration_ref="
            + b
            + "&purpose=execution&task_class=class.demo",
        )
        require(explain["reason"] == "GRANT_MISSING", "removed grant resurrected")
        run.save(
            "result",
            {
                "kind": "DEV-07 finite synthetic target",
                "status": "PASS",
                "source": after["build"],
                "backup_sha256": backup["sha256"],
                "preexisting_submissions": backup["submissions"],
                "receiver_before": len(initial),
                "receiver_after": before_restart,
                "new_receiver_requests": 13,
                "caller_lookups": 1,
                "revocation_cases": 3,
                "revoked_grant_after_restart": True,
                "browser_walkthrough": "pending owner observation",
            },
        )
        print("DEV-07 finite target PASS; evidence: " + str(run.path / "result.json"))
        print("Running console: http://127.0.0.1:8780/; browser walkthrough remains")
    except BaseException as exc:
        run.save(
            "failure",
            {
                "kind": "DEV-07 target failure",
                "error_type": type(exc).__name__,
                "message": str(exc)[:300],
                "last_step": run.events[-1] if run.events else None,
            },
        )
        print(
            "DEV-07 stopped: " + type(exc).__name__ + "; evidence: " + str(run.path),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def _verify_independent_receiver_correlation(client, initial, positive, run):
    arrivals = run.arrivals("receiver-final")
    require(len(arrivals) - len(initial) == 13, "finite target receiver inventory is not 13")
    require(
        len(run.accepted) == 13 and len(set(run.accepted)) == 13,
        "accepted submission inventory is not thirteen distinct records",
    )
    new_rows = arrivals[len(initial) :]
    by_attempt = {}
    for row in new_rows:
        require(row["attempt_id"] not in by_attempt, "duplicate receiver attempt")
        by_attempt[row["attempt_id"]] = row
    correlated = []
    for sid in run.accepted:
        detail = run.detail(client, sid)
        observed = by_attempt.get(detail["attempt_id"])
        receipt = detail["dispatch_receipt"]
        require(
            detail["submission_state"] == "completed"
            and receipt["present"]
            and observed
            and observed["body_sha256"] == receipt["body_sha256"]
            and observed["body_bytes"] == receipt["body_bytes"]
            and observed["model"] == detail["selected_configuration"]["model"],
            "service receipt and independent receiver mismatch",
        )
        correlated.append(
            {
                "submission_id": sid,
                "attempt_id": detail["attempt_id"],
                "model": observed["model"],
                "body_sha256": observed["body_sha256"],
                "price_version": detail["usage"].get("price_version"),
            }
        )
    run.save("receiver-correlation", {"count": len(correlated), "rows": correlated})
    require(
        sum(x.get("caller_lookups", 0) for x in positive) == 1,
        "finite target caller lookup inventory is not one",
    )
    return arrivals


if __name__ == "__main__":
    main()
