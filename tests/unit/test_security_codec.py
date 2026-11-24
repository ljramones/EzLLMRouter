"""The Zstandard finding stays blocking if either copy or compatibility proof changes."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.gateway import codec_inputs, os_inputs
from tools.security_codec import apply_reviews, expected_code, verify_runtime
from tools.security_dependencies import query_versions
from tools.security_resolutions import canonical

ROOT = Path(__file__).resolve().parents[2]


class CodecSecurityTests(unittest.TestCase):
    def test_node_version_and_old_system_copy_are_checked_even_with_matching_code(self):
        codec = os_inputs.load_lock(ROOT)["native_codec"]
        image = {
            "os_packages": [
                {
                    "name": "libzstd",
                    "binary": "libzstd1",
                    "version": codec_inputs.VERSION,
                    "binary_version": codec_inputs.VERSION,
                }
            ]
        }
        names = "libzstd.so.1\nlibzstd.so.1.6.0\n"
        for old_node, old_library in ((False, False), (True, False), (False, True)):
            with (
                self.subTest(node=old_node, library=old_library),
                patch(
                    "tools.security_codec.subprocess.check_output",
                    return_value=names + ("libzstd.so.1.5.7\n" if old_library else ""),
                ),
            ):
                result = verify_runtime(
                    [], codec, image, "node", {"zstd": "1.5.7" if old_node else "1.6.0"}
                )
                self.assertEqual(result, not old_node and not old_library)
        codes = expected_code(codec, "node")
        self.assertEqual(
            codes["/usr/lib/aarch64-linux-gnu/libzstd.so.1"], codes[codec_inputs.LIBRARY]
        )
        self.assertEqual(
            codes["/usr/local/bin/node"], codec["outputs"][codec_inputs.NODE]["sha256"]
        )

    def test_local_suffix_queries_upstream_instead_of_hiding_the_advisory(self):
        row = {
            "ecosystem": "Debian:13",
            "name": "libzstd",
            "version": codec_inputs.VERSION,
            "upstream_version": "1.6.0-0",
            "native_build": "a" * 64,
        }
        data = {"packages": [row], "advisory_versions": [row]}
        self.assertEqual(query_versions(data), ["1.6.0-0"])

    def test_only_exact_all_image_code_advisory_archive_and_compatibility_proofs_clear(self):
        original = os_inputs.load_lock(ROOT)["native_codec"]
        for change in (
            None,
            "code",
            "image",
            "missing",
            "advisory",
            "archive",
            "caller",
            "compatibility",
        ):
            codec = deepcopy(original)
            advisory = {"id": "DEBIAN-CVE-2026-124851", "details": "reviewed synthetic advisory"}
            codec["fixed_advisory"]["advisory_sha256"] = canonical(advisory)
            identity = "sha256:" + "b" * 64
            images = {"node": {"image": {"id": identity}}}
            captures = {"node": {"valid": True, "image": identity, "native_codec": codec["id"]}}
            source = "image:node:" + identity
            report = {
                "decisions": [
                    {
                        "id": advisory["id"],
                        "raw_blocking": True,
                        "effective_blocking": True,
                        "package": {
                            "ecosystem": "Debian:13",
                            "name": "libzstd",
                            "version": codec_inputs.VERSION,
                            "sources": [source, os_inputs.LOCK],
                        },
                        "targets": {source: {}},
                    }
                ],
                "profile_captures": {"node": {"image": identity, "zstd_removed_callers": {}}},
                "archive_proof": {
                    "inventory_sha256": "c" * 64,
                    "packages": [
                        {
                            "source": "libzstd",
                            "binary": "libzstd1",
                            "binary_version": codec_inputs.VERSION,
                            "source_version": codec_inputs.VERSION,
                            "archive_sha256": codec["outputs"][codec_inputs.PACKAGE]["sha256"],
                        }
                    ],
                },
            }
            if change == "code":
                captures["node"]["valid"] = False
            elif change == "image":
                captures["node"]["image"] = "sha256:" + "d" * 64
            elif change == "missing":
                captures.clear()
            elif change == "advisory":
                advisory["details"] = "changed target"
            elif change == "archive":
                report["archive_proof"]["packages"][0]["archive_sha256"] = "0" * 64
            elif change == "caller":
                report["profile_captures"]["node"]["zstd_removed_callers"] = {
                    "/unreviewed": ["ZSTD_copyDCtx"]
                }
            elif change == "compatibility":
                report["profile_captures"].clear()
            snapshot = {"inventory_sha256": "c" * 64, "vulnerabilities": {advisory["id"]: advisory}}
            with self.subTest(change=change):
                result = apply_reviews(report, snapshot, images, captures, codec)
                self.assertEqual(result["effective_blocking"], int(change is not None))
