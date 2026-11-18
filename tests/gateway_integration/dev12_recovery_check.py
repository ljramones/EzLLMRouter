"""No-replay restart and paused-scope admission check over the same campaign."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))

from cryptography.hazmat.primitives import serialization
from duranki_server.canonical import ContractError
from duranki_server.store import SQLiteStore
from duranki_server.successor_authority import SyntheticSuccessorAuthority
from duranki_server.successor_campaign import FiniteSuccessorCampaign
from duranki_server.successor_service import SuccessorService


class NeverExecute:
    def execute(self, *_args):
        raise AssertionError("recovery or paused admission executed work")


def run():
    root = Path(os.environ["DEV12_TARGET_DIR"])
    inventory = json.loads((root / "inventory.json").read_text())
    store = SQLiteStore(root / "campaign.sqlite")
    signer = serialization.load_pem_private_key((root / "signing-key.pem").read_bytes(), password=None)
    authority = SyntheticSuccessorAuthority(store, signer, "key.synthetic.dev12", "v1")
    campaign = FiniteSuccessorCampaign(store, inventory["campaign_id"],
        inventory["budget_account_id"], financial_owner_id=inventory["financial_owner_id"])
    row = store.db.execute("SELECT record FROM dev12_submissions WHERE "
                           "json_extract(record,'$.work_key.step_id')='step.control.unknown'").fetchone()
    record = json.loads(row[0])
    context = record["trusted_context"]
    trusted = {**context["identity"], "task_id": record["work_key"]["task_id"],
               "expires_at": context["expires_at"]}
    token = "dev12.synthetic.token.recovery." + "x" * 32
    permitted = lambda current, original: (
        current["principal_id"] == original["work_key"]["principal_id"] and
        current["identity_binding_id"] == original["trusted_identity"]["identity_binding_id"])
    service = SuccessorService(store, {token: context}, authority, NeverExecute(), campaign,
                               read_allowed=permitted, usage_write_allowed=permitted)
    before = campaign.inspect()
    arrivals_before = len((root / "receiver.jsonl").read_text().splitlines())
    try:
        service.recover_incomplete()
        status = service.status(record["submission_id"], trusted)
        duplicate_code, duplicate = service.submit(record["request"], trusted, 0, credential=token)
        if (duplicate_code != 202 or duplicate["state"] != "outcome_unknown" or
                status["candidate_access"] != "unknown_outcome"):
            raise AssertionError("historical unknown status/recovery changed")
        new_request = deepcopy(record["request"])
        new_request["work_selector"]["step_id"] = "step.control.paused"
        try:
            service.submit(new_request, trusted, 0, credential=token)
        except ContractError as exc:
            if exc.code != "FINANCIAL_AUTH_REQUIRED":
                raise
        else:
            raise AssertionError("paused campaign admitted fresh work")
        after = campaign.inspect()
        arrivals_after = len((root / "receiver.jsonl").read_text().splitlines())
        if (after["attempt_count"] != before["attempt_count"] or
                after["possible_send_count"] != before["possible_send_count"] or
                arrivals_after != arrivals_before or
                store.successor_by_work({**record["work_key"], "step_id": "step.control.paused"})):
            raise AssertionError("restart/read-only/paused path added work or a send")
        result = {"status": "PASS", "campaign_id": inventory["campaign_id"],
                  "attempt_count": after["attempt_count"], "possible_send_count": after["possible_send_count"],
                  "receiver_arrivals": arrivals_after, "unknown_status": status,
                  "paused": after["paused"], "no_replay": True}
        (root / "recovery-result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
        print(json.dumps({key: value for key, value in result.items() if key != "unknown_status"}, sort_keys=True))
    finally:
        service.pool.shutdown(wait=True)
        store.close()


if __name__ == "__main__":
    run()
