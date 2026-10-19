"""Build the distribution ZIP and verify it byte for byte.

Packing rules that matter here:

* the archive root is a single directory so unpacking does not litter the cwd,
* ZIP entry names use forward slashes and no entry may contain a backslash,
* file contents must match the source tree exactly (no re-encoding),
* the executable bit is preserved where the source has it,
* LICENSE is compared against the upstream blob after extraction.
"""

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path


SRC = Path(__file__).resolve().parents[2]
ROOT_NAME = "pathvalidate-3.3.1-pvscan"
OUT = SRC.parent / f"{ROOT_NAME}.zip"

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    ".eggs",
    "docs/_build",
    "_compat39_samples",
}

SKIP_SUFFIXES = {".pyc", ".pyo", ".orig", ".rej"}

UPSTREAM_LICENSE_SHA256 = "130a35b917df1951aefbf366120491d5124045a87ded123f20ded21521f4e3a2"


def iter_files() -> list[Path]:
    files: list[Path] = []

    for path in sorted(SRC.rglob("*")):
        if not path.is_file():
            continue

        relative = path.relative_to(SRC)
        parts = relative.parts

        if any(part in SKIP_DIRS for part in parts):
            continue
        if any(str(relative).startswith(skip) for skip in SKIP_DIRS if "/" in skip):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue

        files.append(path)

    return files


def main() -> int:
    files = iter_files()
    problems: list[str] = []

    if OUT.exists():
        OUT.unlink()

    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(SRC).as_posix()
            info = zipfile.ZipInfo.from_file(path, arcname=f"{ROOT_NAME}/{relative}")
            info.compress_type = zipfile.ZIP_DEFLATED

            data = path.read_bytes()
            archive.writestr(info, data)

    # ---- verify -------------------------------------------------------
    with zipfile.ZipFile(OUT) as archive:
        names = archive.namelist()

        if any("\\" in name for name in names):
            problems.append("archive contains backslash separators")

        if len(names) != len(files):
            problems.append(f"entry count mismatch: {len(names)} != {len(files)}")

        mismatched = 0
        for path in files:
            relative = path.relative_to(SRC).as_posix()
            stored = archive.read(f"{ROOT_NAME}/{relative}")
            if stored != path.read_bytes():
                mismatched += 1
                problems.append(f"content mismatch: {relative}")

        license_name = f"{ROOT_NAME}/LICENSE"
        if license_name not in names:
            problems.append("LICENSE missing from archive")
        else:
            digest = hashlib.sha256(archive.read(license_name)).hexdigest()
            if digest != UPSTREAM_LICENSE_SHA256:
                problems.append(f"LICENSE sha256 differs from upstream: {digest}")

        for required in ("NOTICE.md", "FORK.md", "README.rst", "pyproject.toml", "setup.py"):
            if f"{ROOT_NAME}/{required}" not in names:
                problems.append(f"{required} missing from archive")

        for required in (
            "pathvalidate/batch.py",
            "pathvalidate/_cli.py",
            "pathvalidate/__main__.py",
            "test/test_batch.py",
            "test/test_cli.py",
        ):
            if f"{ROOT_NAME}/{required}" not in names:
                problems.append(f"{required} missing from archive")

        crlf = [
            name
            for name in names
            if name.endswith((".py", ".rst", ".md", ".txt", ".in", ".toml", ".cfg", ".ini"))
            and b"\r\n" in archive.read(name)
        ]
        if crlf:
            problems.append(f"{len(crlf)} text files still use CRLF: {crlf[:5]}")

    size = OUT.stat().st_size
    print(f"archive : {OUT}")
    print(f"entries : {len(files)}")
    print(f"size    : {size:,} bytes")
    print(f"sha256  : {hashlib.sha256(OUT.read_bytes()).hexdigest()}")

    if problems:
        print()
        for problem in problems:
            print("FAIL", problem)
        return 1

    print()
    print("archive verified: contents match source, LICENSE matches upstream, no CRLF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
