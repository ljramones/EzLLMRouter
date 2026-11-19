"""Read-only installed-client check of copied v1 and v2 accounting history."""
import json
from pathlib import Path
import sys

from ezllmrouter_client import IntegrationClient, __version__


def main():
    root = Path(sys.argv[1]).resolve()
    base = sys.argv[2]
    generation = sys.argv[3]
    assert __version__ == "0.2.1" and "site-packages" in str(Path(sys.modules["ezllmrouter_client"].__file__).resolve())
    assert generation in {"v1", "v2"}
    dataset = "dataset.local.vega.01" if generation == "v1" else "dataset.integration.correction.v2"
    expected = "0.055000000" if generation == "v1" else "0.030000000"
    token = (root / "secrets/admin.token").read_text().strip()
    with IntegrationClient(base, token, version="2") as client:
        report = client.report(dataset)
        export = client.export_dataset(dataset)
        assert report["attempt_count"] == len(export["attempts"]) == 3
        assert report["unknown_cost_attempts"] == 1
        assert report["known_total_by_currency"] == {"USD": expected}
        assert all(row["usage_state"] in {"known", "unknown", "not_observed", "legacy_absent"}
                   for row in report["attempts"])
        if generation == "v1":
            assert all(row["usage_state"] == "legacy_absent" for row in report["attempts"])
            assert all(row["lineage_status"] == "legacy_absent" for row in report["attempts"])
            with IntegrationClient(base, token, version="1") as legacy:
                assert legacy.report(dataset)["known_total_by_currency"] == {"USD": expected}
        else:
            assert any(row["usage_state"] == "unknown" for row in report["attempts"])
            assert "snapshot_reference_assessments" in export
            assert "eligibility_assessments" in export
    print(json.dumps({"result": "PASS", "retained_generation": generation,
                      "attempt_count": 3, "known_usd": expected, "unknown_cost_attempts": 1}, sort_keys=True))


if __name__ == "__main__":
    main()
