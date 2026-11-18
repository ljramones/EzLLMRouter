"""Isolated local accounting-only service; no worker, adapter or sender is created."""
from __future__ import annotations

import argparse
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sqlite3
import threading

from .operator_projection import OperatorProjection
from .operator_web import serve as operator_serve
from .mach33_demo import Mach33Demo
from .registry import Registry
from .store import SQLiteStore
from .web import serve as api_serve

RELEASE = version("cognitivedynamics-ezllmrouter-server")
DEST = {"configuration_ref": "cfg.integration.bootstrap", "service": "litellm.dev04",
        "endpoint": "127.0.0.1", "model": "model.demo", "model_version": "v1",
        "processing_region": "local"}


class NoSendAuthority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0
        self.revoked = True


class NoSendRunner:
    def run(self, *_args, **_kwargs):
        raise RuntimeError("MODEL_EXECUTION_DISABLED")


def _secret(path, *, replace=False):
    if path.exists() and not replace:
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("unsafe secret file")
        return path.read_text().strip()
    value = secrets.token_urlsafe(48)
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(8) + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(value + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--secrets-dir", type=Path)
    parser.add_argument("--web-root", type=Path)
    parser.add_argument("--api-port", type=int, default=48760)
    parser.add_argument("--operator-port", type=int, default=48761)
    parser.add_argument("--backup", type=Path, help="write a consistent SQLite backup and exit")
    parser.add_argument("--feature-policy-file", type=Path,
        help="owner-adopted local feature policy; omitted means synthetic low-class snapshots only")
    parser.add_argument("--accounting-retention-days", type=int,
        help="owner-adopted maximum age of a fresh local real cohort, anchored to its T0")
    parser.add_argument("--demo-scope", dest="mach33_demo_scope", type=Path,
        help="absolute private immutable scripted demo scope; separate from the service database")
    parser.add_argument("--mach33-demo-scope", dest="mach33_demo_scope", type=Path,
        help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=RELEASE)
    args = parser.parse_args(argv)
    if args.accounting_retention_days is not None and not 1 <= args.accounting_retention_days <= 397:
        parser.error("accounting retention days must be between 1 and 397")
    if not args.db.is_absolute() or args.api_port == args.operator_port or not (
            1024 <= args.api_port <= 65535 and 1024 <= args.operator_port <= 65535):
        parser.error("absolute DB path and distinct nonprivileged ports required")
    if args.backup:
        if not args.db.is_file() or not args.backup.is_absolute() or args.backup.exists() or args.backup == args.db:
            parser.error("new absolute backup destination required")
        with sqlite3.connect(args.db) as source, sqlite3.connect(args.backup) as target:
            source.backup(target)
        print("consistent backup:", args.backup)
        return
    if not args.secrets_dir or not args.web_root or not args.secrets_dir.is_absolute() or not args.web_root.is_absolute():
        parser.error("absolute secrets and web roots required")
    if args.mach33_demo_scope and not args.mach33_demo_scope.is_absolute():
        parser.error("absolute demo scope required")
    mach33_demo = Mach33Demo(args.mach33_demo_scope) if args.mach33_demo_scope else None
    feature_policy = None
    if args.feature_policy_file:
        policy_path = args.feature_policy_file
        if (not policy_path.is_absolute() or policy_path.is_symlink() or not policy_path.is_file() or
                policy_path.stat().st_mode & 0o022):
            parser.error("feature policy must be an absolute non-writable regular file")
        try:
            feature_policy = json.loads(policy_path.read_text())
        except (ValueError, OSError):
            parser.error("invalid feature policy JSON")
        if (type(feature_policy) is not dict or set(feature_policy) !=
                {"mode", "policy_id", "approved_by", "max_days_by_class"} or
                feature_policy["mode"] != "approved" or feature_policy["approved_by"] != "owner.local" or
                type(feature_policy["policy_id"]) is not str or
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", feature_policy["policy_id"]) or
                type(feature_policy["max_days_by_class"]) is not dict or
                not set(feature_policy["max_days_by_class"]) <= {"low", "internal"} or
                not feature_policy["max_days_by_class"] or
                any(type(days) is not int or not 1 <= days <= 397 for days in
                    feature_policy["max_days_by_class"].values())):
            parser.error("feature policy shape or scope invalid")
    if not (args.web_root / "index.html").is_file():
        parser.error("web root lacks operator assets")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    args.secrets_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.secrets_dir.stat().st_mode & 0o077:
        parser.error("secrets directory must be owner-only")
    first = not args.db.exists()
    if not first and not (args.secrets_dir / "ingest.token").is_file():
        parser.error("existing database requires its original ingest token file")
    store = SQLiteStore(args.db)
    authority = NoSendAuthority()
    if first:
        registry = Registry(store, authority, legacy_destination=DEST,
            legacy_token=secrets.token_urlsafe(48),
            legacy_trusted={"principal_id": "svc.bootstrap", "charging_owner_id": "team.bootstrap"},
            integration_feature_policy=feature_policy,
            integration_accounting_retention_days=args.accounting_retention_days)
        registry.mutate("owner.local", {"operation_id": "op.integration.bootstrap.principal",
            "action": "create_principal", "subject": "svc.integration", "expected_revision": 0,
            "data": {"display_name": "External integration sender", "kind": "service",
                     "owner": "owner.local", "role": "ordinary"}})
        _, ingest_token = registry.provision_credential(
            "owner.local", "svc.integration", 1, "op.integration.bootstrap.credential")
        registry.mutate("owner.local", {"operation_id": "op.integration.bootstrap.activate",
            "action": "principal_state", "subject": "svc.integration", "expected_revision": 2,
            "data": {"status": "active", "reason": "isolated local integration"}})
        path = args.secrets_dir / "ingest.token"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(ingest_token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    else:
        registry = Registry(store, authority, integration_feature_policy=feature_policy,
            integration_accounting_retention_days=args.accounting_retention_days)
    from .integration_credentials import DatabaseCredentialStore
    registry.integration_credentials = DatabaseCredentialStore(
        registry, args.secrets_dir / "integration.master.key")
    consumer_id = "svc.vega.credential-consumer"
    consumer_file = args.secrets_dir / "consumer.token"
    if not registry.principal(consumer_id):
        registry.mutate("owner.local", {"operation_id": "op.integration.consumer.principal",
            "action": "create_principal", "subject": consumer_id, "expected_revision": 0,
            "data": {"display_name": "Vega credential consumer", "kind": "service",
                     "owner": "owner.local", "role": "ordinary"}})
        _, consumer_token = registry.provision_credential(
            "owner.local", consumer_id, 1, "op.integration.consumer.credential")
        registry.mutate("owner.local", {"operation_id": "op.integration.consumer.activate",
            "action": "principal_state", "subject": consumer_id, "expected_revision": 2,
            "data": {"status": "active", "reason": "local credential consumer"}})
        fd = os.open(consumer_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(consumer_token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    elif not consumer_file.is_file() or consumer_file.stat().st_mode & 0o077:
        parser.error("existing credential consumer requires its original private token file")
    if not registry.integration.datasets(registry.principal("owner.local"))["items"]:
        from .integration_accounting import _time
        registry.integration.create_dataset(registry.principal("owner.local"), {
            "dataset_id": "dataset.synthetic.credentials.local", "platform_id": "platform.vega.local",
            "environment_id": "environment.synthetic.credentials.local", "owner_id": "owner.local",
            "ingest_principal_id": "svc.integration", "activated_at": _time()})
    password = _secret(args.secrets_dir / "operator.password")
    # The wire admin credential is deliberately process-local; only the
    # operator password persists. Refresh the file with the issued token.
    admin_token = registry.issue_local_operator_token("owner.local")
    admin_path = args.secrets_dir / "admin.token"
    temporary = admin_path.with_name(".admin.token." + secrets.token_hex(8) + ".issued")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(admin_token + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, admin_path)

    api = api_serve("127.0.0.1", args.api_port, type("AccountingOnly", (), {"registry": registry})(),
                    integration_only=True)
    operator = operator_serve("127.0.0.1", args.operator_port,
        projection=OperatorProjection(store, "svc.integration"), runner=NoSendRunner(),
        password=password, fixture={}, build={"version": RELEASE, "profile": "integration-only"},
        web_root=args.web_root, worker_probe=lambda: {"state": "disabled"},
        sender_status=lambda: {"state": "disabled"}, registry=registry, integration_only=True,
        mach33_demo=mach33_demo)
    thread = threading.Thread(target=operator.serve_forever, daemon=True)
    thread.start()
    stop = threading.Event()
    def halt(_signal, _frame):
        stop.set()
        # BaseServer.shutdown must run outside the serve_forever thread.
        threading.Thread(target=api.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, halt)
    signal.signal(signal.SIGTERM, halt)
    print(f"EzLLMRouter integration-only {RELEASE}; API 127.0.0.1:{args.api_port}; operator http://127.0.0.1:{args.operator_port}/integration",
          flush=True)
    print("credential files:", args.secrets_dir, flush=True)
    try:
        api.serve_forever()
    finally:
        operator.shutdown()
        api.server_close()
        operator.server_close()
        operator.operator_jobs.shutdown(wait=True)
        thread.join(timeout=3)
        store.close()


if __name__ == "__main__":
    main()
