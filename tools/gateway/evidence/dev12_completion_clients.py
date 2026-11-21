"""dev12_completion_handlers clients domain; entry points remain on the facade."""

from __future__ import annotations


def _offline_command(runtime, label, command, *, env=None):
    from tools.gateway.evidence import dev12_completion_handlers as _api

    merged = _api.os.environ.copy()
    merged.update(env or {})
    process = _api.subprocess.run(
        command,
        cwd=_api.source_root(_api.__file__),
        env=merged,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    return {
        "label": label,
        "command": command,
        "exit": process.returncode,
        "stdout": process.stdout[-5000:],
        "stderr": process.stderr[-5000:],
    }


def client_contract(runtime, case):
    """Run exact unpacked Python/CommonJS artifacts against no-network goldens."""
    from tools.gateway.evidence import dev12_completion_handlers as _api

    scenario = case["scenario_id"]
    if case["variant"] != "composed" or scenario not in {"t47_a", "t47_b", "t47_c", "t47_d"}:
        raise NotImplementedError("client-contract branch not implemented")
    root = _api.source_root(_api.__file__)
    python = _api._offline_command(
        runtime,
        "installed-python-successor",
        [
            _api.sys.executable,
            "-I",
            "-B",
            str(root / "tests/development_slice/test_retrieval_client.py"),
        ],
        env={"DEV12_PY_CLIENT_TARGET": str(runtime.installed_python_root)},
    )
    js = _api._offline_command(
        runtime,
        "installed-commonjs-successor",
        ["/dev12-node", str(root / "tests/development_slice/test_retrieval_client.cjs")],
        env={"DEV12_JS_CLIENT_DIR": str(runtime.installed_js_root)},
    )
    source_schemas = (
        root / "tests/fixtures/contracts/dev12-successor-01/schemas.json"
    ).read_bytes()
    py_schemas = (
        runtime.installed_python_root / "ezllmrouter_client/retrieval_schemas.json"
    ).read_bytes()
    js_schemas = (runtime.installed_js_root / "retrieval_schemas.json").read_bytes()
    source_registry = (
        root / "tests/fixtures/contracts/dev12-successor-01/registrations.json"
    ).read_bytes()
    py_registry = (
        runtime.installed_python_root / "ezllmrouter_client/dev12_registrations.json"
    ).read_bytes()
    js_registry = (runtime.installed_js_root / "dev12_registrations.json").read_bytes()
    exact_assets = (
        source_schemas == py_schemas == js_schemas and source_registry == py_registry == js_registry
    )
    common = python["exit"] == 0 and js["exit"] == 0 and exact_assets
    runs = [python, js]
    live = {}
    if scenario == "t47_a":
        from ezllmrouter_client import EzLLMRouterClient
        import ezllmrouter_client

        installed_python = (
            _api.Path(ezllmrouter_client.__file__)
            .resolve()
            .is_relative_to(runtime.installed_python_root.resolve())
        )
        py_request = _api._case_request(runtime, case, "DIRECT_DOCUMENT")
        py_request["work_selector"]["step_id"] += ".wheel"
        live_before = _api._census(runtime)
        with EzLLMRouterClient(
            runtime.base_url, runtime.credentials["DIRECT_DOCUMENT"], timeout=12
        ) as installed:
            py_reply = installed.submit_embedding(py_request, {"wait_ms": 5000})
            py_status = installed.get_successor_status(
                {"submission_id": py_reply["handle"]["submission_id"]}
            )
        js_request = _api._retrieval_request(
            runtime, case, "DELEGATED_RERANK", "tarball", ["doc.js"]
        )
        js_input = runtime.root / "cases" / (case["id"] + "-js-private-input.json")
        js_input.parent.mkdir(exist_ok=True)
        private = {
            "package_path": str(runtime.installed_js_root),
            "base_url": runtime.base_url,
            "token": runtime.credentials["DELEGATED_RERANK"],
            "action": "submit",
            "request": js_request,
        }
        with js_input.open("xb") as stream:
            stream.write(
                (_api.json.dumps(private, sort_keys=True, ensure_ascii=True) + "\n").encode()
            )
        js_input.chmod(0o600)
        js_live = _api._offline_command(
            runtime,
            "installed-commonjs-live-target",
            [
                "/dev12-node",
                str(_api.Path(_api.__file__).with_name("dev12_completion_js_actor.cjs")),
                str(js_input),
            ],
        )
        runs.append(js_live)
        try:
            js_observed = _api.json.loads(js_live["stdout"].strip().splitlines()[-1])
        except (IndexError, ValueError):
            js_observed = {}
        live_after = _api._census(runtime)
        live = {
            "installed_python_source": str(_api.Path(ezllmrouter_client.__file__).resolve()),
            "python_reply": py_reply,
            "python_status": py_status,
            "commonjs_actor": js_live,
            "commonjs_observed": js_observed,
            "before": live_before,
            "after": live_after,
            "private_js_input_path": str(js_input),
        }
        py_live_ok = (
            installed_python
            and py_reply.get("state") == "completed"
            and py_status.get("submission_state") == "completed"
        )
        js_live_ok = (
            js_live["exit"] == 0
            and js_observed.get("reply", {}).get("state") == "completed"
            and js_observed.get("status", {}).get("submission_state") == "completed"
        )
        two_live = (
            live_after["receiver_arrivals"] == live_before["receiver_arrivals"] + 2
            and live_after["submissions"] == live_before["submissions"] + 2
            and js_observed.get("reply", {}).get("attempt_id") != py_reply.get("attempt_id")
        )
        checks = {
            "t47_a.python_defaults": (
                python["exit"] == 0 and "OK" in python["stderr"] and py_live_ok,
                "Exact unpacked Python wheel passed fixtures and submitted/statused one live controlled attempt",
            ),
            "t47_a.commonjs_defaults": (
                js["exit"] == 0 and '"status":"PASS"' in js["stdout"] and js_live_ok,
                "Exact unpacked CommonJS tarball passed fixtures and submitted/statused one live controlled attempt",
            ),
            "t47_a.parity": (
                common and two_live,
                "Both installed artifacts used exact schema bytes and distinct guarded live target attempts",
            ),
        }
    elif scenario == "t47_b":
        py_a1 = _api._offline_command(
            runtime,
            "independent-a1-python",
            [
                _api.sys.executable,
                "-I",
                "-B",
                str(root / "tests/fixtures/contracts/dev12-successor-01/conformance/check.py"),
            ],
        )
        js_a1 = _api._offline_command(
            runtime,
            "a1-javascript-conformance",
            [
                "/dev12-node",
                str(root / "tests/fixtures/contracts/dev12-successor-01/conformance/check.cjs"),
            ],
        )
        runs.extend((py_a1, js_a1))
        checks = {
            "t47_b.domain_goldens": (
                py_a1["exit"] == 0
                and js_a1["exit"] == 0
                and "offline cross-check PASS" in py_a1["stdout"],
                "Independent Python projection and JavaScript conformance pass adopted domain-separated goldens",
            ),
            "t47_b.order_sensitive": (
                common and py_a1["exit"] == 0 and js_a1["exit"] == 0,
                "Strict client fixtures and A1 checker reject order-sensitive/canonical negatives",
            ),
        }
    elif scenario == "t47_c":
        legacy_js = _api._offline_command(
            runtime,
            "installed-commonjs-legacy",
            ["/dev12-node", str(root / "tests/development_slice/test_client.cjs")],
            env={
                "EZLLMROUTER_INSTALLED_CLIENT": "1",
                "NODE_PATH": str(runtime.installed_js_root.parents[1]),
            },
        )
        legacy_py = _api._offline_command(
            runtime,
            "legacy-python-contract",
            [_api.sys.executable, "-I", "-B", str(root / "tests/development_slice/test_core.py")],
        )
        legacy_http = _api._offline_command(
            runtime,
            "caller-owned-tool-cycle",
            [_api.sys.executable, "-I", "-B", str(root / "tests/development_slice/test_http.py")],
        )
        runs.extend((legacy_js, legacy_py, legacy_http))
        checks = {
            "t47_c.legacy_parser": (
                legacy_js["exit"] == 0 and legacy_py["exit"] == 0,
                "Installed CommonJS legacy parser and server strict parser controls pass",
            ),
            "t47_c.legacy_digest": (
                legacy_py["exit"] == 0,
                "Legacy canonical/domain_digest golden tests pass without rewriting bytes",
            ),
            "t47_c.caller_tool_cycle": (
                legacy_http["exit"] == 0
                and "OK" in legacy_http["stderr"]
                and legacy_js["exit"] == 0,
                "Legacy HTTP tool-result source/forgery scenario and installed client controls pass",
            ),
        }
    else:
        fixture = runtime.root / "cases" / "case.t47_a.composed.json"
        if not fixture.is_file() or fixture.is_symlink():
            raise AssertionError("retained installed-client positive response absent")
        commands = (
            (
                "wheel",
                [
                    _api.sys.executable,
                    "-I",
                    "-B",
                    str(root / "tools/gateway/evidence/dev12_completion_sdk_probe.py"),
                    str(runtime.installed_python_root),
                    str(fixture),
                ],
            ),
            (
                "tarball",
                [
                    "/dev12-node",
                    str(root / "tools/gateway/evidence/dev12_completion_sdk_probe.cjs"),
                    str(runtime.installed_js_root),
                    str(fixture),
                ],
            ),
        )
        probes = {}
        for label, command in commands:
            process = _api.subprocess.run(
                command, cwd=root, capture_output=True, text=True, timeout=30, check=False
            )
            if process.returncode or len(process.stdout) > 250000:
                raise AssertionError(f"{label} exact installed-client probe failed")
            probes[label] = _api.json.loads(process.stdout)
            runs.append(
                {
                    "label": f"installed-{label}-explicit-boundary",
                    "command": command,
                    "exit": process.returncode,
                    "stdout_sha256": _api.sha256(process.stdout.encode()).hexdigest(),
                    "stderr": process.stderr[-1000:],
                }
            )

        def paired(name):
            return all(
                {(row["case"], row["selector"]) for row in probes[label]["outcomes"]}
                == {
                    (kind, selector)
                    for kind in ("positive", "unknown_version", "unknown_field")
                    for selector in ("submission_id", "work_selector")
                }
                and all(
                    row["passed"]
                    and row["observed"] == row["expected"]
                    and _api.sha256(row["exact_body_utf8"].encode()).hexdigest()
                    == row["body_sha256"]
                    for row in probes[label]["outcomes"]
                    if row["case"] in (name, "positive")
                )
                for label in ("wheel", "tarball")
            )

        checks = {
            "t47_d.unknown_version": (
                common and paired("unknown_version"),
                "Both exact installed artifacts rejected explicit unknown-version responses through status",
            ),
            "t47_d.unknown_field": (
                common and paired("unknown_field"),
                "Both exact installed artifacts rejected an extra response field through status",
            ),
            "t47_d.strict_compatibility": (
                exact_assets and common and paired("positive"),
                "Both artifacts accepted positive immutable selectors with exact bounded schema bytes",
            ),
        }
        live = {"explicit_offline_probes": probes}
    return _api._evidence(
        runtime,
        case,
        {
            "client": {
                "python_exit": python["exit"],
                "commonjs_exit": js["exit"],
                "live_python_completed": live.get("python_status", {}).get(
                    "submission_state", "not_run"
                ),
                "live_commonjs_completed": live.get("commonjs_observed", {})
                .get("status", {})
                .get("submission_state", "not_run"),
                "schema_sha256": _api.sha256(source_schemas).hexdigest(),
                "registrations_sha256": _api.sha256(source_registry).hexdigest(),
            }
        },
        checks,
        {
            "offline_runs": runs,
            "exact_installed_assets": exact_assets,
            "live_target": live,
            "wheel_root": str(runtime.installed_python_root),
            "commonjs_root": str(runtime.installed_js_root),
        },
        live.get("python_reply", {}).get("attempt_id", case["attempt_group"]),
    )
