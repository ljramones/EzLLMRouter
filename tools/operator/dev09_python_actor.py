"""Installed Python client actor; input and output contain only synthetic IDs."""

if not __package__ and "__file__" in globals():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import json
import sys

from ezllmrouter_client import EzLLMRouterClient, __version__


def main():
    data = json.load(sys.stdin)
    runs = []
    outcome = None
    with EzLLMRouterClient(base_url=data["base_url"], token=data["token"]) as client:
        for row in data["rows"]:
            run = client.start_run(row["run"])
            reply = client.submit_in_run(row["request"], row["run"]["run_id"], {"wait_ms": 3000})
            runs.append(
                {
                    "run_id": run["run_id"],
                    "submission_id": reply["handle"]["submission_id"],
                    "state": reply["state"],
                }
            )
        if data.get("outcome"):
            if data.get("expect_outcome_authority"):
                receipt = client.report_outcome(data["outcome"])
                if (
                    client.report_outcome(data["outcome"]) != receipt
                    or client.get_outcome_receipt(data["outcome"]["event_id"]) != receipt
                ):
                    raise AssertionError("outcome duplicate or read receipt changed")
                outcome = receipt
            else:
                try:
                    client.report_outcome(data["outcome"])
                    raise AssertionError("ungranted outcome authority unexpectedly accepted")
                except Exception as exc:
                    if getattr(exc, "code", None) != "POLICY_DENIED":
                        raise
    print(
        json.dumps(
            {
                "package": __import__("ezllmrouter_client").__file__,
                "version": __version__,
                "runs": runs,
                "outcome": outcome,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
