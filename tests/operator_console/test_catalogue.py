"""Researched catalogue import stays separate from synthetic dispatch and prices."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from duranki_server.catalogue import validate_catalogue
from duranki_server.registry import Registry, RegistryConflict
from duranki_server.store import SQLiteStore


SEED = json.loads((ROOT / "deploy/local/inputs/catalogue.json").read_text())
DEST = {"configuration_ref": "cfg.demo", "service": "litellm.dev04", "endpoint": "127.0.0.1",
        "model": "model.demo", "model_version": "v1", "processing_region": "local"}
TRUSTED = {"principal_id": "svc.demo", "charging_owner_id": "team.demo"}


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SQLiteStore(Path(self.temp.name) / "store.sqlite")
        self.addCleanup(self.store.close)
        self.authority = Authority()
        self.registry = Registry(self.store, self.authority, legacy_destination=DEST,
            legacy_token="test-catalogue-service-token-00000000000000", legacy_trusted=TRUSTED)
        self.sources = {source["id"]: source for source in SEED["sources"]}

    def request(self, entry, operation="op.catalogue.test"):
        return {"operation_id": operation, "action": "import_catalogue",
                "subject": "catalogue." + entry["catalogue_key"], "expected_revision": 0,
                "data": {"entry": entry, "sources": [self.sources[ref] for ref in entry["source_refs"]]}}

    def test_all_twelve_import_and_reimport_without_authority_or_accounting_change(self):
        self.store.create({"submission_id": "submission.old", "attempt_id": "attempt.old", "principal_id": "svc.demo",
                           "task_id": "task.demo", "work_key": {"principal_id": "svc.demo", "task_id": "task.demo"},
                           "work_digest": "sha256:old"})
        old = self.store.get("submission.old")
        grant = self.registry.grant("svc.demo", "cfg.demo")
        for index, entry in enumerate(SEED["models"]):
            request = self.request(entry, f"op.catalogue.{index}")
            self.registry.mutate("owner.local", request)
            self.assertEqual(self.registry.readiness(self.registry.model(request["subject"])), "not_connected")
            self.assertEqual(self.registry.explain("svc.demo", request["subject"], "execution", "class.demo")["allowed"], False)
            with self.assertRaises(Exception):
                self.registry.admit("svc.demo", request["subject"], "execution", "class.demo")
            self.assertEqual(self.registry.prices(request["subject"]), [])
            self.assertIsNone(self.registry.grant("svc.demo", request["subject"]))
        self.assertEqual(len([m for m in self.registry.list_models() if m.get("kind") == "real_catalogue"]), 12)
        version = self.registry.version()
        for index, entry in enumerate(SEED["models"]):
            request = self.request(entry, f"op.catalogue.reimport.{index}")
            self.registry.mutate("owner.local", request)
        self.assertEqual(self.registry.version(), version)
        self.assertEqual(self.registry.grant("svc.demo", "cfg.demo"), grant)
        self.assertEqual(self.store.get("submission.old"), old)
        self.assertEqual(len(self.registry.list_principals()), 2)

    def test_changed_seed_conflicts_and_revocation_cannot_be_resurrected(self):
        entry = SEED["models"][0]
        request = self.request(entry)
        self.registry.mutate("owner.local", request)
        subject = request["subject"]
        self.registry.mutate("owner.local", {"operation_id": "op.catalogue.revoke", "action": "model_state",
            "subject": subject, "expected_revision": 1,
            "data": {"status": "revoked", "reason": "Test"}})
        version = self.registry.version()
        self.registry.mutate("owner.local", self.request(entry, "op.catalogue.same"))
        self.assertEqual(self.registry.model(subject)["status"], "revoked")
        self.assertEqual(self.registry.version(), version)
        changed = json.loads(json.dumps(entry))
        changed["price_reference"]["bands"][0]["rates_usd_per_1000000_tokens"]["output"] = "21"
        with self.assertRaises(RegistryConflict):
            self.registry.mutate("owner.local", self.request(changed, "op.catalogue.changed"))
        with self.assertRaises(ValueError):
            self.registry.mutate("owner.local", {"operation_id": "op.catalogue.enable", "action": "model_state",
                "subject": subject, "expected_revision": 2,
                "data": {"status": "enabled", "reason": "Improper activation"}})
        with self.assertRaises(ValueError):
            self.registry.mutate("owner.local", {"operation_id": "op.catalogue.price", "action": "publish_price",
                "subject": subject, "expected_revision": 2,
                "data": {"price_version": "fake.v1", "currency": "USD",
                         "rates": {"input_uncached": "4", "output_text": "20"},
                         "source": "synthetic fixture", "usage_semantics_version": "synthetic.text.v1"}})

    def test_seed_conditions_and_non_executable_shape(self):
        by_key = {m["catalogue_key"]: m for m in SEED["models"]}
        for key, boundary in (("anthropic.claude-haiku-5-5", ("prompt_tokens_lte", "prompt_tokens_gt", 100000)),
                              ("openai.gpt-6.1-sol", ("input_tokens_lte", "input_tokens_gt", 272000))):
            bands = by_key[key]["price_reference"]["bands"]
            self.assertEqual((bands[0]["conditions"][boundary[0]], bands[1]["conditions"][boundary[1]]),
                             (boundary[2], boundary[2]))
        self.assertEqual([b["conditions"]["rate_period"] for b in by_key[
            "deepseek.deepseek-flash"]["price_reference"]["bands"]], ["peak", "off_peak"])
        self.assertEqual(by_key["google.gemini-4-argon"]["price_reference"]["bands"][0][
            "conditions"]["publisher_date_through"], "2026-11-30")
        record = validate_catalogue("catalogue." + SEED["models"][0]["catalogue_key"],
                                    self.request(SEED["models"][0])["data"])
        self.assertIsNone(record["destination"])
        malformed = self.request(json.loads(json.dumps(SEED["models"][0])))
        malformed["data"]["entry"]["duranki_registration"]["runtime_ready"] = True
        with self.assertRaises(ValueError):
            validate_catalogue(malformed["subject"], malformed["data"])

    def test_operator_price_snapshot_keeps_conditional_and_extra_rates(self):
        entry = next(m for m in SEED["models"] if m["catalogue_key"] == "openai.gpt-6.1-sol")
        request = self.request(entry)
        self.registry.mutate("owner.local", request)
        subject = request["subject"]
        old = self.registry.model(subject)["catalogue"]["price_reference"]
        bands = json.loads(json.dumps(old["bands"]))
        bands[0]["rates_usd_per_1000000_tokens"]["input_uncached"] = "99"
        result = self.registry.mutate("owner.local", {"operation_id": "op.operator.price",
            "action": "publish_reference_price", "subject": subject, "expected_revision": 1,
            "data": {"snapshot_id": "operator.test.v2", "source_title": "Operator test source",
                "source_url": "https://example.org/test-reference", "bands": bands}})["record"]
        updated = result["catalogue"]["price_reference"]
        self.assertEqual(updated["bands"][0]["rates_usd_per_1000000_tokens"]["input_uncached"], "99")
        self.assertEqual(updated["bands"][0]["rates_usd_per_1000000_tokens"]["cache_write_30m"],
                         old["bands"][0]["rates_usd_per_1000000_tokens"]["cache_write_30m"])
        self.assertEqual(updated["bands"][1]["calculation_basis"], old["bands"][1]["calculation_basis"])
        self.assertEqual(updated["bands"][1]["conditions"], old["bands"][1]["conditions"])
        self.assertIsNone(updated["verified_on"])
        self.assertEqual(result["reference_price_history"][0]["price"], old)
        self.assertEqual(result["original_research"]["price_reference"], old)
        with self.assertRaises(RegistryConflict):
            self.registry.mutate("owner.local", self.request(entry, "op.seed.reimport"))

    def test_local_settings_do_not_edit_publisher_facts_and_correction_is_server_identified(self):
        entry = SEED["models"][0]
        request = self.request(entry)
        self.registry.mutate("owner.local", request)
        subject = request["subject"]
        original = self.registry.model(subject)
        with self.assertRaises(ValueError):
            self.registry.mutate("owner.local", {"operation_id": "op.edit.publisher", "action": "edit_catalogue_model",
                "subject": subject, "expected_revision": 1,
                "data": {"display_name": "Alias", "notes": "Local note", "vendor": "Changed publisher"}})
        edited = self.registry.mutate("owner.local", {"operation_id": "op.edit.local", "action": "edit_catalogue_model",
            "subject": subject, "expected_revision": 1,
            "data": {"display_name": "Local alias", "notes": "Local note"}})["record"]
        self.assertEqual(edited["catalogue"]["vendor"], original["catalogue"]["vendor"])
        self.assertEqual(edited["catalogue"]["price_reference"], original["catalogue"]["price_reference"])
        self.assertEqual(edited["display_name"], "Local alias")
        self.assertEqual(edited["catalogue"]["notes"], ["Local note"])
        price = {"source_title": "Corrected source", "source_url": "https://example.org/corrected",
                 "bands": edited["catalogue"]["price_reference"]["bands"]}
        change = {"operation_id": "op.price.correction", "action": "correct_reference_price",
                  "subject": subject, "expected_revision": 2, "data": price}
        corrected = self.registry.mutate("owner.local", change)["record"]
        snapshot = corrected["catalogue"]["price_reference"]["snapshot_id"]
        self.assertTrue(snapshot.startswith("operator.corrected."))
        self.assertEqual(self.registry.mutate("owner.local", change)["record"]["catalogue"]["price_reference"]["snapshot_id"], snapshot)
        self.assertEqual(corrected["reference_price_history"][0]["price"], original["catalogue"]["price_reference"])
        history = self.registry.history(subject)
        self.assertEqual(history[0]["before"]["price_version"], original["price_version"])
        self.assertEqual(history[0]["after"]["price_version"], snapshot)
        self.assertNotIn("notes", history[0]["after"])


if __name__ == "__main__":
    unittest.main()
