"""Isolated local accounting-only service; no worker, adapter or sender is created."""

from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import re
import secrets
import signal
import sqlite3
import threading

from .observability import configure_logging
from .integration_bootstrap import BootstrapError, ensure_services
from .private_files import secret_text, write_private
from .user_management import UserManager, UserError
from .operator_projection import OperatorProjection
from .operator_web import serve as operator_serve
from .scripted_demo import ScriptedDemo
from .identity import InstanceIdentity
from .external_identity import IdentityLookup
from .registry import Registry
from .store import SQLiteStore
from .instance_lock import InstanceLease, InstanceBusy
from .web import serve as api_serve

try:
    RELEASE = version("cognitivedynamics-ezllmrouter-server")
except PackageNotFoundError:
    from . import __version__ as RELEASE
DEST = {
    "configuration_ref": "cfg.integration.bootstrap",
    "service": "litellm.dev04",
    "endpoint": "127.0.0.1",
    "model": "model.demo",
    "model_version": "v1",
    "processing_region": "local",
}


class NoSendAuthority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0
        self.revoked = True


class NoSendRunner:
    def run(self, *_args, **_kwargs):
        raise RuntimeError("MODEL_EXECUTION_DISABLED")


def _secret(path, *, replace=False):
    return secret_text(path, replace=replace)


