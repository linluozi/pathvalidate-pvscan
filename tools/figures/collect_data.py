"""Build a realistic messy tree and record what pvscan actually reports.

The numbers written to results.json are the ones used for the figures, so the
charts cannot drift away from what the tool really does.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parent
TREE = WORK / "_tree"
PYTHON = sys.executable
PVSCAN = Path(r"C:\Users\15082\.workbuddy\binaries\python\envs\pvscan\Scripts\pvscan.exe")


def wsl(name: str) -> str:
    table = {c: chr(0xF000 + ord(c)) for c in '<>:"/\\|?*'}
    return "".join(table.get(c, c) for c in name)


def build() -> None:
    if TREE.exists():
        shutil.rmtree(TREE, ignore_errors=True)

    TREE.mkdir(parents=True)

    # a Windows reserved device name
    (TREE / "CON.txt").write_text("x")
    (TREE / "nul.tar.gz").write_text("x")

    # names WSL stored in the private use area
    (TREE / wsl("a|b.txt")).write_text("x")
    (TREE / wsl("a?b.txt")).write_text("x")
    (TREE / wsl("report<final>.log")).write_text("x")

    # trailing dot / trailing space, only reachable via the extended prefix
    for raw in ("trail.", "lead "):
        subprocess.run(
            [PYTHON, "-c", f"import os;os.close(os.open(r'\\\\?\\{TREE}\\{raw}', os.O_CREAT|os.O_WRONLY))"],
            check=True,
        )

    # invisible characters and unnormalized unicode
    (TREE / "inv\u200bisible.txt").write_text("x")

    import unicodedata

    (TREE / unicodedata.normalize("NFD", "café.txt")).write_text("x")

    # over-long name, extension must survive
    (TREE / ("d" * 90 + ".tar.gz")).write_text("x")

    # a nested directory with a broken name
    bad = TREE / wsl("sub:dir")
    bad.mkdir()
    (bad / wsl("inner<1>.log")).write_text("x")
    (bad / "keep.txt").write_text("x")

    # clean files, as a control group
    for name in ("ok.txt", "notes.md", "photo.jpeg"):
        (TREE / name).write_text("x")


def run(*args: str) -> dict:
    proc = subprocess.run(
        [str(PVSCAN), *args, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(proc.stdout)


def main() -> int:
    build()

    before = run("check", str(TREE), "--platform", "windows")
    kinds: dict[str, int] = {}

    for entry in before["results"][0]["entries"]:
        for issue in entry["issues"]:
            kinds[issue["kind"]] = kinds.get(issue["kind"], 0) + 1

    plan = run("fix", str(TREE), "--platform", "windows", "--max-len", "40")

    applied = run(
        "fix", str(TREE), "--platform", "windows", "--max-len", "40", "--apply"
    )

    after = run("check", str(TREE), "--platform", "windows")

    data = {
        "scanned": before["results"][0]["scanned"],
        "invalid_before": before["results"][0]["invalid"],
        "issues_before": before["results"][0]["with_issues"],
        "kinds": kinds,
        "planned_renames": len(plan["renames"]),
        "applied_renames": len(applied.get("renamed", [])),
        "invalid_after": after["results"][0]["invalid"],
        "issues_after": after["results"][0]["with_issues"],
        "renames": plan["renames"],
    }

    (WORK / "results.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
    )

    print(json.dumps({k: v for k, v in data.items() if k != "renames"}, indent=2))
    print("\nsample renames:")
    for rename in data["renames"][:6]:
        print(f"  {rename['source'].split(chr(92))[-1]!r} -> {rename['target'].split(chr(92))[-1]!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
