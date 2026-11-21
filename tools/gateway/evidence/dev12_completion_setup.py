"""dev12_completion_runner setup domain; entry points remain on the facade."""

from __future__ import annotations

from pathlib import Path


@staticmethod
def _wait_port(process, port: int):
    from tools.gateway.evidence import dev12_completion_runner as _api

    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("controlled TLS receiver stopped during startup")
        try:
            with _api.socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            _api.time.sleep(0.05)
    raise TimeoutError("controlled TLS receiver readiness")


@staticmethod
def _operator_port(envelope: dict, free_port) -> int:
    from tools.gateway.evidence import dev12_completion_runner as _api

    declared = _api.os.environ.get("DEV12_OPERATOR_PORT")
    if declared is None:
        if "operator_port" in envelope:
            raise RuntimeError("planned operator port requires exact runtime declaration")
        return free_port()
    if (
        not declared.isascii()
        or not declared.isdecimal()
        or type(envelope.get("operator_port")) is not int
        or int(declared) != envelope["operator_port"]
        or not 1024 <= int(declared) <= 65535
    ):
        raise RuntimeError("fixed operator port differs from exact plan")
    port = int(declared)
    with _api.socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    return port


def _bind_contexts(self):
    """Use A1 vectors for three distinct, synthetic authenticated roles."""
    from tools.gateway.evidence import dev12_completion_runner as _api
    from tools.gateway.evidence.dev12_integrated import fixture

    identities = ("DIRECT_DOCUMENT", "DELEGATED_RERANK", "AUTONOMOUS_QUERY")
    for index, vector_id in enumerate(identities):
        request, context = fixture(vector_id)
        context["identity"]["charging_owner_id"] = self.plan["envelope"]["financial_owner_id"]
        token = f"dev12.completion02.synthetic.{index}." + "x" * 32
        if vector_id == "DIRECT_DOCUMENT":
            retained = self.root / "continuation-direct-secret.json"
            if retained.exists():
                if retained.is_symlink() or retained.stat().st_mode & 0o077:
                    raise RuntimeError("retained disposable direct credential unsafe")
                token = _api.json.loads(retained.read_text())["direct"]
        self.credentials[vector_id] = token
        self.contexts_by_credential[token] = context
    return {
        token: {
            **context["identity"],
            "task_id": fixture(vector_id)[0]["work_selector"]["task_id"],
            "expires_at": context["expires_at"],
        }
        for vector_id, token in self.credentials.items()
        for context in (self.contexts_by_credential[token],)
    }


def persist_signer(self, private_key, version: str) -> Path:
    """Retain synthetic rotation material before authority publishes its selector."""
    from tools.gateway.evidence import dev12_completion_runner as _api
    from cryptography.hazmat.primitives import serialization

    if not version.startswith("v.") or not version.replace(".", "").isalnum():
        raise ValueError("bounded synthetic signer version required")
    path = self.root / ("signing-key-" + version + ".pem")
    raw = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        _api.os.fsync(stream.fileno())
    path.chmod(0o600)
    return path


def _ensure_continuation_other_credential(self) -> None:
    """Recover only the disposable ordinary login when its case needs it."""
    from tools.gateway.evidence import dev12_completion_runner as _api

    if self.operator_credentials.get("other"):
        return
    credential_file = self.root / "continuation-operator-secret.json"
    if credential_file.exists():
        if credential_file.is_symlink() or credential_file.stat().st_mode & 0o077:
            raise RuntimeError("retained synthetic operator secret is unsafe")
        other_secret = _api.json.loads(credential_file.read_text())["other"]
    else:
        principals = [
            item
            for item in self.registry.list_principals()
            if item["principal_id"] == "user.other.synthetic"
        ]
        if len(principals) != 1:
            raise RuntimeError("original synthetic ordinary principal absent")
        # An earlier disposable continuation can stop after registry
        # rotation but before the one-time secret is retained. Bind each
        # recovery operation to the observed principal revision so a lost
        # synthetic secret can be rotated again without replaying an
        # already committed one-use operation.
        revision = principals[0]["revision"]
        _, other_secret = self.registry.provision_credential(
            "owner.local",
            "user.other.synthetic",
            revision,
            "op.dev12.completion02.credential.other.revision." + str(revision),
        )
        if not other_secret:
            raise RuntimeError("synthetic ordinary credential cannot be recovered")
        raw = _api._json_bytes({"other": other_secret})
        with _api.os.fdopen(
            _api.os.open(
                credential_file, _api.os.O_WRONLY | _api.os.O_CREAT | _api.os.O_EXCL, 0o600
            ),
            "wb",
        ) as stream:
            if stream.write(raw) != len(raw):
                raise OSError("short synthetic credential write")
            stream.flush()
            _api.os.fsync(stream.fileno())
        _api.append_durable(
            self.journal,
            {
                "kind": "continuation_synthetic_credential_rotated",
                "at": _api.time.time_ns(),
                "principal_id": "user.other.synthetic",
                "purpose": "T-62.e isolated cross-principal read check",
            },
        )
    self.operator_credentials["other"] = other_secret


