# NOTICE

This distribution is a **modified** version of
[pathvalidate](https://github.com/thombashi/pathvalidate).

- Upstream project: `thombashi/pathvalidate`
- Upstream commit this fork is based on: `1ca0a50fce51d5b5bd633457a72abf74dbe3112d`
  ("Update tips.rst to clarify handling of dot directory entries: #68", 2026-05-10)
- Upstream version at that commit: `3.3.1`
- Upstream license: MIT License, Copyright (c) 2016-2025 Tsuyoshi Hombashi

The original license text is kept **byte for byte** in [`LICENSE`](LICENSE), as
required by the MIT license. It has not been edited, extended or reworded.

## What was changed

Everything listed here is additive. No upstream validation rule, error message,
error code or public function signature was modified.

### New files

| File | Purpose |
| --- | --- |
| `pathvalidate/batch.py` | Batch scanning, fix planning and safe renaming on top of the existing validators. |
| `pathvalidate/_cli.py` | Implementation of the `pvscan` command line tool. |
| `pathvalidate/__main__.py` | Allows `python -m pathvalidate`. |
| `test/test_batch.py` | 49 tests for the batch layer. |
| `test/test_cli.py` | 28 tests for the CLI. |
| `NOTICE.md` | This file. |

### Modified files

| File | Change |
| --- | --- |
| `pathvalidate/__init__.py` | Re-exports the new public batch API. Nothing removed. |
| `setup.py` | Adds the `pvscan` console script entry point. |
| `pyproject.toml` | Adds `fallback_version = "3.3.1"` so the source tree can be built from a ZIP without a `.git` directory. |
| `MANIFEST.in` | Ships `NOTICE.md` and the `tools/` verification scripts in the sdist. |
| `.gitignore` | Ignores the scratch tree used to generate the figures. |
| `README.rst` | Documents the new batch API and the `pvscan` tool. |
| `CHANGELOG.md` | Adds a fork section above the upstream entries. |
| `docs/pages/reference/index.rst` | Links the new `batch` reference page. |

### New files (in addition to the table above)

| File | Purpose |
| --- | --- |
| `docs/pages/reference/batch.rst` | Sphinx API reference for the batch layer. |
| `FORK.md` | Standalone description of the fork, its verification and limitations. |
| `tools/verify/run_all.py` | Runs every verification step in order. |
| `tools/verify/_mutation_check.py` | Mutation testing of the new code. |
| `tools/verify/_compat39.py` | Static Python 3.9 compatibility check. |
| `tools/verify/_compat39_selftest.py` | Proves the compatibility checker works. |
| `tools/verify/_verify_upstream.py` | Compares every upstream file against its git blob. |
| `tools/verify/_normalize_eol.py` | Normalizes the tree to LF (git archive applies CRLF on Windows). |

### Behavioural notes

- The upstream single-name functions behave exactly as before. The test suite
  asserts this explicitly (`Test_public_api::test_upstream_behaviour_is_unchanged`).
- `scan_paths` is read only. `plan_fixes` computes renames without touching the
  filesystem. Only `FixPlan.apply()` and `pvscan fix --apply` rename anything.

## Verification performed

- Upstream test suite: `4170 passed, 14 skipped` before the change,
  `4247 passed, 14 skipped` after (the 77 new tests are the only difference, the
  same 14 tests are skipped for the same reasons).
- 8/8 targeted mutations of the new code are caught by the new tests.
- `mypy` reports no issues for the new modules.
- `ruff check --select F,E9,I001` reports no issues for the new files.
- Python 3.9 compatibility checked statically (the only interpreter available
  locally is 3.13).
