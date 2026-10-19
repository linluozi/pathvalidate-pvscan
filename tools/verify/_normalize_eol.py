"""Normalise every text file in the distribution to LF line endings.

`git archive` on Windows applies core.autocrlf, so the extracted tree contains
CRLF while the upstream blobs are LF. Shipping CRLF would break byte for byte
comparison of LICENSE against upstream, so every text file is converted back.

Binary files are detected by content (a NUL byte) rather than by extension, so a
new binary asset cannot slip through a whitelist.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "build", "dist", ".ruff_cache", ".mypy_cache"}


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def main() -> int:
    converted = 0
    skipped_binary = 0

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue

        data = path.read_bytes()

        if is_binary(data):
            skipped_binary += 1
            continue

        if b"\r\n" not in data:
            continue

        path.write_bytes(data.replace(b"\r\n", b"\n"))
        converted += 1

    print(f"converted to LF: {converted}, binary files left alone: {skipped_binary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
