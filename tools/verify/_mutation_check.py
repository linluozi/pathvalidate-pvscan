"""Reverse-verify the new tests: break the implementation and expect failures.

A green suite proves nothing on its own. Each mutation below removes one specific
behaviour; if the suite stays green, the corresponding test is a false positive.
"""

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "pathvalidate" / "batch.py"
PYTHON = sys.executable

MUTATIONS = [
    (
        "extension preserving truncation removed",
        "return truncated_stem + extension",
        "return truncate_str(name, encoding, max_len)",
    ),
    (
        "collision disambiguation disabled",
        "unique = _unique_name(candidate, taken, case_insensitive, max_len, encoding)",
        "unique = candidate",
    ),
    (
        "wsl decoding removed from the fixer",
        "    component = decode_wsl_name(component)",
        "    pass",
    ),
    (
        "bottom-up ordering reversed",
        "renames.sort(key=lambda rename: (-rename.depth, str(rename.source)))",
        "renames.sort(key=lambda rename: (rename.depth, str(rename.source)))",
    ),
    (
        "extended path prefix disabled",
        "    if use_prefix:\n        os.rename(_extended_path(source), _extended_path(target))\n        return",
        "    if False:\n        os.rename(_extended_path(source), _extended_path(target))\n        return",
    ),
    (
        "rollback removed",
        "                for done in reversed(applied):\n                    try:\n                        _rename(done.target, done.source)\n                    except OSError:  # pragma: no cover - best effort rollback\n                        pass",
        "                pass",
    ),
    (
        "wsl detection disabled in the scanner",
        "    if has_wsl_mapping(component):",
        "    if False:",
    ),
    (
        "invisible character detection disabled",
        "        if unicodedata.category(char) in (\"Cf\", \"Cc\", \"Cs\"):",
        "        if False:",
    ),
]


def run_tests() -> tuple[int, str]:
    proc = subprocess.run(
        [
            PYTHON,
            "-m",
            "pytest",
            "test/test_batch.py",
            "test/test_cli.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "--no-header",
            "-W",
            "ignore::DeprecationWarning",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    tail = [line for line in proc.stdout.splitlines() if "passed" in line or "failed" in line]

    return proc.returncode, tail[-1] if tail else "?"


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    backup = TARGET.with_suffix(".py.orig")
    shutil.copyfile(TARGET, backup)

    print(f"baseline: {run_tests()[1]}")

    survivors = []

    try:
        for label, old, new in MUTATIONS:
            if old not in original:
                print(f"SKIP  {label}: pattern not found")
                survivors.append(label)
                continue

            mutated = original.replace(old, new, 1)
            TARGET.write_text(mutated, encoding="utf-8")

            code, summary = run_tests()

            if code == 0:
                print(f"SURVIVED  {label}  ({summary})")
                survivors.append(label)
            else:
                print(f"killed    {label}  ({summary})")
    finally:
        TARGET.write_text(original, encoding="utf-8")
        backup.unlink()

    print()
    print(f"{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} mutations killed")

    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
