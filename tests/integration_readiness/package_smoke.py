"""Fresh authenticated observation against the exact clean-installed service wheel."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from duranki_client import IntegrationClient

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = json.loads((ROOT / "tests/fixtures/contracts/integration-readiness-v1/examples.json").read_text())


def main():
    secrets = Path(sys.argv[1])
    dataset = {**EXAMPLES["dataset"], "dataset_id": "dataset.final.package.smoke",
               "ingest_principal_id": "svc.integration"}
    event = {**EXAMPLES["events"][0], "dataset_id": dataset["dataset_id"],
             "event_id": "event.final.package.smoke"}
    base = "http://127.0.0.1:48760"
    with IntegrationClient(base, (secrets / "admin.token").read_text().strip()) as admin, \
            IntegrationClient(base, (secrets / "ingest.token").read_text().strip()) as ingest:
        assert admin.create_dataset(dataset)["dataset_id"] == dataset["dataset_id"]
        first = ingest.submit_observation(event)
        assert first["membership_at_receipt"] == "pending_start"
        assert ingest.submit_observation(event) == first
        assert ingest.recover_receipt(dataset["dataset_id"], event["event_id"]) == first
        report = admin.report(dataset["dataset_id"])
        assert report["attempt_count"] == 0 and report["known_total_by_currency"] == {}
    print("final packaged service fresh authenticated observation PASS: one receipt, no charge")


if __name__ == "__main__":
    main()
