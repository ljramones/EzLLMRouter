#!/usr/bin/env python3
"""Disposable HTTP/Coordinator proof with offline-installed DEV-09 SDK packages."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(ROOT / "tests/operator_console"))

from ezllmrouter_server.reporting import usage_costs
from ezllmrouter_server.web import serve
from test_registry_core import RegistryCoordinatorTests, REQUEST, TOKEN


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: dev09_installed_proof.py INSTALLED_PYTHON_DIR INSTALLED_NODE_MODULES_DIR")
    python_dir, js_dir = map(lambda value: Path(value).resolve(), sys.argv[1:])
    result_path = ROOT / "docs/development/dev-09/INSTALLED-CLIENT-RESULT-01.json"
    if result_path.exists():
        raise SystemExit("installed-client result already exists; preserve the first proof")
    if not (python_dir / "ezllmrouter_client/__init__.py").is_file() or \
            not (js_dir / "@cognitivedynamics/ezllmrouter-client/index.cjs").is_file():
        raise SystemExit("both offline-installed SDK packages are required")
    fixture = RegistryCoordinatorTests("test_attributed_run_binds_signed_decision_and_rejects_reassignment")
    fixture.setUp()
    server = None
    try:
        registry = fixture.registry
        credentials = {}
        for index, user in enumerate(("user.alpha", "user.beta")):
            fixture.change(100 + index * 10, "create_principal", user, 0,
                {"display_name": "Synthetic " + user, "kind": "human", "owner": "team.demo"})
            _, credentials[user] = registry.provision_credential("owner.local", user, 1,
                "op.dev09.credential." + user)
            fixture.change(101 + index * 10, "principal_state", user, 2,
                {"status": "active", "reason": "Disposable SDK proof"})
            fixture.change(102 + index * 10, "set_grant", user, 0,
                {"configuration_ref": "cfg.demo", "status": "active", "purposes": ["execution"],
                 "task_classes": ["class.demo"]})
        fixture.change(130, "register_agent", "agent.synthetic", 0,
            {"display_name": "Synthetic shared agent", "owner": "team.demo", "versions": ["v1"]})
        for index, user in enumerate((None, "user.alpha", "user.beta")):
            data = {"caller_principal_id": "svc.demo", "agent_id": "agent.synthetic",
                    "charging_owner_id": "team.demo", "task_classes": ["class.demo"], "status": "active"}
            if user:
                data["initiating_user_id"] = user
            fixture.change(140 + index, "set_agent_permission", "permission.dev09." + str(index), 0, data)
        server = serve("127.0.0.1", 0, fixture.coordinator)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = "http://127.0.0.1:" + str(server.server_address[1])

        def row(name, mode, **fields):
            request = deepcopy(REQUEST)
            request["execution_generation"] = "gen.dev09." + name
            request["step_id"] = "step.dev09." + name
            run = {"version": "1", "run_id": "run.dev09." + name,
                   "task_id": request["task_id"], "task_class": request["task_class"],
                   "evaluation_ref": "rubric.synthetic.v1", "mode": mode, **fields}
            return {"run": run, "request": request}

        python_rows = [row("direct", "direct_human")]
        alpha = row("alpha", "user_delegated_agent", agent_id="agent.synthetic",
                    agent_version="v1", initiating_user_id="user.alpha")
        child = row("child", "nested_agent", agent_id="agent.synthetic", agent_version="v1",
                    parent_run_id="run.dev09.alpha")
        beta = row("beta", "user_delegated_agent", agent_id="agent.synthetic",
                   agent_version="v1", initiating_user_id="user.beta")
        auto = row("auto", "autonomous_agent", agent_id="agent.synthetic", agent_version="v1")
        common = dict(os.environ, PYTHONPATH=str(python_dir), NODE_PATH=str(js_dir))

        def actor(command, data):
            result = subprocess.run(command, input=json.dumps(data), text=True, capture_output=True,
                                    env=common, cwd=ROOT, timeout=30)
            if result.returncode:
                raise RuntimeError("installed actor failed: " + result.stderr[-1200:])
            return json.loads(result.stdout)

        direct = actor([sys.executable, str(ROOT / "tests/operator_console/dev09_python_actor.py")],
                       {"base_url": base_url, "token": credentials["user.alpha"], "rows": python_rows})
        alpha_result = actor([sys.executable, str(ROOT / "tests/operator_console/dev09_python_actor.py")],
            {"base_url": base_url, "token": TOKEN, "rows": [alpha], "outcome": {
                "version": "1", "event_id": "event.dev09.denied", "run_id": alpha["run"]["run_id"],
                "kind": "task_outcome", "subject_revision": 1, "verdict": "accepted",
                "evaluator_version": "rubric.synthetic.v1", "evidence_ref": "evidence.synthetic"}})
        node = "/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node"
        child_result = actor([node, str(ROOT / "tests/operator_console/dev09_js_actor.cjs")],
            {"base_url": base_url, "token": TOKEN, "rows": [child, beta, auto]})
        assert len(fixture.adapter.sent) == 5
        fixture.change(160, "create_principal", "svc.evaluator", 0,
            {"display_name": "Synthetic evaluator", "kind": "service", "owner": "team.demo"})
        _, evaluator_token = registry.provision_credential("owner.local", "svc.evaluator", 1,
            "op.dev09.credential.evaluator")
        fixture.change(161, "principal_state", "svc.evaluator", 2,
            {"status": "active", "reason": "Disposable evaluator"})
        fixture.change(162, "set_outcome_authority", "svc.evaluator", 0,
            {"status": "active", "task_classes": ["class.demo"]})
        accepted = {"version": "1", "event_id": "event.dev09.accepted", "run_id": alpha["run"]["run_id"],
            "kind": "task_outcome", "subject_revision": 1, "verdict": "accepted",
            "evaluator_version": "rubric.synthetic.v1", "evidence_ref": "evidence.synthetic.accepted"}
        outcome_py = actor([sys.executable, str(ROOT / "tests/operator_console/dev09_python_actor.py")],
            {"base_url": base_url, "token": evaluator_token, "rows": [], "outcome": accepted,
             "expect_outcome_authority": True})
        revised = {**accepted, "event_id": "event.dev09.revised", "subject_revision": 2,
                   "verdict": "rejected", "evidence_ref": "evidence.synthetic.revised"}
        outcome_js = actor([node, str(ROOT / "tests/operator_console/dev09_js_actor.cjs")],
            {"base_url": base_url, "token": evaluator_token, "rows": [], "outcome": revised})
        assert outcome_py["outcome"]["subject_revision"] == 1
        assert outcome_js["outcome"]["subject_revision"] == 2
        assert len(fixture.adapter.sent) == 5
        observed_states = [item["state"] for result in (direct, alpha_result, child_result)
                           for item in result["runs"]]
        assert all(state == "delivered" for state in observed_states), observed_states
        assert direct["package"].startswith(str(python_dir)) and \
               alpha_result["package"].startswith(str(python_dir)) and \
               child_result["package"].startswith(str(js_dir))
        scope = {"role": "registry_admin", "principal_id": "owner.local"}
        report = usage_costs(registry, scope)
        assert report["total"]["attempts"] == 5
        assert {item["agent_id"] for item in report["attempts"]} == \
               {"agent.synthetic", "__direct_human__"}
        assert {item["initiating_user_id"] for item in report["attempts"]} == \
               {"user.alpha", "user.beta", "__autonomous__"}
        scoped = usage_costs(registry, {"role": "ordinary", "principal_id": "user.alpha"})
        assert len(scoped["attempts"]) == 3
        assert all(item["initiating_user_id"] == "user.alpha" for item in scoped["attempts"])
        alpha_run = next(run for run in report["workflows"] if run["run_id"] == alpha["run"]["run_id"])
        assert alpha_run["outcome"]["verdict"] == "rejected"
        package_sources = {"python": python_dir / "ezllmrouter_client/__init__.py",
            "commonjs": js_dir / "@cognitivedynamics/ezllmrouter-client/index.cjs"}
        result = {"status": "PASS", "kind": "DEV-09 disposable installed SDK HTTP/Coordinator proof",
            "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
            "source_dirty": True, "installed_python": direct["version"], "installed_commonjs": "0.0.3",
            "packages": {name: {"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                         for name, path in package_sources.items()},
            "attempts": report["total"]["attempts"], "sends": len(fixture.adapter.sent),
            "alpha_visible": len(scoped["attempts"]),
            "outcome_revisions": [outcome_py["outcome"]["subject_revision"],
                                  outcome_js["outcome"]["subject_revision"]],
            "cost": report["total"], "real_provider_calls": 0,
            "boundary": "local component adapter; signed target plan and trusted owned sender require owner Docker run"}
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True))
    finally:
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        fixture.doCleanups()


if __name__ == "__main__":
    main()
