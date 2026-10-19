"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>

Command line interface for the batch scanning helpers.

The console script is installed as ``pvscan``. Running ``pvscan check`` is
always read only; ``pvscan fix`` only touches the filesystem when ``--apply``
is given.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Final, Optional, Sequence, TextIO

from .__version__ import __version__
from ._const import Platform
from .batch import BatchRenameError, PathReport, ScanResult, plan_fixes, scan_paths

EXIT_OK: Final = 0
EXIT_PROBLEMS: Final = 1
EXIT_USAGE: Final = 2
EXIT_APPLY_FAILED: Final = 3

_MATRIX_PLATFORMS: Final = (
    Platform.WINDOWS,
    Platform.MACOS,
    Platform.LINUX,
    Platform.UNIVERSAL,
)

_SEVERITY_MARK: Final = {"error": "ERROR", "warning": "WARN "}


def _display(text: str) -> str:
    """Escape characters that would be invisible or reorder text in a terminal.

    Without this, a name containing ``U+F03F`` or ``U+200B`` looks identical to a
    clean name in the output, which makes the report impossible to act on.
    """

    out: list[str] = []

    for char in text:
        code = ord(char)
        category = unicodedata.category(char)

        if code < 0x20 or code == 0x7F:
            out.append(f"\\x{code:02x}")
        elif category in ("Cf", "Cs", "Co", "Cn"):
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)

    return "".join(out)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pvscan",
        description=(
            "Scan directory trees for file names that break on other platforms, "
            "and optionally repair them. Read only unless 'fix --apply' is used."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "paths",
        nargs="*",
        default=["."],
        metavar="PATH",
        help="files or directories to inspect (default: current directory)",
    )
    common.add_argument(
        "--platform",
        default="auto",
        metavar="NAME",
        help="target platform: auto, windows, macos, linux, posix, universal (default: auto)",
    )
    common.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="do not descend into sub directories",
    )
    common.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="descend into symlinked directories",
    )
    common.add_argument(
        "--no-unicode-check",
        dest="unicode_check",
        action="store_false",
        help="skip invisible character and NFC normalization checks",
    )
    common.add_argument(
        "--reserved",
        action="append",
        default=[],
        metavar="NAME",
        help="extra reserved name to reject (repeatable, case insensitive)",
    )
    common.add_argument(
        "--json",
        action="store_true",
        help="emit machine readable JSON instead of a table",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check", parents=[common], help="report problems without changing anything"
    )
    check.add_argument(
        "--matrix",
        action="store_true",
        help="also report whether each path is valid on every supported platform",
    )
    check.add_argument(
        "--fail-on",
        choices=("error", "warning", "never"),
        default="error",
        help="exit with status 1 when this severity or worse is found (default: error)",
    )
    check.add_argument(
        "--quiet",
        action="store_true",
        help="only print the summary line",
    )

    fix = subparsers.add_parser(
        "fix",
        parents=[common],
        help="rename offending entries (dry run unless --apply is given)",
    )
    fix.add_argument(
        "--apply",
        action="store_true",
        help="actually perform the renames; without it the plan is only printed",
    )
    fix.add_argument(
        "--replacement",
        default="_",
        metavar="TEXT",
        help="replacement text for invalid characters (default: '_')",
    )
    fix.add_argument(
        "--max-len",
        type=int,
        default=255,
        metavar="BYTES",
        help="maximum byte length per name component, 0 to disable (default: 255)",
    )
    fix.add_argument(
        "--no-collision-check",
        dest="resolve_collisions",
        action="store_false",
        help="do not disambiguate names that collapse into the same target",
    )

    return parser


def _platform_matrix(report: PathReport) -> dict[str, bool]:
    from ._filename import is_valid_filename

    result: dict[str, bool] = {}

    for platform in _MATRIX_PLATFORMS:
        ok = True
        for component in Path(report.relative).parts:
            if not is_valid_filename(component, platform=platform):
                ok = False
                break
        result[platform.value] = ok

    return result


def _print_report(
    report: PathReport,
    matrix: bool,
    out: TextIO,
) -> None:
    markers = []
    if report.is_symlink:
        markers.append("symlink")
    if report.is_dir:
        markers.append("dir")

    suffix = f"  [{', '.join(markers)}]" if markers else ""
    out.write(f"{_display(report.relative)}{suffix}\n")

    for issue in report.issues:
        mark = _SEVERITY_MARK.get(issue.severity, issue.severity.upper())
        component = (
            f" component={_display(issue.component)!r}" if issue.component is not None else ""
        )
        out.write(f"  {mark} {issue.code} {issue.kind}{component}\n")
        out.write(f"        {issue.message}\n")

    if matrix:
        verdicts = _platform_matrix(report)
        rendered = "  ".join(f"{name}={'ok' if ok else 'FAIL'}" for name, ok in verdicts.items())
        out.write(f"  matrix  {rendered}\n")


