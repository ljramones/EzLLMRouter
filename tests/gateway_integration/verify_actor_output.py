"""Require the Node 24 actor regression and strict stdout consumer before a send."""

import io
import json
from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_actor_output.py REGRESSION_JSON")
    report = json.loads(Path(sys.argv[1]).read_text())
    assert report["node"].startswith("v24."), report["node"]
    assert (report["passed"], report["failed"], report["total"]) == (9, 0, 9)
    results = report["results"]
    assert len(results) == 9 and len({row["name"] for row in results}) == 9
    successful = 0
    for row in results:
        assert row["passed"] and row["real_network_calls"] == 0, row["name"]
        if row["actor_exit"] == 0:
            # Same single-document parser used for first-submission in run.sh.
            assert json.load(io.StringIO(row["stdout"]))["submission_id"] == "submission.stub"
            assert row["stdout_records"] == 1 and row["stderr_records"] >= 1
            successful += 1
        else:
            assert row["actor_exit"] == 1 and row["stdout"] == ""
    assert successful == 6, successful
    print(
        json.dumps(
            {
                "node": report["node"],
                "passed": 9,
                "strict_stdout_consumers": successful,
                "real_network_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
