"""Profile findings stay blocked when any exact evidence or precondition changes."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.security_profile import (
    CASES,
    CONTROLS,
    HARNESSES,
    apply_reviews,
    load_policy,
    proof_valid,
    sources,
)
from tools.security_resolutions import canonical
from tools.security_elf import application_closure
from tools.security_profile_conditions import valid as condition_valid
from tools.security_profile_capture import node_report


class ProfileReviewTests(unittest.TestCase):
    def test_node_diagnostic_rejects_unreviewed_startup_before_execution(self):
        image = "sha256:" + "a" * 64
        configuration = {
            "Id": image,
            "Config": {"Env": [], "Entrypoint": ["docker-entrypoint.sh"], "Cmd": ["node"]},
        }
        for change in ("identity", "options", "entrypoint"):
            actual = deepcopy(configuration)
            if change == "identity":
                actual["Id"] = "sha256:" + "b" * 64
            elif change == "options":
                actual["Config"]["Env"] = ["NODE_OPTIONS=--require=/unreviewed.js"]
            else:
                actual["Config"]["Entrypoint"] = ["/unreviewed-entrypoint"]
            with (
                self.subTest(change=change),
                patch("tools.security_profile_capture.subprocess.check_output") as execute,
            ):
                with self.assertRaises(ValueError):
                    node_report(image, actual)
                execute.assert_not_called()

    def native_proof(self, imports=(), dependency=None):
        proof = self.proof()
        objects = {
            "/app/actor": {
                "imports": list(imports),
                "exports": [],
                "needed": [dependency] if dependency else [],
                "soname": None,
            }
        }
        if dependency:
            objects["/usr/lib/" + dependency] = {
                "imports": [],
                "exports": [],
                "needed": [],
                "soname": dependency,
            }
        proof.update(elf_objects=objects, elf_sha256=canonical(objects))
        proof["closure"] = application_closure(objects)
        proof["closure_sha256"] = canonical(proof["closure"])
        return proof

    def test_full_native_metadata_and_closure_cannot_be_forged_independently(self):
        expected = self.native_proof()
        self.assertTrue(proof_valid(expected, expected))
        changed = deepcopy(expected)
        changed["elf_objects"]["/app/actor"]["imports"] = ["swscanf"]
        self.assertFalse(proof_valid(changed, expected))
        changed = deepcopy(expected)
        changed["closure"]["objects"] = []
        self.assertFalse(proof_valid(changed, expected))

    def test_additional_reviews_require_full_metadata_and_absent_affected_callers(self):
        cases = (
            ("DEBIAN-CVE-2026-115819", ("swscanf",), None),
            ("DEBIAN-CVE-2026-115456", ("_ZSt10from_chars",), None),
            ("DEBIAN-CVE-2026-121481", ("EVP_EncodeBlock",), None),
            ("DEBIAN-CVE-2025-6141", ("_nc_parse_entry",), None),
            ("DEBIAN-CVE-2025-6141", (), "libtic.so.6"),
            ("DEBIAN-CVE-2026-15059", (), "libsystemd.so.0"),
        )
        for identifier, imports, dependency in cases:
            with self.subTest(identifier=identifier, dependency=dependency):
                self.assertFalse(condition_valid(identifier, {"worker": self.proof()}))
                self.assertTrue(condition_valid(identifier, {"worker": self.native_proof()}))
                self.assertFalse(
                    condition_valid(identifier, {"worker": self.native_proof(imports, dependency)})
                )

    def test_node_file_stream_review_rejects_enabled_reports_or_other_code(self):
        proof = self.native_proof(("_ZNSt13basic_filebufIcEEC1Ev",))
        proof["elf_objects"]["/usr/local/bin/node"] = proof["elf_objects"].pop("/app/actor")
        proof["closure"] = application_closure(proof["elf_objects"])
        proof["elf_sha256"] = canonical(proof["elf_objects"])
        proof["node_report"] = {
            "fatal": False,
            "signal": False,
            "exception": False,
            "node_options": "",
            "command": ["node", "-e", "setInterval(()=>{},3600000)"],
            "entrypoint": ["docker-entrypoint.sh"],
        }
        identifier = "DEBIAN-CVE-2026-125709"
        self.assertTrue(condition_valid(identifier, {"js": proof}))
        for change in ("fatal", "signal", "exception", "code", "flags", "missing"):
            actual = deepcopy(proof)
            report = actual["node_report"]
            if change in {"fatal", "signal", "exception"}:
                report[change] = True
            elif change == "code":
                report["command"] = ["node", "-e", "process.report.writeReport()"]
            elif change == "flags":
                report["node_options"] = "--report-on-fatalerror"
            else:
                actual.pop("node_report")
            with self.subTest(change=change):
                self.assertFalse(condition_valid(identifier, {"js": actual}))

    def proof(self):
        return {
            "image": "sha256:" + "a" * 64,
            "elf_sha256": "b" * 64,
            "closure_sha256": "c" * 64,
            "closure": {"restricted_callers": {}, "quic_callers": {}},
            "unordered_load_objects": [],
            "runtime": {
                "uid": 10001,
                "euid": 10001,
                "no_new_privs": 1,
                "guard_global": True,
                "guard_outside_thread_stack": True,
                "guard_readonly": True,
                "locale": "C.UTF-8",
            },
        }

    def test_native_caller_wrong_architecture_locale_privileges_and_code_changes_fail(self):
        expected = self.proof()
        self.assertTrue(proof_valid(expected, expected))
        for change in (
            "caller",
            "quic",
            "segments",
            "locale",
            "uid",
            "nnp",
            "tls_guard",
            "writable",
            "code",
        ):
            proof = self.proof()
            if change == "caller":
                proof["closure"]["restricted_callers"] = {"/unexpected/lib.so": ["regexec"]}
            elif change == "quic":
                proof["closure"]["quic_callers"] = {"/unexpected/lib.so": ["SSL_accept_stream"]}
            elif change == "segments":
                proof["unordered_load_objects"] = ["/unexpected/lib.so"]
            elif change == "locale":
                proof["runtime"]["locale"] = "en_US.UTF-8"
            elif change == "uid":
                proof["runtime"]["euid"] = 0
            elif change == "nnp":
                proof["runtime"]["no_new_privs"] = 0
            elif change == "tls_guard":
                proof["runtime"]["guard_outside_thread_stack"] = False
            elif change == "writable":
                proof["runtime"]["guard_readonly"] = False
            else:
                proof["elf_sha256"] = "0" * 64
            with self.subTest(change=change):
                self.assertFalse(proof_valid(proof, expected))

    def data(self):
        proof = self.proof()
        identifier = "DEBIAN-CVE-2018-20796"
        advisory = {"id": identifier, "summary": "synthetic native regex case"}
        source = "image:worker:" + proof["image"]
        return (
            {
                "decisions": [
                    {
                        "id": identifier,
                        "state": "under_investigation",
                        "effective_blocking": True,
                        "raw_blocking": True,
                        "package": {
                            "ecosystem": "Debian:13",
                            "name": "glibc",
                            "version": "2.41-review",
                            "sources": [source],
                        },
                        "targets": {source: {"state": "under_investigation"}},
                    }
                ],
                "limits": [],
            },
            {"vulnerabilities": {identifier: advisory}},
            {"worker": {"image": {"id": proof["image"]}}},
            {"worker": proof},
            {
                "images": {"worker": deepcopy(proof)},
                "reviews": {
                    identifier: {
                        "source_version": "2.41-review",
                        "advisory_sha256": canonical(advisory),
                        "reason": "Synthetic qualified profile precondition is false",
                    }
                },
            },
        )

    def test_profile_resolution_preserves_raw_finding_and_changed_advisory_or_image_blocks(self):
        data = self.data()
        result = apply_reviews(*deepcopy(data))
        self.assertEqual(result["effective_blocking"], 0)
        self.assertTrue(result["decisions"][0]["raw_blocking"])
        self.assertEqual(result["decisions"][0]["state"], "not_affected")
        for change in ("advisory", "image", "missing", "source", "version"):
            report, snapshot, images, proofs, policy = deepcopy(data)
            if change == "advisory":
                next(iter(snapshot["vulnerabilities"].values()))["new_fact"] = True
            elif change == "image":
                proofs["worker"]["image"] = "sha256:" + "0" * 64
            elif change == "missing":
                proofs.clear()
            elif change == "source":
                report["decisions"][0]["package"]["sources"].append("unreviewed-source")
            else:
                report["decisions"][0]["package"]["version"] = "unreviewed-version"
            with self.subTest(change=change):
                self.assertEqual(
                    apply_reviews(report, snapshot, images, proofs, policy)["effective_blocking"], 1
                )

    def test_nonblocking_profile_review_requires_the_same_complete_proof(self):
        data = self.data()
        data[0]["decisions"][0].update(raw_blocking=False, effective_blocking=False)
        result = apply_reviews(*deepcopy(data))
        self.assertEqual(result["decisions"][0]["state"], "not_affected")
        self.assertEqual(result["resolved_profile_matches"], 1)
        self.assertFalse(result["decisions"][0]["raw_blocking"])
        for change in ("advisory", "caller", "archive", "empty_sources"):
            report, snapshot, images, proofs, policy = deepcopy(data)
            if change == "advisory":
                next(iter(snapshot["vulnerabilities"].values()))["changed"] = True
            elif change == "caller":
                proofs["worker"]["closure"]["restricted_callers"] = {"/app/lib.so": ["glob"]}
            elif change == "archive":
                from tools.gateway.os_inputs import LOCK

                report["decisions"][0]["package"]["sources"].append(LOCK)
            else:
                report["decisions"][0]["package"]["sources"].clear()
            with self.subTest(change=change):
                result = apply_reviews(report, snapshot, images, proofs, policy)
                self.assertEqual(result["decisions"][0]["state"], "under_investigation")
                self.assertEqual(result["resolved_profile_matches"], 0)
                self.assertEqual(result["effective_blocking"], 0)

    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in (
            *CONTROLS,
            *HARNESSES,
            "server/src/application.py",
            "worker/ezllmrouter_worker/main.py",
            "tools/security_profile_probe.c",
        ):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# synthetic source\n")
        now = datetime.now(timezone.utc)
        q = {
            "status": "passed",
            "cleanup_complete": True,
            "source_packet_sha256": "a" * 64,
            "images": {"role" + str(i): {"id": "sha256:" + str(i) * 64} for i in range(7)},
            "structure": {
                "service": {
                    "uid_gid": "10001:10001",
                    "readonly_root": True,
                    "locale": {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "LANGUAGE": "C"},
                }
            },
            "harness_sha256": {},
        }
        q["structure"] = {
            name: deepcopy(q["structure"]["service"])
            for name in ("ingress", "netns", "receiver", "service", "worker")
        }
        q["harness_sha256"] = {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in HARNESSES
        }
        policy = {
            "format": "ezllmrouter-profile-reviews-v1",
            "reviewed_at": now.isoformat(),
            "expires_at": (now + timedelta(days=7)).isoformat(),
            "source_sha256": sources(root),
            "qualification_sha256": canonical(q),
            "source_packet_sha256": q["source_packet_sha256"],
            "images": {name: {"image": image["id"]} for name, image in q["images"].items()},
            "probe_source_sha256": hashlib.sha256(
                (root / "tools/security_profile_probe.c").read_bytes()
            ).hexdigest(),
            "reviews": {
                identifier: {
                    "condition": condition,
                    "reason": "Synthetic bounded precondition review",
                    "advisory_sha256": "b" * 64,
                    "cna_sha256": "c" * 64,
                }
                for identifier, (_source, condition) in CASES.items()
            },
        }
        return root, q, policy

    def test_expiry_changed_source_added_native_interface_and_qualification_changes_reject(self):
        for change in (None, "expiry", "source", "interface", "qualification", "incomplete"):
            root, q, policy = self.fixture()
            if change == "expiry":
                policy["expires_at"] = (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat()
            elif change == "source":
                (root / "server/src/application.py").write_text("# changed\n")
            elif change == "interface":
                (root / "server/src/application.py").write_text("import ctypes\n")
                policy["source_sha256"] = sources(root)
            elif change == "qualification":
                q["structure"]["service"]["uid_gid"] = "0:0"
                policy["qualification_sha256"] = canonical(q)
            elif change == "incomplete":
                q["structure"].clear()
                policy["qualification_sha256"] = canonical(q)
            path = root / "policy.json"
            path.write_text(json.dumps(policy))
            with self.subTest(change=change):
                if change is None:
                    self.assertEqual(load_policy(path, root, q), policy)
                else:
                    with self.assertRaises(ValueError):
                        load_policy(path, root, q)
