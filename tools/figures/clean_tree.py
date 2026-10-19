"""Remove the scratch tree, including files Windows cannot reach normally.

`shutil.rmtree` fails with WinError 145 when the directory still contains a file
whose name ends with a space or a dot: Windows strips the trailing character from
the ordinary path, so the entry looks like it does not exist. Those entries have
to be removed through the extended length prefix.
"""

import os
import shutil
import sys
from pathlib import Path


PREFIX = "\\\\?\\"


def remove_extended(path: str) -> bool:
    extended = PREFIX + path

    try:
        if os.path.isdir(extended):
            os.rmdir(extended)
        else:
            os.unlink(extended)
        return True
    except OSError as exc:
        print(f"  cannot remove {path!r}: {exc.strerror}")
        return False


def clean(tree: Path) -> None:
    if not tree.exists():
        print("nothing to clean")
        return

    base = str(tree.resolve())

    for entry in os.scandir(tree):
        full = base + "\\" + entry.name

        if entry.is_dir(follow_symlinks=False):
            clean(Path(full))
            continue

        if entry.name != entry.name.rstrip(" ."):
            remove_extended(full)

    shutil.rmtree(tree, ignore_errors=True)
    print("clean" if not tree.exists() else "still present")


if __name__ == "__main__":
    clean(Path(sys.argv[1] if len(sys.argv) > 1 else "tools/figures/_tree"))