def _cmd_check(args: argparse.Namespace) -> int:
    out = sys.stdout
    results: list[ScanResult] = []

    for raw in args.paths:
        try:
            results.append(
                scan_paths(
                    raw,
                    platform=args.platform,
                    recursive=args.recursive,
                    check_unicode=args.unicode_check,
                    follow_symlinks=args.follow_symlinks,
                    additional_reserved_names=args.reserved or None,
                )
            )
        except (FileNotFoundError, NotADirectoryError) as exc:
            sys.stderr.write(f"pvscan: {exc}\n")
            return EXIT_USAGE

    if args.json:
        out.write(
            json.dumps(
                {"results": [result.as_dict() for result in results]}, indent=2, ensure_ascii=False
            )
        )
        out.write("\n")
    else:
        for result in results:
            if not args.quiet:
                out.write(f"{result.root}  (target: {result.platform.value})\n")

                for report in result.reports:
                    if report.has_issues:
                        _print_report(report, args.matrix, out)

                for path, message in result.errors:
                    out.write(f"  ERROR unreadable: {path}: {message}\n")

            out.write(
                f"{result.root}: {len(result.reports)} scanned, "
                f"{result.invalid_count} invalid, {result.problem_count} with issues\n"
            )

    total_invalid = sum(result.invalid_count for result in results)
    total_issues = sum(result.problem_count for result in results)

    if args.fail_on == "never":
        return EXIT_OK

    if args.fail_on == "warning":
        return EXIT_PROBLEMS if total_issues else EXIT_OK

    return EXIT_PROBLEMS if total_invalid else EXIT_OK


def _cmd_fix(args: argparse.Namespace) -> int:
    out = sys.stdout
    exit_code = EXIT_OK

    for raw in args.paths:
        try:
            result = scan_paths(
                raw,
                platform=args.platform,
                recursive=args.recursive,
                check_unicode=args.unicode_check,
                follow_symlinks=args.follow_symlinks,
                additional_reserved_names=args.reserved or None,
            )
        except (FileNotFoundError, NotADirectoryError) as exc:
            sys.stderr.write(f"pvscan: {exc}\n")
            return EXIT_USAGE

        plan = plan_fixes(
            result,
            replacement_text=args.replacement,
            max_len=None if args.max_len <= 0 else args.max_len,
            resolve_collisions=args.resolve_collisions,
            additional_reserved_names=args.reserved or None,
        )

        if args.json:
            payload = plan.as_dict()
            payload["applied"] = False
            if args.apply:
                try:
                    apply_result = plan.apply()
                except BatchRenameError as exc:
                    payload["error"] = str(exc)
                    out.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
                    sys.stderr.write(f"pvscan: {exc}\n")
                    return EXIT_APPLY_FAILED

                payload["applied"] = True
                payload["renamed"] = [rename.as_dict() for rename in apply_result.applied]

            out.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

            if plan.unresolved:
                exit_code = EXIT_PROBLEMS
            continue

        if not plan.has_changes:
            out.write(f"{result.root}: nothing to fix ({len(result.reports)} entries checked)\n")
            if plan.unresolved:
                exit_code = EXIT_PROBLEMS
                for path, reason in plan.unresolved:
                    out.write(f"  UNRESOLVED {path}: {reason}\n")
            continue

        out.write(f"{result.root}: {len(plan.renames)} rename(s) planned\n")
        for rename in plan.renames:
            reason = f"  ({', '.join(rename.reasons)})" if rename.reasons else ""
            out.write(
                f"  {_display(rename.source.name)!r} -> {_display(rename.target.name)!r}{reason}\n"
            )

        for path, reason in plan.unresolved:
            exit_code = EXIT_PROBLEMS
            out.write(f"  UNRESOLVED {path}: {reason}\n")

        if not args.apply:
            out.write("dry run: re-run with --apply to perform these renames\n")
            continue

        try:
            apply_result = plan.apply()
        except BatchRenameError as exc:
            sys.stderr.write(f"pvscan: {exc}\n")
            sys.stderr.write("pvscan: already applied renames were rolled back\n")
            return EXIT_APPLY_FAILED

        out.write(f"applied {apply_result.changed_count} rename(s)\n")

    return exit_code


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point of the ``pvscan`` console script."""

    # Windows consoles default to a legacy code page, which turns any non ASCII
    # file name into a UnicodeEncodeError. The report is the whole point of this
    # tool, so force UTF-8 on the streams when they support it.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "check":
        return _cmd_check(args)

    if args.command == "fix":
        return _cmd_fix(args)

    parser.error(f"unknown command: {args.command}")
    return EXIT_USAGE  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
