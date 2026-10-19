# pvscan — batch path checking for pathvalidate

[![Python](https://img.shields.io/badge/python-3.9%2B-2b2119?style=flat-square)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-c8892b?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-4247%20passed-6b6b3a?style=flat-square)](#verification)
[![Mutations](https://img.shields.io/badge/mutations-8%2F8%20killed-b4552f?style=flat-square)](#verification)

A fork of [thombashi/pathvalidate](https://github.com/thombashi/pathvalidate) that
adds **batch scanning and safe renaming** of directory trees, plus a `pvscan`
command line tool.

Upstream answers *"is this one file name valid for platform X?"*.
This fork answers *"I have 40,000 files downloaded from three operating systems —
which ones will break, and can you fix them without clobbering each other?"*

![Three stages: scan, plan, apply](docs/figures/fig3_pipeline.png)

---

## The five problems a single-name validator cannot express

All five were reproduced on a real filesystem before being fixed.

| # | Problem | Evidence |
| --- | --- | --- |
| 1 | **Truncation eats the extension** | `sanitize_filename("a"*250 + ".tar.gz", max_len=255)` → `"…aaa.tar"`. The file is no longer an archive. |
| 2 | **Sanitizing creates collisions** | `a:b` and `a\|b` both become `a_b` on Windows. In a rename loop the second one fails or overwrites. |
| 3 | **WSL names are legal but broken** | WSL stores `\| : * ? < >` as private-use characters at `U+F000`. Every validator says "valid"; the file breaks on copy. |
| 4 | **Trailing space / dot files are unreachable** | Windows strips them from ordinary paths, so `os.rename("report. ", …)` raises `FileNotFoundError` for a file that exists. |
| 5 | **Parent renamed before child** | Renaming `sub:dir` first invalidates `sub:dir/inner.log`, which still needs fixing. |

![Problem kinds found in a mixed-OS folder](docs/figures/fig1_problem_kinds.png)

---

## Install

```console
$ pip install .
$ pvscan --help
```

Python 3.9+. No external dependencies.

## Use

```console
# report only, never writes
$ pvscan check ./downloads --platform windows

# dry run: prints the plan, changes nothing
$ pvscan fix ./downloads --platform windows

# actually rename
$ pvscan fix ./downloads --platform windows --apply
```

Re-running is a no-op:

```console
$ pvscan fix ./downloads --platform windows --apply
./downloads: nothing to fix (5 entries checked)
```

![Before and after](docs/figures/fig2_before_after.png)

### Options

| Flag | Meaning |
| --- | --- |
| `--platform` | `auto`, `windows`, `macos`, `linux`, `posix`, `universal` |
| `--matrix` | `check` only: verdict for every platform in one pass |
| `--json` | machine readable output |
| `--replacement` | text for invalid characters (default `_`) |
| `--max-len` | byte budget per component, `0` disables (default 255) |
| `--reserved` | extra reserved name, repeatable |
| `--fail-on` | `check` exit code trigger: `error` (default), `warning`, `never` |

Exit codes: `0` clean, `1` problems, `2` usage error, `3` apply failed.

### From Python

```python
from pathvalidate import scan_paths, plan_fixes

result = scan_paths("./downloads", platform="windows")

for report in result.reports:
    for issue in report.issues:
        print(report.relative, issue.code, issue.kind)

plan = plan_fixes(result)          # no filesystem changes
for rename in plan:
    print(rename.source.name, "->", rename.target.name, rename.reasons)

plan.apply()                       # children first, rolls back on failure
```

---

## What makes the renames safe

- **Extension preserving truncation.** `split_name("archive.tar.gz")` →
  `("archive", ".tar.gz")`, so the byte budget is spent on the stem.
- **Collision resolution.** Names are grouped per parent directory and tracked
  case-insensitively; the second `a_b` becomes `a_b (2)`.
- **Bottom-up order.** Deepest paths are renamed first, so a parent rename never
  invalidates a pending child path.
- **Extended length prefix.** Files with trailing spaces or dots are reached
  through `\\?\`, which is the only way Windows will open them.
- **Rollback.** If rename 7 of 10 fails, the first 6 are reverted and
  `BatchRenameError` is raised.
- **Terminal-safe output.** Names print as `a\uf07cb.txt`, not as an invisible
  character, so the report can be acted on.

---

## Verification

```console
$ python tools/verify/run_all.py
```

| Step | Result |
| --- | --- |
| Upstream files untouched | 90 of 96 byte identical; 6 changed, all in `NOTICE.md` |
| Full test suite | **4247 passed, 14 skipped** (upstream baseline: 4170 / 14) |
| Mutation testing | **8/8 killed** |
| Lint (`F,E9,I001`) | clean on all new files |
| `mypy` | clean on `batch.py` and `_cli.py` |
| Python 3.9 | statically verified (3 real breakages caught by the checker) |
| Fresh install from ZIP | full suite + CLI end-to-end pass |

The baseline was measured before touching anything, and the 14 skipped tests are
the same 14 for the same reasons. Mutation testing deletes one behaviour at a
time (extension preservation, collision resolution, WSL decoding, ordering,
extended prefix, rollback, WSL detection, invisible-character detection) and the
suite goes red for each — a green suite alone would not prove the tests can fail.

---

## Scope and limits

- `check` on a single file checks that file's name only, not its parent directories.
- Symlinked directories are not descended into by default, and their names are
  never rewritten.
- `PVX001` / `PVX002` are warnings and do not affect the exit code unless
  `--fail-on warning` is used.
- Python 3.9 compatibility is verified statically; the suite was executed on 3.13.

See [FORK.md](FORK.md) for the full write-up and [NOTICE.md](NOTICE.md) for the
exact change list.

---

## License

MIT, same as upstream. `LICENSE` is byte-for-byte the upstream file
(sha256 `130a35b917df1951aefbf366120491d5124045a87ded123f20ded21521f4e3a2`).

Original: Copyright (c) 2016-2025 Tsuyoshi Hombashi.
Modifications documented in [NOTICE.md](NOTICE.md).
