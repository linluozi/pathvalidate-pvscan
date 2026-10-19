"""Run every verification step used for this fork, in order.

Usage (from the repository root)::

    python tools/verify/run_all.py

Every step is independent and prints its own verdict. The script exits non zero
as soon as one step fails, so it can be used as a release gate.
"""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PYTHON = sys.executable


STEPS = [
    ("line endings normalised to LF", [PYTHON, HERE / "_normalize_eol.py"]),
    ("upstream files untouched", [PYTHON, HERE / "_verify_upstream.py"]),
    ("Python 3.9 syntax compatibility", [PYTHON, HERE / "_compat39.py"]),
    (
        "compatibility checker is discriminating",
        [PYTHON, HERE / "_compat39_selftest.py"],
    ),
    (
        "full test suite",
        [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header",
         "-W", "ignore::DeprecationWarning"],
    ),
    (
        "lint (real errors only)",
        [PYTHON, "-m", "ruff", "check",
         "pathvalidate/batch.py", "pathvalidate/_cli.py", "pathvalidate/__main__.py",
         "test/test_batch.py", "test/test_cli.py",
         "--select", "F,E9,I001", "--output-format=concise"],
    ),
    (
        "type check",
        [PYTHON, "-m", "mypy", "pathvalidate/batch.py", "pathvalidate/_cli.py",
         "--ignore-missing-imports"],
    ),
    ("mutation testing", [PYTHON, HERE / "_mutation_check.py"]),
]


def main() -> int:
    failures: list[str] = []

    for label, command in STEPS:
        print(f"\n=== {label}")
        print(f"    $ {' '.join(str(part) for part in command)}")

        proc = subprocess.run(
            [str(part) for part in command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        output = (proc.stdout + proc.stderr).strip().splitlines()
        for line in output[-6:]:
            print(f"    {line}")

        if proc.returncode != 0:
            failures.append(label)
            print(f"    -> FAILED (exit {proc.returncode})")
        else:
            print("    -> ok")

    print()
    print("=" * 60)

    if failures:
        print(f"{len(failures)} step(s) failed:")
        for label in failures:
            print(f"  - {label}")
        return 1

    print(f"all {len(STEPS)} verification steps passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
