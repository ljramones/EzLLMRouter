"""Keep existing whole-library typing debt from growing while strict coverage expands."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tools/type_audit_budget.json"
SOURCES = ("server/src/ezllmrouter_server", "clients/python/src/ezllmrouter_client")
ERROR = re.compile(r"^(.+\.py):\d+(?::\d+)?: error: ", re.MULTILINE)


def error_counts(output: str) -> dict[str, int]:
    return dict(Counter(ERROR.findall(output)))


def regressions(expected: Mapping[str, int], observed: Mapping[str, int]) -> list[str]:
    return [
        f"{path}: {count} typing errors exceeds budget {expected.get(path, 0)}"
        for path, count in sorted(observed.items())
        if count > expected.get(path, 0)
    ]


def main() -> int:
    budget = json.loads(BASELINE.read_text())
    result = subprocess.run(
        [sys.executable, "-m", "mypy", *SOURCES],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
    )
    counts = error_counts(result.stdout)
    if result.returncode not in (0, 1) or (result.returncode == 1 and not counts):
        print("Whole-library typing audit could not complete.", file=sys.stderr)
        print(result.stderr or result.stdout, file=sys.stderr)
        return 1
    failures = regressions(budget["errors"], counts)
    parent = ROOT / ".artifacts/type-audit"
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="library-", dir=parent))
    (output / "diagnostics.txt").write_text(result.stdout + result.stderr)
    summary = {
        "source_roots": list(SOURCES),
        "errors": counts,
        "total_errors": sum(counts.values()),
        "budget_errors": sum(budget["errors"].values()),
        "regressions": failures,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        f"Whole-library typing debt: {summary['total_errors']} errors within reviewed budgets; {output}/summary.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
