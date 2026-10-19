"""Compare every upstream file in the working tree against its git blob.

The point is to prove that the fork only *added* files and only touched the four
files documented in NOTICE.md. Comparing after LF normalisation is required
because git archive on Windows applies core.autocrlf.
"""

import hashlib
import subprocess
import sys
from pathlib import Path


UPSTREAM = Path("E:/WorkBuddy-Work/WorkBuddy-0/_audit_pathvalidate")
LOCAL = Path(__file__).resolve().parents[2]

#: files that are expected to differ, with the reason
EXPECTED_DIFFERENCES = {
    "pathvalidate/__init__.py": "re-exports the batch API",
    "setup.py": "console script entry point",
    "pyproject.toml": "setuptools_scm fallback_version",
    "MANIFEST.in": "ships NOTICE.md and tools/",
    ".gitignore": "ignores the figure scratch tree",
    "README.rst": "documents the batch API and pvscan",
    "CHANGELOG.md": "fork section",
    "docs/pages/reference/index.rst": "adds the batch reference page",
}


def git_blobs() -> dict[str, bytes]:
    listing = subprocess.run(
        ["git", "-C", str(UPSTREAM), "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    blobs: dict[str, bytes] = {}

    for name in listing:
        blobs[name] = subprocess.run(
            ["git", "-C", str(UPSTREAM), "show", f"HEAD:{name}"],
            capture_output=True,
            check=True,
        ).stdout

    return blobs


def main() -> int:
    blobs = git_blobs()

    identical = 0
    changed_expected = []
    changed_unexpected = []
    missing = []

    for name, data in blobs.items():
        local_path = LOCAL / name

        if not local_path.exists():
            missing.append(name)
            continue

        local = local_path.read_bytes()
        same = hashlib.sha256(local.replace(b"\r\n", b"\n")).digest() == hashlib.sha256(
            data.replace(b"\r\n", b"\n")
        ).digest()

        if same:
            identical += 1
        elif name in EXPECTED_DIFFERENCES:
            changed_expected.append(name)
        else:
            changed_unexpected.append(name)

    print(f"upstream files tracked : {len(blobs)}")
    print(f"byte identical         : {identical}")
    print(f"changed as documented  : {len(changed_expected)}")
    for name in changed_expected:
        print(f"    ~ {name}  ({EXPECTED_DIFFERENCES[name]})")

    if missing:
        print(f"MISSING ({len(missing)}):")
        for name in missing:
            print(f"    - {name}")

    if changed_unexpected:
        print(f"UNEXPECTED CHANGES ({len(changed_unexpected)}):")
        for name in changed_unexpected:
            print(f"    ! {name}")

    ok = not missing and not changed_unexpected
    print()
    print("tree matches the documented change set" if ok else "TREE DIVERGES")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
