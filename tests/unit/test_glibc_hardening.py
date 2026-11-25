"""Allocator decisions require controls, exact probes, all images and no override caller."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import security_glibc as glibc
from tools.security_profile_conditions import valid as condition_valid
from tools.security_resolutions import canonical


class GlibcHardeningTests(unittest.TestCase):
    def proof(self):
        return {
            "environment": {"GLIBC_TUNABLES": glibc.TUNABLES},
            "probe_sha256": "a" * 64,
            "sample": deepcopy(glibc.SAMPLE),
            "fallback": deepcopy(glibc.FALLBACK),
            "failure": deepcopy(glibc.FAILURE),
        }

    def test_missing_duplicated_changed_and_loader_override_controls_fail(self):
        entry = "GLIBC_TUNABLES=" + glibc.TUNABLES
        self.assertEqual(glibc.environment({"Env": [entry]}), {"GLIBC_TUNABLES": glibc.TUNABLES})
        for entries in (
            [],
            [entry, entry],
            ["GLIBC_TUNABLES"],
            [entry + ":glibc.malloc.arena_max=2"],
            [entry, "LD_PRELOAD=/tmp/allocator.so"],
            [entry, "LD_AUDIT=/tmp/audit.so"],
        ):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                glibc.environment({"Env": entries})

    def test_every_allocator_invariant_and_result_type_is_required(self):
        self.assertTrue(glibc.valid(self.proof()))
        for field, value in (
            ("arenas", 2),
            ("stacks_retained", 1),
            ("thread_allocations_in_brk_heap", 7),
            ("integrity", 1),
            ("threads", 1),
        ):
            proof = self.proof()
            proof["sample"][field] = value
            self.assertFalse(glibc.valid(proof), field)
        for section in ("sample", "fallback", "failure"):
            proof = self.proof()
            proof[section].clear()
            self.assertFalse(glibc.valid(proof), section)

    def test_unreviewed_probe_and_changed_environment_fail_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            probe = Path(temporary) / "probe"
            probe.write_bytes(b"public synthetic executable fixture")
            digest = hashlib.sha256(probe.read_bytes()).hexdigest()
            for expected, entries in (
                ("0" * 64, ["GLIBC_TUNABLES=" + glibc.TUNABLES]),
                (digest, []),
            ):
                with patch("tools.security_glibc.subprocess.check_output") as execute:
                    with self.assertRaises(ValueError):
                        glibc.capture(
                            "sha256:" + "a" * 64, {"Env": entries}, "10001:10001", probe, expected
                        )
                    execute.assert_not_called()

    def test_capture_keeps_stable_proof_and_checks_failure_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            probe = Path(temporary) / "probe"
            probe.write_bytes(b"public synthetic executable fixture")
            digest = hashlib.sha256(probe.read_bytes()).hexdigest()
            outputs = [
                dict(glibc.SAMPLE, libc_base=123, seconds=0.01),
                glibc.FALLBACK,
                glibc.FAILURE,
            ]
            with patch(
                "tools.security_glibc.subprocess.check_output",
                side_effect=[json.dumps(x) for x in outputs],
            ) as execute:
                proof = glibc.capture(
                    "sha256:" + "a" * 64,
                    {"Env": ["GLIBC_TUNABLES=" + glibc.TUNABLES]},
                    "10001:10001",
                    probe,
                    digest,
                )
            self.assertTrue(glibc.valid(proof))
            self.assertNotIn("libc_base", proof["sample"])
            self.assertEqual(execute.call_count, 3)
            for call in execute.call_args_list:
                self.assertIn("--network=none", call.args[0])
                self.assertIn("--read-only", call.args[0])
                self.assertIn("--entrypoint=/probe", call.args[0])

    def test_single_arena_review_rejects_missing_image_proof_and_override_caller(self):
        objects = {"/app/actor": {"imports": []}}
        proof = {
            "elf_objects": objects,
            "elf_sha256": canonical(objects),
            "closure": {"objects": ["/app/actor"]},
            "allocator": self.proof(),
        }
        identifier = "DEBIAN-CVE-2019-1010025"
        self.assertTrue(condition_valid(identifier, {"service": proof}))
        for change in ("missing", "mallopt", "dlmopen", "arenas"):
            changed = deepcopy(proof)
            if change == "missing":
                changed.pop("allocator")
            elif change == "arenas":
                changed["allocator"]["sample"]["arenas"] = 2
            else:
                changed["elf_objects"]["/outside/optional.so"] = {"imports": [change]}
                changed["elf_sha256"] = canonical(changed["elf_objects"])
            self.assertFalse(
                condition_valid(identifier, {"service": proof, "worker": changed}), change
            )
