"""Component reviews cannot clear changed artifacts or partially inspected matches."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.security_resolutions import canonical, capture, evaluate, load_policy


class ComponentResolutionTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(Path("tools/security_component_reviews.json").read_text())
        review = self.policy["reviews"][0]
        self.advisory = {"id": review["id"], "severity": "HIGH", "synthetic": True}
        review["advisory_sha256"] = canonical(self.advisory)
        self.snapshot = {
            "queried_at": "2026-11-23T00:00:00Z",
            "vulnerabilities": {review["id"]: self.advisory},
        }
        self.images = {}
        self.captures = {}
        for name, digit in (("service", "1"), ("worker", "2")):
            identity = "sha256:" + digit * 64
            package = self.policy["packages"]["libuuid1"]
            self.images[name] = {
                "image": {"id": identity, "architecture": "arm64"},
                "os_packages": [
                    {
                        "binary": "libuuid1",
                        "binary_version": package["binary_version"],
                        "name": package["source"],
                        "version": package["source_version"],
                    }
                ],
            }
            self.captures[name] = {
                "image": identity,
                "component_inventory": {
                    "checked_basenames": ["mount", "umount"],
                    "checked_perl_paths": [],
                    "forbidden_components": [],
                },
                "packages": {
                    "libuuid1": {
                        key: package[key]
                        for key in ("binary_version", "source", "source_version", "code_set_sha256")
                    }
                },
            }
        self.issues = [
            {
                "id": review["id"],
                "blocking": True,
                "severity": "HIGH",
                "package": {
                    "ecosystem": review["ecosystem"],
                    "name": review["source"],
                    "version": review["source_version"],
                    "sources": [
                        "image:" + name + ":" + image["image"]["id"]
                        for name, image in self.images.items()
                    ],
                },
            }
        ]

    def result(self, archives=None):
        return evaluate(
            self.issues, self.snapshot, self.images, self.captures, self.policy, archives
        )

    def test_complete_review_clears_only_effective_gate_and_preserves_raw_findings(self):
        before = deepcopy(self.issues)
        result = self.result()
        self.assertEqual((result["raw_blocking"], result["effective_blocking"]), (1, 0))
        self.assertEqual(result["resolved_component_matches"], 1)
        self.assertEqual(self.issues, before)
        self.assertEqual(self.advisory["severity"], "HIGH")

    def test_changed_advisory_reopens_match(self):
        self.advisory["new_affected_interface"] = "uuid"
        self.assertEqual(self.result()["effective_blocking"], 1)

    def test_changed_package_version_gets_no_old_code_proof(self):
        image = self.images["worker"]
        image["os_packages"][0]["binary_version"] += "+changed"
        with patch(
            "tools.security_resolutions.subprocess.check_output",
            return_value="f\t755\t/usr/bin/find\0f\t755\t/usr/bin/dpkg-query\0",
        ) as command:
            proof = capture(image, self.policy)
        self.assertEqual(proof["packages"], {})
        self.assertEqual(command.call_count, 1)

    def test_partial_image_review_never_clears_global_match(self):
        self.captures["worker"]["packages"]["libuuid1"]["code_set_sha256"] = "0" * 64
        result = self.result()
        self.assertEqual(result["effective_blocking"], 1)
        self.assertEqual(result["decisions"][0]["targets"]["service"]["state"], "not_affected")
        self.assertEqual(
            result["decisions"][0]["targets"]["worker"]["state"], "under_investigation"
        )

    def test_sqlite_review_requires_extension_coverage_in_every_image(self):
        review = next(row for row in self.policy["reviews"] if row["id"] == "DEBIAN-CVE-2025-70873")
        advisory = {"id": review["id"], "synthetic": True}
        review["advisory_sha256"] = canonical(advisory)
        self.snapshot["vulnerabilities"][review["id"]] = advisory
        issue = self.issues[0]
        issue["id"] = review["id"]
        issue["package"].update(
            ecosystem=review["ecosystem"], name=review["source"], version=review["source_version"]
        )
        package = self.policy["packages"]["libsqlite3-0"]
        for role in self.images:
            self.images[role]["os_packages"] = [
                {
                    "binary": "libsqlite3-0",
                    "binary_version": package["binary_version"],
                    "name": package["source"],
                    "version": package["source_version"],
                }
            ]
            self.captures[role]["packages"] = {
                "libsqlite3-0": {
                    key: package[key]
                    for key in ("binary_version", "source", "source_version", "code_set_sha256")
                }
            }
            census = self.captures[role]["component_inventory"]
            census["checked_basenames"] = ["sqlite3"]
            census["checked_sqlite_extensions"] = ["zipfile.so", "sqlite3_zipfile.so"]
        self.assertEqual(self.result()["effective_blocking"], 0)
        self.captures["worker"]["component_inventory"].pop("checked_sqlite_extensions")
        self.assertEqual(self.result()["effective_blocking"], 1)
        self.captures["worker"]["component_inventory"]["checked_sqlite_extensions"] = [
            "zipfile.so",
            "sqlite3_zipfile.so",
        ]
        from tools.gateway.os_inputs import LOCK

        issue["package"]["sources"].append(LOCK)
        self.snapshot["inventory_sha256"] = "a" * 64
        archived = {
            "source": LOCK,
            "lock_sha256": "b" * 64,
            "inventory_sha256": "a" * 64,
            "packages": [
                {
                    "binary": "libsqlite3-0",
                    "ecosystem": "Debian:14",
                    **{
                        key: package[key]
                        for key in (
                            "binary_version",
                            "source",
                            "source_version",
                            "architecture",
                            "archive_sha256",
                        )
                    },
                }
            ],
        }
        self.assertEqual(self.result()["effective_blocking"], 1)
        self.assertEqual(self.result(archived)["effective_blocking"], 0)
        for change in ("inventory", "hash", "extra_binary"):
            proof = deepcopy(archived)
            with self.subTest(change=change):
                if change == "inventory":
                    proof["inventory_sha256"] = "c" * 64
                elif change == "hash":
                    proof["packages"][0]["archive_sha256"] = "c" * 64
                else:
                    proof["packages"].append(dict(proof["packages"][0], binary="sqlite3"))
                self.assertEqual(self.result(proof)["effective_blocking"], 1)

    def test_extra_binary_declared_source_and_reintroduced_components_reopen(self):
        original = (deepcopy(self.images), deepcopy(self.captures), deepcopy(self.issues))
        for change in (
            "binary",
            "source",
            "component",
            "coverage",
            "image",
            "version",
            "architecture",
        ):
            with self.subTest(change=change):
                self.images, self.captures, self.issues = deepcopy(original)
                proof = self.captures["worker"]
                if change == "binary":
                    self.images["worker"]["os_packages"].append(
                        dict(self.images["worker"]["os_packages"][0], binary="libmount1")
                    )
                elif change == "source":
                    self.issues[0]["package"]["sources"].append("uninspected:declared-input")
                elif change == "component":
                    proof["component_inventory"]["forbidden_components"] = ["/opt/copied/mount"]
                elif change == "coverage":
                    proof["component_inventory"]["checked_basenames"] = ["mount"]
                elif change == "image":
                    proof["image"] = "sha256:" + "3" * 64
                elif change == "version":
                    self.images["worker"]["os_packages"][0]["binary_version"] += "+changed"
                else:
                    self.images["worker"]["image"]["architecture"] = "amd64"
                self.assertEqual(self.result()["effective_blocking"], 1)

    def test_expired_future_and_overlong_reviews_rejected(self):
        now = datetime.now(timezone.utc)
        for start, end in (
            (now - timedelta(days=2), now - timedelta(days=1)),
            (now + timedelta(days=1), now + timedelta(days=2)),
            (now - timedelta(days=1), now + timedelta(days=8)),
        ):
            with self.subTest(start=start), tempfile.TemporaryDirectory() as directory:
                policy = deepcopy(self.policy)
                policy.update(reviewed_at=start.isoformat(), expires_at=end.isoformat())
                path = Path(directory) / "review.json"
                path.write_text(json.dumps(policy))
                with self.assertRaises(ValueError):
                    load_policy(path)

    def test_unsafe_paths_and_duplicate_reviews_rejected(self):
        for change in ("path", "duplicate", "unbound"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                policy = deepcopy(self.policy)
                now = datetime.now(timezone.utc)
                policy.update(
                    reviewed_at=(now - timedelta(hours=1)).isoformat(),
                    expires_at=(now + timedelta(hours=1)).isoformat(),
                )
                if change == "path":
                    policy["packages"]["libuuid1"]["code_files"] = ["/tmp/../etc/passwd"]
                elif change == "duplicate":
                    policy["reviews"].append(deepcopy(policy["reviews"][0]))
                else:
                    policy["reviews"][0]["allowed_binaries"] = ["unreviewed"]
                path = Path(directory) / "review.json"
                path.write_text(json.dumps(policy))
                with self.assertRaises(ValueError):
                    load_policy(path)
