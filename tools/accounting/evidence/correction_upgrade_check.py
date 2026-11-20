"""Read only check of copied v1 demonstration after additive 0.2.0 migration."""

import json
from pathlib import Path
import sys

from ezllmrouter_client import IntegrationClient, __version__

root = Path(sys.argv[1])
assert __version__ == "0.2.0" and "site-packages" in str(
    Path(sys.modules["ezllmrouter_client"].__file__).resolve()
)
token = (root / "secrets/admin.token").read_text().strip()
did = "dataset.local.vega.01"
with (
    IntegrationClient("http://127.0.0.1:48760", token, version="1") as legacy,
    IntegrationClient("http://127.0.0.1:48760", token, version="2") as current,
):
    v1 = legacy.report(did)
    v2 = current.report(did)
    assert v1["attempt_count"] == v2["attempt_count"] == 3
    assert v1["unknown_cost_attempts"] == v2["unknown_cost_attempts"] == 1
    assert v1["known_total_by_currency"] == v2["known_total_by_currency"] == {"USD": "0.055000000"}
    assert all(item["model_identity_state"] == "legacy_absent" for item in v2["attempts"])
    assert all(item["lineage_status"] == "legacy_absent" for item in v2["attempts"])
    assert current.export_dataset(did)["attempts"]
print(
    json.dumps(
        {
            "result": "PASS",
            "migrated_v1_attempts": 3,
            "known_usd": "0.055000000",
            "legacy_fields": "explicitly absent",
        },
        sort_keys=True,
    )
)
