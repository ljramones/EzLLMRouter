"""A patched system library cannot conceal an old bundled runtime copy."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from tools.gateway.os_inputs import LOCK
from tools.security_native import apply_reviews, capture
from tools.security_resolutions import canonical
from tools.security_dependencies import query, findings, query_versions


class NativeReviewTests(unittest.TestCase):
    def setUp(self):
        self.version = "3.5.9-1~deb13u1+ezllmrouter1"
        self.advisory = {"id": "DEBIAN-CVE-2026-95692", "severity": "HIGH"}
        self.snapshot = {
            "inventory_sha256": "a" * 64,
            "vulnerabilities": {self.advisory["id"]: self.advisory},
        }
        self.native = {
            "id": "b" * 64,
            "openssl_source_version": self.version,
            "openssl_version": "3.5.9+ezllmrouter1",
            "node": {"version": "24.22.3"},
            "cryptography": {"version": "50.0.2+ezllmrouter1"},
            "packages": {
                name: name + ".deb" for name in ("libssl3t64", "openssl-provider-legacy", "openssl")
            },
            "fixed_advisories": {
                self.advisory["id"]: {
                    "advisory_sha256": canonical(self.advisory),
                    "reason": "Synthetic exact backport review",
                }
            },
            "code": [{"path": "/reviewed/library.so", "role": "all", "sha256": "c" * 64}],
        }
        self.native["outputs"] = {
            filename: {"sha256": "d" * 64} for filename in self.native["packages"].values()
        }
        self.images = {
            role: {
                "image": {
                    "id": "sha256:" + digit * 64,
                    "base": "docker.io/library/"
                    + ("node" if role == "node" else "python")
                    + "@sha256:"
                    + "0" * 64,
                },
                "os_packages": [
                    {
                        "binary": name,
                        "binary_version": self.version,
                        "name": "openssl",
                        "version": self.version,
                    }
                    for name in self.native["packages"]
                    if role != "node" or name != "openssl"
                ],
                "application_packages": []
                if role == "node"
                else [{"name": "cryptography", "version": self.native["cryptography"]["version"]}],
            }
            for role, digit in (("service", "1"), ("node", "2"))
        }
        self.proofs = {
            role: {"valid": True, "image": value["image"]["id"], "native_build": self.native["id"]}
            for role, value in self.images.items()
        }
        sources = [
            "image:" + role + ":" + value["image"]["id"] for role, value in self.images.items()
        ] + [LOCK]
        decision = {
            "id": self.advisory["id"],
            "raw_blocking": True,
            "effective_blocking": True,
            "state": "under_investigation",
            "package": {
                "ecosystem": "Debian:13",
                "name": "openssl",
                "version": self.version,
                "sources": sources,
            },
            "targets": {source: {"state": "under_investigation"} for source in sources},
        }
        self.report = {
            "decisions": [decision],
            "archive_proof": {
                "inventory_sha256": "a" * 64,
                "packages": [
                    {
                        "source": "openssl",
                        "binary": name,
                        "binary_version": self.version,
                        "source_version": self.version,
                        "archive_sha256": "d" * 64,
                    }
                    for name in self.native["packages"]
                ],
            },
        }

    def result(self):
        return apply_reviews(self.report, self.snapshot, self.images, self.proofs, self.native)

    def test_complete_copy_and_archive_proofs_resolve_as_fixed(self):
        result = self.result()
        self.assertEqual(result["effective_blocking"], 0)
        self.assertEqual(result["resolved_native_matches"], 1)
        self.assertEqual(result["decisions"][0]["state"], "fixed")
        self.assertEqual(self.advisory["severity"], "HIGH")

    def test_any_unpatched_copy_changed_advisory_or_unbound_source_keeps_blocking(self):
        original = deepcopy((self.report, self.snapshot, self.proofs))
        for change in (
            "copy",
            "missing",
            "image",
            "build",
            "advisory",
            "archive",
            "source",
            "version",
        ):
            self.report, self.snapshot, self.proofs = deepcopy(original)
            with self.subTest(change=change):
                if change == "copy":
                    self.proofs["node"]["valid"] = False
                elif change == "missing":
                    self.proofs.pop("node")
                elif change == "image":
                    self.proofs["node"]["image"] = "sha256:" + "3" * 64
                elif change == "build":
                    self.proofs["node"]["native_build"] = "e" * 64
                elif change == "advisory":
                    self.snapshot["vulnerabilities"][self.advisory["id"]]["new_interface"] = (
                        "unknown"
                    )
                elif change == "archive":
                    self.report["archive_proof"]["packages"][0]["archive_sha256"] = "e" * 64
                elif change == "source":
                    self.report["decisions"][0]["package"]["sources"].append("unknown:declared")
                else:
                    self.report["decisions"][0]["package"]["version"] = "3.5.9-1~deb13u1"
                self.assertEqual(self.result()["effective_blocking"], 1)

    def test_code_match_does_not_clear_a_static_node_openssl_copy(self):
        hashes = "c" * 64 + "  /reviewed/library.so\0"
        for shared in (False, True):
            with (
                self.subTest(shared=shared),
                patch(
                    "tools.security_native.subprocess.check_output",
                    side_effect=[
                        hashes,
                        json.dumps(
                            {
                                "openssl": self.native["openssl_version"],
                                "shared": shared,
                                "node": "24.22.3",
                            }
                        ),
                    ],
                ),
            ):
                self.assertEqual(capture(self.images["node"], self.native)["valid"], shared)

    def test_code_match_does_not_clear_old_cryptography_backend(self):
        hashes = "c" * 64 + "  /reviewed/library.so\0"
        versions = {
            "openssl": "OpenSSL 3.5.9+ezllmrouter1 reviewed",
            "crypto_openssl": "OpenSSL 4.0.3 old bundled copy",
            "cryptography": self.native["cryptography"]["version"],
            "crypto_object_exists": True,
        }
        with patch(
            "tools.security_native.subprocess.check_output",
            side_effect=[hashes, json.dumps(versions)],
        ):
            self.assertFalse(capture(self.images["service"], self.native)["valid"])

    def test_runtime_without_crypto_requires_absence_of_both_module_and_native_object(self):
        image = self.images["service"]
        image["application_packages"] = []
        for present in (False, True):
            for installed in (False, True):
                versions = {
                    "openssl": "OpenSSL 3.5.9+ezllmrouter1 reviewed",
                    "cryptography": self.native["cryptography"]["version"] if installed else None,
                    "crypto_openssl": "OpenSSL 4.0.3 old" if installed else None,
                    "crypto_object_exists": present,
                }
                with (
                    self.subTest(object_present=present, module_present=installed),
                    patch(
                        "tools.security_native.subprocess.check_output",
                        side_effect=["c" * 64 + "  /reviewed/library.so\0", json.dumps(versions)],
                    ),
                ):
                    self.assertEqual(
                        capture(image, self.native)["valid"], not present and not installed
                    )

    def test_added_openssl_binary_keeps_runtime_unreviewed(self):
        self.images["node"]["os_packages"].append(
            {
                "binary": "openssl-provider-fips",
                "binary_version": self.version,
                "name": "openssl",
                "version": self.version,
            }
        )
        with patch(
            "tools.security_native.subprocess.check_output",
            side_effect=[
                "c" * 64 + "  /reviewed/library.so\0",
                json.dumps(
                    {"openssl": self.native["openssl_version"], "shared": True, "node": "24.22.3"}
                ),
            ],
        ):
            self.assertFalse(capture(self.images["node"], self.native)["valid"])


class NativeAdvisoryVersionTests(unittest.TestCase):
    def data(self):
        return {
            "sha256": "a" * 64,
            "packages": [
                {
                    "ecosystem": "PyPI",
                    "name": "cryptography",
                    "version": "50.0.2+ezllmrouter1",
                    "sources": ["synthetic-native-build"],
                }
            ],
            "advisory_versions": [
                {
                    "ecosystem": "PyPI",
                    "name": "cryptography",
                    "version": "50.0.2+ezllmrouter1",
                    "upstream_version": "50.0.2",
                    "native_build": "b" * 64,
                }
            ],
        }

    def test_local_labels_query_upstream_version_on_every_page_and_preserve_identity(self):
        data = self.data()
        calls = []

        def fetch(route, payload=None):
            calls.append((route, payload))
            if route == "querybatch":
                return {
                    "results": [
                        {"vulns": [{"id": "SYNTHETIC-NATIVE-1"}], "next_page_token": "next"}
                    ]
                }
            if route == "query":
                return {"vulns": []}
            return {"id": "SYNTHETIC-NATIVE-1", "database_specific": {"severity": "HIGH"}}

        snapshot = query(data, fetch)
        self.assertEqual(calls[0][1]["queries"][0]["version"], "50.0.2")
        self.assertEqual(calls[1][1]["version"], "50.0.2")
        issues = findings(data, snapshot)
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0]["blocking"])
        self.assertEqual(issues[0]["package"]["version"], "50.0.2+ezllmrouter1")
        snapshot["queried_versions"] = ["50.0.2+ezllmrouter1"]
        with self.assertRaises(ValueError):
            findings(data, snapshot)

    def test_unrelated_version_or_package_overrides_are_rejected(self):
        for change in ("version", "package", "duplicate"):
            data = self.data()
            with self.subTest(change=change):
                if change == "version":
                    data["advisory_versions"][0]["upstream_version"] = "1.0"
                elif change == "package":
                    data["advisory_versions"][0]["name"] = "unrelated"
                else:
                    data["advisory_versions"].append(deepcopy(data["advisory_versions"][0]))
                with self.assertRaises(ValueError):
                    query_versions(data)