def _stop_operator(server, thread):
    if thread.is_alive():
        server.shutdown()
    thread.join(timeout=3)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    defaults = InstanceIdentity()
    parser.add_argument("--platform-id", default="platform.local")
    parser.add_argument("--owner-id", default=defaults.owner_id)
    parser.add_argument("--task-class", default=defaults.task_class)
    parser.add_argument("--credential-consumer-id", default=defaults.credential_consumer_id)
    parser.add_argument("--credential-release-purpose", default=defaults.credential_release_purpose)
    parser.add_argument(
        "--identity-origin", help="optional HTTPS or loopback user-display service origin"
    )
    parser.add_argument(
        "--identity-cookie",
        action="append",
        default=[],
        help="exact cookie name to forward to the configured identity origin",
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--secrets-dir", type=Path)
    parser.add_argument("--web-root", type=Path)
    parser.add_argument("--api-port", type=int, default=48760)
    parser.add_argument("--operator-port", type=int, default=48761)
    parser.add_argument("--backup", type=Path, help="write a consistent SQLite backup and exit")
    parser.add_argument(
        "--feature-policy-file",
        type=Path,
        help="owner-adopted local feature policy; omitted means synthetic low-class snapshots only",
    )
    parser.add_argument(
        "--accounting-retention-days",
        type=int,
        help="owner-adopted maximum age of a fresh local real cohort, anchored to its T0",
    )
    parser.add_argument(
        "--demo-scope",
        dest="scripted_demo_scope",
        type=Path,
        help="absolute private immutable scripted demo scope; separate from the service database",
    )
    parser.add_argument("--version", action="version", version=RELEASE)
    args = parser.parse_args(argv)
    configure_logging()
    try:
        identity = InstanceIdentity(
            args.owner_id,
            args.task_class,
            args.credential_consumer_id,
            args.credential_release_purpose,
        )
        if bool(args.identity_origin) != bool(args.identity_cookie):
            raise ValueError("identity origin and cookie allowlist must be configured together")
        identity_lookup = (
            IdentityLookup(args.identity_origin, tuple(args.identity_cookie))
            if args.identity_origin
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))
    if (
        args.accounting_retention_days is not None
        and not 1 <= args.accounting_retention_days <= 397
    ):
        parser.error("accounting retention days must be between 1 and 397")
    if (
        not args.db.is_absolute()
        or args.api_port == args.operator_port
        or not (1024 <= args.api_port <= 65535 and 1024 <= args.operator_port <= 65535)
    ):
        parser.error("absolute DB path and distinct nonprivileged ports required")
    if args.backup:
        if (
            not args.db.is_file()
            or not args.backup.is_absolute()
            or args.backup.exists()
            or args.backup == args.db
        ):
            parser.error("new absolute backup destination required")
        try:
            with InstanceLease(args.db, exclusive=True):
                write_private(args.backup, b"")
                with (
                    closing(sqlite3.connect(args.db)) as source,
                    closing(sqlite3.connect(args.backup)) as target,
                ):
                    source.backup(target)
        except InstanceBusy:
            parser.error("stop services and other maintenance before backing up")
        print("consistent backup:", args.backup)
        return
    if (
        not args.secrets_dir
        or not args.web_root
        or not args.secrets_dir.is_absolute()
        or not args.web_root.is_absolute()
    ):
        parser.error("absolute secrets and web roots required")
    if args.scripted_demo_scope and not args.scripted_demo_scope.is_absolute():
        parser.error("absolute demo scope required")
    scripted_demo = ScriptedDemo(args.scripted_demo_scope) if args.scripted_demo_scope else None
    feature_policy = None
    if args.feature_policy_file:
        policy_path = args.feature_policy_file
        if (
            not policy_path.is_absolute()
            or policy_path.is_symlink()
            or not policy_path.is_file()
            or policy_path.stat().st_mode & 0o022
        ):
            parser.error("feature policy must be an absolute non-writable regular file")
        try:
            feature_policy = json.loads(policy_path.read_text())
        except (ValueError, OSError):
            parser.error("invalid feature policy JSON")
        if (
            type(feature_policy) is not dict
            or set(feature_policy) != {"mode", "policy_id", "approved_by", "max_days_by_class"}
            or feature_policy["mode"] != "approved"
            or feature_policy["approved_by"] != identity.owner_id
            or type(feature_policy["policy_id"]) is not str
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", feature_policy["policy_id"])
            or type(feature_policy["max_days_by_class"]) is not dict
            or not set(feature_policy["max_days_by_class"]) <= {"low", "internal"}
            or not feature_policy["max_days_by_class"]
            or any(
                type(days) is not int or not 1 <= days <= 397
                for days in feature_policy["max_days_by_class"].values()
            )
        ):
            parser.error("feature policy shape or scope invalid")
    if not (args.web_root / "index.html").is_file():
        parser.error("web root lacks operator assets")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    args.secrets_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.secrets_dir.is_symlink() or args.secrets_dir.stat().st_mode & 0o077:
        parser.error("secrets directory must be owner-only")
    with ExitStack() as cleanup:
        store = SQLiteStore(args.db)
        cleanup.callback(store.close)
        authority = NoSendAuthority()
        registry = Registry(
            store,
            authority,
            legacy_destination=DEST,
            legacy_token=secrets.token_urlsafe(48),
            legacy_trusted={"principal_id": "svc.bootstrap", "charging_owner_id": "team.bootstrap"},
            identity=identity,
            integration_feature_policy=feature_policy,
            integration_accounting_retention_days=args.accounting_retention_days,
        )
        try:
            ensure_services(registry, args.secrets_dir)
        except BootstrapError as exc:
            parser.error(str(exc))
        from .integration_credentials import DatabaseCredentialStore

        registry.integration_credentials = DatabaseCredentialStore(
            registry, args.secrets_dir / "integration.keys.json"
        )
        if not registry.integration.datasets(registry.principal(identity.owner_id))["items"]:
            from .integration_accounting import _time

            registry.integration.create_dataset(
                registry.principal(identity.owner_id),
                {
                    "dataset_id": "dataset.synthetic.credentials.local",
                    "platform_id": args.platform_id,
                    "environment_id": "environment.synthetic.credentials.local",
                    "owner_id": identity.owner_id,
                    "ingest_principal_id": "svc.integration",
                    "activated_at": _time(),
                },
            )
        password = _secret(args.secrets_dir / "operator.password")
        # The wire admin credential is deliberately process-local; only the
        # operator password persists. Refresh the file with the issued token.
        admin_token = registry.issue_local_operator_token(identity.owner_id)
        admin_path = args.secrets_dir / "admin.token"
        write_private(admin_path, (admin_token + "\n").encode("ascii"), replace=True)

        try:
            UserManager(registry, bootstrap_password_file=args.secrets_dir / "admin.password")
        except UserError as exc:
            parser.error(exc.code)
        api = api_serve(
            "127.0.0.1",
            args.api_port,
            type("AccountingOnly", (), {"registry": registry})(),
            integration_only=True,
        )
        cleanup.callback(api.server_close)
        operator = operator_serve(
            "127.0.0.1",
            args.operator_port,
            projection=OperatorProjection(store, "svc.integration"),
            runner=NoSendRunner(),
            password=password,
            fixture={},
            build={"version": RELEASE, "profile": "integration-only"},
            web_root=args.web_root,
            worker_probe=lambda: {"state": "disabled"},
            sender_status=lambda: {"state": "disabled"},
            registry=registry,
            integration_only=True,
            identity_lookup=identity_lookup,
            scripted_demo=scripted_demo,
        )
        cleanup.callback(operator.operator_jobs.shutdown, wait=True)
        cleanup.callback(operator.server_close)
        thread = threading.Thread(target=operator.serve_forever, daemon=True)
        thread.start()
        cleanup.callback(_stop_operator, operator, thread)

        def halt(_signal, _frame):
            # BaseServer.shutdown must run outside the serve_forever thread.
            threading.Thread(target=api.shutdown, daemon=True).start()

        for number in (signal.SIGINT, signal.SIGTERM):
            previous = signal.signal(number, halt)
            cleanup.callback(signal.signal, number, previous)
        print(
            f"EzLLMRouter integration-only {RELEASE}; API 127.0.0.1:{args.api_port}; operator http://127.0.0.1:{args.operator_port}/integration",
            flush=True,
        )
        print("credential files:", args.secrets_dir, flush=True)
        if (args.secrets_dir / "admin.password").exists():
            print("initial admin password file:", args.secrets_dir / "admin.password", flush=True)
        api.serve_forever()


if __name__ == "__main__":
    main()