def _install_exact_clients(self):
    """Unpack reviewed artifact bytes locally, with no package acquisition."""
    from tools.gateway.evidence import dev12_completion_runner as _api

    artifacts = {row["kind"]: _api.Path(row["path"]) for row in self.plan["artifacts"]}
    self.installed_python_root = self.root / "installed-python"
    self.installed_js_root = (
        self.root / "installed-js" / "node_modules" / "@mach33" / "ezllmrouter-client"
    )
    self.installed_python_root.mkdir()
    self.installed_js_root.mkdir(parents=True)
    with _api.zipfile.ZipFile(artifacts["python_wheel"]) as package:
        for member in package.infolist():
            destination = _api.Path(member.filename)
            if (
                destination.is_absolute()
                or ".." in destination.parts
                or member.is_dir()
                and member.file_size
            ):
                raise ValueError("unsafe Python wheel member")
            target = self.installed_python_root / destination
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as source, target.open("xb") as output:
                    output.write(source.read())
    with _api.tarfile.open(artifacts["js_tarball"], "r:gz") as package:
        for member in package:
            destination = _api.Path(member.name)
            if (
                destination.is_absolute()
                or ".." in destination.parts
                or not destination.parts
                or destination.parts[0] != "package"
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("unsafe CommonJS package member")
            target = self.installed_js_root.joinpath(*destination.parts[1:])
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.extractfile(member) as source, target.open("xb") as output:
                    output.write(source.read())
    _api.sys.path.insert(0, str(self.installed_python_root))


def start(self, *, finite_scope=None):
    """Called only after a passing no-send preflight and explicit release."""
    from tools.gateway.evidence import dev12_completion_runner as _api

    if self.started:
        raise RuntimeError("campaign assembly already started")
    if (self.root / "campaign.sqlite").exists() or self.journal.exists():
        raise RuntimeError("existing durable campaign requires continuation, not reset")
    if finite_scope is not None:
        if self.plan["envelope"]["campaign_id"] == "campaign.dev12.c02.ct02b.supp02":
            from tools.gateway.evidence.dev12_ct02b_supp02 import supplemental_limits
        else:
            from tools.gateway.evidence.dev12_ct02b_supplement import supplemental_limits
        supplemental_limits(self.plan, finite_scope)
    _api.sys.path[:0] = [
        str(_api.ROOT / "server/src"),
        str(_api.HERE),
        str(_api.ROOT / "tests/development_slice"),
    ]
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from ezllmrouter_server.core import Coordinator
    from ezllmrouter_server.operator_projection import OperatorProjection
    from ezllmrouter_server.operator_web import serve as serve_operator
    from ezllmrouter_server.registry import Registry
    from ezllmrouter_server.store import SQLiteStore
    from tools.synthetic.successor_assembly import attach_standalone_synthetic
    from tools.synthetic.successor_authority import SyntheticSuccessorAuthority
    from tools.synthetic.successor_campaign import FiniteSuccessorCampaign
    from tools.synthetic.successor_receiver_evidence import DurableReceiverReceipts
    from ezllmrouter_server.web import serve
    from tools.gateway.evidence.dev12_executor import Dev12SyntheticExecutor
    from tools.gateway.evidence.dev12_integrated import certificate, free_port
    from tools.gateway.evidence.dev12_completion_preflight import mounted_source_identity
    from tools.gateway.evidence.dev12_tls_receiver import TEST_KEY

    envelope = self.plan["envelope"]
    if (
        envelope.get("service_network_mode") != "bridge"
        or _api.os.environ.get("DEV12_SERVICE_NETWORK_MODE") != "bridge"
    ):
        raise RuntimeError("browser-qualified service requires declared Docker bridge identity")
    worker = _api.Path(_api.os.environ.get("DEV12_WORKER_SOCKET", "/link/dev12-worker.sock"))
    if not worker.is_socket():
        raise RuntimeError("isolated worker socket absent")
    self._install_exact_clients()
    cert, key = certificate(self.root)
    receiver_port, service_port = free_port(), free_port()
    operator_port = self._operator_port(envelope, free_port)
    self.receiver_port = receiver_port
    self.service_port = service_port
    self.operator_port = operator_port
    self.base_url = f"http://127.0.0.1:{service_port}"
    self.operator_url = f"http://127.0.0.1:{operator_port}"
    identities = self._bind_contexts()
    signer = ed25519.Ed25519PrivateKey.generate()
    signing_path = self.root / "signing-key.pem"
    signing_path.write_bytes(
        signer.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    signing_path.chmod(0o600)
    self.receiver = _api.subprocess.Popen(
        (
            _api.sys.executable,
            "-I",
            "-B",
            str(_api.HERE / "dev12_completion_receiver.py"),
            str(cert),
            str(key),
            str(self.receiver_log),
            str(receiver_port),
        ),
        cwd=_api.ROOT,
        stdout=_api.subprocess.DEVNULL,
        stderr=(self.root / "receiver.stderr").open("ab"),
    )
    self._wait_port(self.receiver, receiver_port)
    self.store = SQLiteStore(self.root / "campaign.sqlite")
    self.authority = SyntheticSuccessorAuthority(self.store, signer, "key.synthetic.dev12", "v1")
    direct = self.contexts_by_credential[self.credentials["DIRECT_DOCUMENT"]]["identity"]
    self.registry = Registry(
        self.store,
        self.authority,
        legacy_destination={
            "configuration_ref": "cfg.synthetic.dev12.operator",
            "service": "controlled.synthetic",
            "endpoint": "127.0.0.1",
            "model": "model.demo",
            "model_version": "synthetic-v1",
            "processing_region": "local",
        },
        legacy_token=self.credentials["DIRECT_DOCUMENT"],
        legacy_trusted=direct,
    )
    ordinary = self.registry.mutate(
        "owner.local",
        {
            "operation_id": "op.dev12.completion02.create.other",
            "action": "create_principal",
            "subject": "user.other.synthetic",
            "expected_revision": 0,
            "data": {
                "display_name": "Other synthetic user",
                "kind": "human",
                "owner": "owner.local",
            },
        },
    )["record"]
    ordinary, other_secret = self.registry.provision_credential(
        "owner.local",
        ordinary["principal_id"],
        ordinary["revision"],
        "op.dev12.completion02.credential.other",
    )
    self.registry.mutate(
        "owner.local",
        {
            "operation_id": "op.dev12.completion02.activate.other",
            "action": "principal_state",
            "subject": ordinary["principal_id"],
            "expected_revision": ordinary["revision"],
            "data": {"status": "active", "reason": "isolated qualification"},
        },
    )
    self.operator_credentials = {
        "owner": "dev12.synthetic.operator." + "x" * 32,
        "other": other_secret,
    }
    for context in self.contexts_by_credential.values():
        self.authority.set_historical_access(
            context["identity"],
            read=True,
            write=True,
            resume=True,
            observed_at=_api.datetime.now(_api.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    self.allowance = FiniteSuccessorCampaign(
        self.store,
        envelope["campaign_id"],
        envelope["budget_account_id"],
        financial_owner_id=envelope["financial_owner_id"],
    )
    identity = mounted_source_identity()
    retained = {
        "plan_sha256": _api.sha256(_api._json_bytes(self.plan)).hexdigest(),
        "source_tree": self.plan["source_tree"],
        "mounted_source": identity,
        "artifacts": self.plan["artifacts"],
        "campaign_id": envelope["campaign_id"],
        "receiver": f"127.0.0.1:{receiver_port}",
        "service": self.base_url,
        "operator": self.operator_url,
        "planned_operator_port": envelope.get("operator_port"),
        "service_network_mode": "bridge",
        "service_default_route_present": any(
            row.split()[1] == "00000000"
            for row in _api.Path("/proc/net/route").read_text().splitlines()[1:]
        ),
        "worker_network_mode": "none",
        "worker_socket": str(worker),
        "real_provider_calls": 0,
    }
    _api.append_durable(self.root / "release-identity.jsonl", retained)
    if finite_scope is None:
        limits = {
            "max_attempts": 512,
            "max_concurrent": 2,
            "ceiling_decimal": "6.000000000",
            "window_hours": 24,
        }
    else:
        limits = supplemental_limits(self.plan, finite_scope)
    self.allowance.start(
        {
            "receiver": retained["receiver"],
            "service": self.base_url,
            "operator": self.operator_url,
        },
        [
            "campaign.sqlite",
            "receiver.jsonl",
            "receiver-receipts.jsonl",
            "guard.jsonl",
            "case-journal.jsonl",
            str(worker),
        ],
        **limits,
    )
    if finite_scope is not None:
        if self.plan["envelope"]["campaign_id"] == "campaign.dev12.c02.ct02b.supp02":
            from tools.gateway.evidence.dev12_ct02b_supp02 import verify_started_limits
        else:
            from tools.gateway.evidence.dev12_ct02b_supplement import verify_started_limits
        verify_started_limits(self.allowance.inspect(), finite_scope)
    self.executor = Dev12SyntheticExecutor(worker, receiver_port, cert.read_text(), TEST_KEY)
    _api.os.environ["EZLLMROUTER_GATEWAY_GUARD_EVENTS"] = str(self.guard_log)

    def permitted(current, original):
        return (
            current["principal_id"] == original["work_key"]["principal_id"]
            and current["source_authority_id"]
            == original["trusted_identity"]["source_authority_id"]
            and current["identity_binding_id"]
            == original["trusted_identity"]["identity_binding_id"]
        )

    self.coordinator = Coordinator(
        self.store,
        identity=identities,
        config={},
        prompt_blocks={},
        allowed_lineages={},
        authority=None,
        adapter=None,
        retention={},
        classification={},
        recipe=None,
    )
    self.successor = attach_standalone_synthetic(
        self.coordinator,
        store=self.store,
        contexts_by_credential=self.contexts_by_credential,
        authority=self.authority,
        executor=self.executor,
        allowance=self.allowance,
        read_allowed=permitted,
        usage_write_allowed=permitted,
        receiver_receipts=DurableReceiverReceipts(self.root / "receiver-receipts.jsonl"),
    )
    self.successor.recover_incomplete()
    self.wire = serve("127.0.0.1", service_port, self.coordinator)
    _api.threading.Thread(target=self.wire.serve_forever, daemon=True).start()
    # Docker publishes this container listener only on the host's 127.0.0.1.
    # Binding container loopback would make the published port unreachable.
    self.operator = serve_operator(
        "0.0.0.0",
        operator_port,
        projection=OperatorProjection(
            self.store, "user.demo", str(self.root / "send-events.jsonl")
        ),
        runner=None,
        password=self.operator_credentials["owner"],
        fixture={"destination": {}, "policy": {}},
        build={"commit": "disposable.dev12", "dirty": False, "fingerprint": identity["sha256"]},
        web_root=_api.ROOT / "web",
        worker_probe=lambda: {"state": "networkless"},
        sender_status=lambda: {"state": "controlled"},
        successor_store=self.store,
        registry=self.registry,
    )
    _api.threading.Thread(target=self.operator.serve_forever, daemon=True).start()
    self.started = True
    _api.append_durable(
        self.journal,
        {
            "kind": "campaign_started",
            "at": _api.time.time_ns(),
            "identity": retained,
            "allowance": self.allowance.inspect(),
        },
    )


def continue_existing(self, checkpoint: dict, receipt: dict) -> None:
    """Reopen one stopped campaign; never start, reseed, or replay it."""
    from tools.gateway.evidence import dev12_completion_runner as _api

    if self.started or not (self.root / "campaign.sqlite").is_file():
        raise RuntimeError("continuation requires one stopped durable campaign")
    _api.sys.path[:0] = [
        str(_api.ROOT / "server/src"),
        str(_api.HERE),
        str(_api.ROOT / "tests/development_slice"),
    ]
    from cryptography.hazmat.primitives import serialization
    from ezllmrouter_server.core import Coordinator
    from ezllmrouter_server.operator_projection import OperatorProjection
    from ezllmrouter_server.operator_web import serve as serve_operator
    from ezllmrouter_server.registry import Registry
    from ezllmrouter_server.store import SQLiteStore
    from tools.synthetic.successor_assembly import attach_standalone_synthetic
    from tools.synthetic.successor_authority import SyntheticSuccessorAuthority
    from tools.synthetic.successor_campaign import FiniteSuccessorCampaign
    from tools.synthetic.successor_receiver_evidence import DurableReceiverReceipts
    from ezllmrouter_server.web import serve
    from tools.gateway.evidence.dev12_executor import Dev12SyntheticExecutor
    from tools.gateway.evidence.dev12_integrated import certificate, free_port
    from tools.gateway.evidence.dev12_completion_preflight import mounted_source_identity
    from tools.gateway.evidence.dev12_tls_receiver import TEST_KEY
    from cryptography import x509
    import sqlite3

    envelope = self.plan["envelope"]
    if (
        envelope.get("service_network_mode") != "bridge"
        or _api.os.environ.get("DEV12_SERVICE_NETWORK_MODE") != "bridge"
    ):
        raise RuntimeError("continuation service network declaration differs")
    worker = _api.Path(_api.os.environ.get("DEV12_WORKER_SOCKET", "/link/dev12-worker.sock"))
    if not worker.is_socket() or not _api.os.access(worker, _api.os.W_OK):
        raise RuntimeError("original isolated worker socket unavailable to service UID")
    self.installed_python_root = self.root / "installed-python"
    self.installed_js_root = (
        self.root / "installed-js" / "node_modules" / "@mach33" / "ezllmrouter-client"
    )
    for installed in (self.installed_python_root, self.installed_js_root):
        if not installed.is_dir() or installed.is_symlink():
            raise RuntimeError("original exact installed-client extraction absent")
    _api.sys.path.insert(0, str(self.installed_python_root))
    cert, key = self.root / "cert.pem", self.root / "key.pem"
    for item in (cert, key):
        if not item.is_file() or item.is_symlink():
            raise RuntimeError("original controlled receiver TLS material absent")
    original_cert_sha256 = _api.sha256(cert.read_bytes()).hexdigest()
    expiration = x509.load_pem_x509_certificate(cert.read_bytes()).not_valid_after.replace(
        tzinfo=_api.timezone.utc
    )
    renewed_tls = expiration <= _api.datetime.now(_api.timezone.utc) + _api.timedelta(minutes=5)
    if renewed_tls:
        # A short-lived synthetic receiver certificate is not campaign
        # authority. Retain the original bytes and use a distinct identity.
        cert, key = certificate(
            self.root, stem="receiver.continue" + str(_api.time.time_ns()), valid_hours=24
        )
    self.receiver_certificate = {
        "path": str(cert.relative_to(self.root)),
        "sha256": _api.sha256(cert.read_bytes()).hexdigest(),
        "original_sha256": original_cert_sha256,
        "renewed": renewed_tls,
    }
    self.receiver_port, self.service_port = free_port(), free_port()
    self.operator_port = self._operator_port(envelope, free_port)
    self.base_url = f"http://127.0.0.1:{self.service_port}"
    self.operator_url = f"http://127.0.0.1:{self.operator_port}"
    identities = self._bind_contexts()
    with sqlite3.connect(f"file:{self.root / 'campaign.sqlite'}?immutable=1", uri=True) as db:
        row = db.execute(
            "SELECT state FROM dev12_authority WHERE authority_id='standalone.synthetic'"
        ).fetchone()
    if row is None:
        raise RuntimeError("original durable authority absent")
    active = _api.json.loads(row[0])["active_minting_key"]
    version = active["key_version"]
    signer_path = (
        self.root / "signing-key.pem"
        if version == "v1"
        else self.root / ("signing-key-" + version + ".pem")
    )
    if not signer_path.is_file() or signer_path.is_symlink():
        raise RuntimeError("exact durable active signer unavailable")
    signer = serialization.load_pem_private_key(signer_path.read_bytes(), password=None)
    self.store = SQLiteStore(self.root / "campaign.sqlite")
    self.authority = SyntheticSuccessorAuthority(self.store, signer, active["key_id"], version)
    direct = self.contexts_by_credential[self.credentials["DIRECT_DOCUMENT"]]["identity"]
    self.registry = Registry(
        self.store,
        self.authority,
        legacy_destination={
            "configuration_ref": "cfg.synthetic.dev12.operator",
            "service": "controlled.synthetic",
            "endpoint": "127.0.0.1",
            "model": "model.demo",
            "model_version": "synthetic-v1",
            "processing_region": "local",
        },
        legacy_token=self.credentials["DIRECT_DOCUMENT"],
        legacy_trusted=direct,
    )
    self.allowance = FiniteSuccessorCampaign(
        self.store,
        envelope["campaign_id"],
        envelope["budget_account_id"],
        financial_owner_id=envelope["financial_owner_id"],
    )
    before = self.allowance.inspect()
    expected = checkpoint["last_campaign"]
    for field in (
        "campaign_id",
        "budget_account_id",
        "financial_owner_id",
        "currency",
        "ceiling_decimal",
        "max_attempts",
        "max_concurrent",
        "start_at",
        "expires_at",
        "attempt_count",
        "possible_send_count",
        "cumulative_reserved_decimal",
    ):
        if before.get(field) != expected.get(field):
            raise RuntimeError("durable campaign differs from stopped checkpoint: " + field)
    if before["expires_at"] != checkpoint["original_expires_at"] or _api.datetime.now(
        _api.timezone.utc
    ) >= _api.datetime.strptime(before["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=_api.timezone.utc
    ):
        raise RuntimeError("original finite release window expired")
    self.operator_credentials = {"owner": "dev12.synthetic.operator." + "x" * 32}
    self.receiver = _api.subprocess.Popen(
        (
            _api.sys.executable,
            "-I",
            "-B",
            str(_api.HERE / "dev12_completion_receiver.py"),
            str(cert),
            str(key),
            str(self.receiver_log),
            str(self.receiver_port),
        ),
        cwd=_api.ROOT,
        stdout=_api.subprocess.DEVNULL,
        stderr=(self.root / "receiver.stderr").open("ab"),
    )
    self._wait_port(self.receiver, self.receiver_port)
    self.executor = Dev12SyntheticExecutor(worker, self.receiver_port, cert.read_text(), TEST_KEY)
    _api.os.environ["EZLLMROUTER_GATEWAY_GUARD_EVENTS"] = str(self.guard_log)

    def permitted(current, original):
        return (
            current["principal_id"] == original["work_key"]["principal_id"]
            and current["source_authority_id"]
            == original["trusted_identity"]["source_authority_id"]
            and current["identity_binding_id"]
            == original["trusted_identity"]["identity_binding_id"]
        )

    self.coordinator = Coordinator(
        self.store,
        identity=identities,
        config={},
        prompt_blocks={},
        allowed_lineages={},
        authority=None,
        adapter=None,
        retention={},
        classification={},
        recipe=None,
    )
    self.successor = attach_standalone_synthetic(
        self.coordinator,
        store=self.store,
        contexts_by_credential=self.contexts_by_credential,
        authority=self.authority,
        executor=self.executor,
        allowance=self.allowance,
        read_allowed=permitted,
        usage_write_allowed=permitted,
        receiver_receipts=DurableReceiverReceipts(self.root / "receiver-receipts.jsonl"),
    )
    arrivals_before = len(self.receiver_log.read_bytes().splitlines())
    self.successor.recover_incomplete()
    after = self.allowance.inspect()
    arrivals_after = len(self.receiver_log.read_bytes().splitlines())
    for field in (
        "start_at",
        "expires_at",
        "attempt_count",
        "possible_send_count",
        "cumulative_reserved_decimal",
    ):
        if after[field] != before[field]:
            raise RuntimeError("recovery changed finite campaign boundary: " + field)
    if arrivals_after != arrivals_before:
        raise RuntimeError("continuation recovery replayed receiver work")
    self.wire = serve("127.0.0.1", self.service_port, self.coordinator)
    _api.threading.Thread(target=self.wire.serve_forever, daemon=True).start()
    source = mounted_source_identity()
    if source != receipt["mounted_source_identity"]:
        raise RuntimeError("continued assembly differs from new host source receipt")
    self.operator = serve_operator(
        "0.0.0.0",
        self.operator_port,
        projection=OperatorProjection(
            self.store, "user.demo", str(self.root / "send-events.jsonl")
        ),
        runner=None,
        password=self.operator_credentials["owner"],
        fixture={"destination": {}, "policy": {}},
        build={"commit": "disposable.dev12", "dirty": False, "fingerprint": source["sha256"]},
        web_root=_api.ROOT / "web",
        worker_probe=lambda: {"state": "networkless"},
        sender_status=lambda: {"state": "controlled"},
        successor_store=self.store,
        registry=self.registry,
    )
    _api.threading.Thread(target=self.operator.serve_forever, daemon=True).start()
    self.started = True
    retained = {
        "kind": "continuation_released",
        "at": _api.time.time_ns(),
        "original_plan_sha256": checkpoint["original_plan_sha256"],
        "original_source_tree": checkpoint["original_source_tree"],
        "original_mounted_source": checkpoint["original_mounted_source"],
        "plan_sha256": receipt["plan_sha256"],
        "source_tree": self.plan["source_tree"],
        "mounted_source": source,
        "campaign_id": envelope["campaign_id"],
        "original_start_at": checkpoint["original_start_at"],
        "original_expires_at": checkpoint["original_expires_at"],
        "original_attempt_count": before["attempt_count"],
        "original_possible_send_count": before["possible_send_count"],
        "receiver_arrivals_before": arrivals_before,
        "receiver_arrivals_after": arrivals_after,
        "receiver": f"127.0.0.1:{self.receiver_port}",
        "service": self.base_url,
        "operator": self.operator_url,
        "worker_socket": str(worker),
        "service_network_mode": "bridge",
        "receiver_certificate": self.receiver_certificate,
        "synthetic_ordinary_credential_rotated": False,
        "real_provider_calls": 0,
    }
    _api.append_durable(self.root / "release-identity.jsonl", retained)
    _api.append_durable(self.journal, retained)


def close(self):
    for server in (self.operator, self.wire):
        if server is not None:
            server.shutdown()
            server.server_close()
    if self.operator is not None:
        self.operator.operator_jobs.shutdown(wait=True)
    if self.coordinator is not None:
        self.coordinator.pool.shutdown(wait=True)
        self.coordinator.successor.pool.shutdown(wait=True)
    if self.receiver is not None:
        self.receiver.terminate()
        self.receiver.wait(timeout=5)
    if self.store is not None:
        self.store.close()


def restart_service(self) -> dict:
    """Reopen the same SQLite campaign and recover without invoking any send.

    The receiver and isolated worker remain live. The old Coordinator and
    operator listeners are closed before any store object is replaced.
    The durable campaign row is read, never started or reseeded again.
    """
    from tools.gateway.evidence import dev12_completion_runner as _api

    if not self.started or self.executor.first_write_wait is not None:
        raise RuntimeError("service restart requires quiescent live assembly")
    from cryptography.hazmat.primitives import serialization
    from ezllmrouter_server.core import Coordinator
    from ezllmrouter_server.operator_projection import OperatorProjection
    from ezllmrouter_server.operator_web import serve as serve_operator
    from ezllmrouter_server.registry import Registry
    from ezllmrouter_server.store import SQLiteStore
    from tools.synthetic.successor_assembly import attach_standalone_synthetic
    from tools.synthetic.successor_authority import SyntheticSuccessorAuthority
    from tools.synthetic.successor_campaign import FiniteSuccessorCampaign
    from tools.synthetic.successor_receiver_evidence import DurableReceiverReceipts
    from ezllmrouter_server.web import serve
    import sqlite3

    before = self.allowance.inspect()
    arrivals_before = len(self.receiver_log.read_bytes().splitlines())
    _api.append_durable(
        self.journal,
        {
            "kind": "service_restart_begin",
            "at": _api.time.time_ns(),
            "campaign": before,
            "receiver_arrivals": arrivals_before,
        },
    )
    for listener in (self.operator, self.wire):
        listener.shutdown()
        listener.server_close()
    self.operator.operator_jobs.shutdown(wait=True)
    self.coordinator.pool.shutdown(wait=True)
    self.successor.pool.shutdown(wait=True)
    self.store.close()

    with sqlite3.connect(self.root / "campaign.sqlite") as db:
        state_row = db.execute(
            "SELECT state FROM dev12_authority WHERE authority_id='standalone.synthetic'"
        ).fetchone()
    if state_row is None:
        raise RuntimeError("durable authority missing on same-campaign restart")
    active = _api.json.loads(state_row[0])["active_minting_key"]
    version = active["key_version"]
    signer_path = (
        self.root / "signing-key.pem"
        if version == "v1"
        else self.root / ("signing-key-" + version + ".pem")
    )
    if not signer_path.is_file() or signer_path.is_symlink():
        raise RuntimeError("durable active signer unavailable on restart")
    signer = serialization.load_pem_private_key(signer_path.read_bytes(), password=None)
    self.store = SQLiteStore(self.root / "campaign.sqlite")
    self.authority = SyntheticSuccessorAuthority(self.store, signer, active["key_id"], version)
    direct = self.contexts_by_credential[self.credentials["DIRECT_DOCUMENT"]]["identity"]
    self.registry = Registry(
        self.store,
        self.authority,
        legacy_destination={
            "configuration_ref": "cfg.synthetic.dev12.operator",
            "service": "controlled.synthetic",
            "endpoint": "127.0.0.1",
            "model": "model.demo",
            "model_version": "synthetic-v1",
            "processing_region": "local",
        },
        legacy_token=self.credentials["DIRECT_DOCUMENT"],
        legacy_trusted=direct,
    )
    envelope = self.plan["envelope"]
    self.allowance = FiniteSuccessorCampaign(
        self.store,
        envelope["campaign_id"],
        envelope["budget_account_id"],
        financial_owner_id=envelope["financial_owner_id"],
    )
    if (
        self.allowance.inspect()["start_at"] != before["start_at"]
        or self.allowance.inspect()["attempt_count"] != before["attempt_count"]
    ):
        raise RuntimeError("same-campaign durable row changed during restart")

    def permitted(current, original):
        return (
            current["principal_id"] == original["work_key"]["principal_id"]
            and current["source_authority_id"]
            == original["trusted_identity"]["source_authority_id"]
            and current["identity_binding_id"]
            == original["trusted_identity"]["identity_binding_id"]
        )

    identities = {
        token: {
            **context["identity"],
            "task_id": context["request"]["work_selector"]["task_id"]
            if "request" in context
            else None,
            "expires_at": context["expires_at"],
        }
        for token, context in self.contexts_by_credential.items()
    }
    # _bind_contexts uses the immutable fixed A1 vectors for task binding.
    from tools.gateway.evidence.dev12_integrated import fixture

    for vector_id, token in self.credentials.items():
        identities[token]["task_id"] = fixture(vector_id)[0]["work_selector"]["task_id"]
    self.coordinator = Coordinator(
        self.store,
        identity=identities,
        config={},
        prompt_blocks={},
        allowed_lineages={},
        authority=None,
        adapter=None,
        retention={},
        classification={},
        recipe=None,
    )
    self.successor = attach_standalone_synthetic(
        self.coordinator,
        store=self.store,
        contexts_by_credential=self.contexts_by_credential,
        authority=self.authority,
        executor=self.executor,
        allowance=self.allowance,
        read_allowed=permitted,
        usage_write_allowed=permitted,
        receiver_receipts=DurableReceiverReceipts(self.root / "receiver-receipts.jsonl"),
    )
    self.successor.recover_incomplete()
    self.wire = serve("127.0.0.1", self.service_port, self.coordinator)
    _api.threading.Thread(target=self.wire.serve_forever, daemon=True).start()
    from tools.gateway.evidence.dev12_completion_preflight import mounted_source_identity

    self.operator = serve_operator(
        "0.0.0.0",
        self.operator_port,
        projection=OperatorProjection(
            self.store, "user.demo", str(self.root / "send-events.jsonl")
        ),
        runner=None,
        password=self.operator_credentials["owner"],
        fixture={"destination": {}, "policy": {}},
        build={
            "commit": "disposable.dev12",
            "dirty": False,
            "fingerprint": mounted_source_identity()["sha256"],
        },
        web_root=_api.ROOT / "web",
        worker_probe=lambda: {"state": "networkless"},
        sender_status=lambda: {"state": "controlled"},
        successor_store=self.store,
        registry=self.registry,
    )
    _api.threading.Thread(target=self.operator.serve_forever, daemon=True).start()
    after = self.allowance.inspect()
    arrivals_after = len(self.receiver_log.read_bytes().splitlines())
    if (
        arrivals_after != arrivals_before
        or after["start_at"] != before["start_at"]
        or after["possible_send_count"] != before["possible_send_count"]
    ):
        raise AssertionError("service recovery changed receiver or send campaign identity")
    result = {
        "campaign_before": before,
        "campaign_after": after,
        "receiver_arrivals_before": arrivals_before,
        "receiver_arrivals_after": arrivals_after,
        "authority_key_version": version,
    }
    _api.append_durable(
        self.journal, {"kind": "service_restart_end", "at": _api.time.time_ns(), **result}
    )
    return result
