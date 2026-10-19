"""Prove that _compat39.py actually detects 3.9 incompatibilities.

Each sample is a construct that really breaks on Python 3.9, or a construct that
is safe there. Note that PEP 526 variable annotations are *not* evaluated at
runtime, so ``x: list[int] = []`` is fine on 3.9 and is used as a negative
control here.
"""

import subprocess
import sys
from pathlib import Path


SAMPLES = {
    # real 3.9 failures: the subscript / union is evaluated as a value
    "eager_generic.py": "def f():\n    return list[int]\n",
    "eager_union.py": "def f(a):\n    return int | None\n",
    "eager_alias.py": "Alias = dict[str, int]\n",
    # safe on 3.9: lazy annotations and PEP 526 variable annotations
    "ok_lazy.py": (
        "from __future__ import annotations\n"
        "def f(a: list[int], b: dict[str, int] | None = None) -> tuple[int, ...]:\n"
        "    return (1,)\n"
    ),
    "ok_var_annotation.py": "x: list[int] = []\n",
}

EXPECT_FAIL = {"eager_generic.py", "eager_union.py", "eager_alias.py"}


def main() -> int:
    here = Path(__file__).resolve().parent
    tmp = here / "_compat39_samples"
    tmp.mkdir(exist_ok=True)

    ok = True

    for name, content in SAMPLES.items():
        target = tmp / name
        target.write_text(content, encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(here / "_compat39.py"), "--file", str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        failed = proc.returncode != 0
        expected = name in EXPECT_FAIL
        verdict = "as expected" if failed == expected else "UNEXPECTED"

        if failed != expected:
            ok = False

        first = (proc.stdout.strip() or proc.stderr.strip()).splitlines()[0]
        print(f"{name:22} {'FAIL' if failed else 'ok  '}  {verdict:12} {first}")

    print()
    print("checker is discriminating" if ok else "CHECKER IS BROKEN")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
