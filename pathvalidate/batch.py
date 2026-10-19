"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>

Batch scanning and safe renaming utilities.

This module builds *on top of* the single-name validators in
:py:mod:`pathvalidate._filename` / :py:mod:`pathvalidate._filepath`. It does not
change any of the validation rules; it adds a higher level workflow that is
useful when a whole directory tree has to be checked or repaired:

- per path-component diagnostics (a bad directory name is reported separately
  from a bad leaf name),
- extension preserving truncation (``"a" * 250 + ".tar.gz"`` keeps ``.tar.gz``
  instead of degrading to ``.tar``),
- collision resolution after sanitization (``"a:b"`` and ``"a|b"`` both become
  ``"a_b"``, the second one is disambiguated),
- invisible / unnormalized Unicode detection,
- bottom-up application order so that renaming a directory never invalidates
  the path of a child that still has to be processed,
- rollback when a rename fails half way through.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterable, Iterator, Optional, Sequence

from ._common import normalize_platform, truncate_str
from ._const import Platform
from ._filename import sanitize_filename, validate_filename
from .error import ValidationError

__all__ = (
    "ApplyResult",
    "BatchRenameError",
    "FixPlan",
    "Issue",
    "PathReport",
    "Rename",
    "ScanResult",
    "apply_fixes",
    "plan_fixes",
    "scan_paths",
    "split_name",
)


#: Platforms whose filesystems are case insensitive by default.
_CASE_INSENSITIVE_PLATFORMS: Final = (Platform.WINDOWS, Platform.MACOS, Platform.UNIVERSAL)

#: Maximum length (in characters) that is still treated as a file extension.
_MAX_EXTENSION_LEN: Final = 16

#: Maximum number of dot separated parts that are treated as one extension.
_MAX_EXTENSION_PARTS: Final = 3

#: Suffix template used when two entries would collapse into the same name.
_COLLISION_TMPL: Final = " ({:d})"

#: Synthetic issue codes for problems that pathvalidate itself does not report.
_CODE_INVISIBLE: Final = "PVX001"
_CODE_UNNORMALIZED: Final = "PVX002"
_CODE_COLLISION: Final = "PVX003"
_CODE_WSL_MAPPED: Final = "PVX004"

#: Windows Subsystem for Linux stores characters that NTFS forbids by mapping
#: them into the Unicode private use area, starting at ``U+F000``.
#: See https://learn.microsoft.com/en-us/windows/wsl/case-sensitivity
_WSL_PUA_START: Final = 0xF000
_WSL_PUA_END: Final = 0xF0FF

#: Characters that WSL maps into the private use area, i.e. the ones NTFS
#: refuses. Reversing the mapping therefore also repairs the name.
_WSL_MAPPABLE: Final = frozenset('<>:"/\\|?*')


def decode_wsl_name(name: str) -> str:
    """Reverse the WSL private use area mapping of a file name.

    The Windows Subsystem for Linux cannot store characters such as ``":"`` or
    ``"|"`` on NTFS. It stores them in the Unicode private use area instead
    (``U+F000`` + the character code). Such names look harmless to a plain
    validator but break as soon as the file is copied to another filesystem, so
    they are worth detecting and repairing.

    Args:
        name: A single path component.

    Returns:
        The name with private use area characters mapped back to ASCII. Only
        characters that WSL itself would have mapped are converted, everything
        else is left untouched.

    Example:
        >>> decode_wsl_name("a\\uf03fb.txt")
        'a|b.txt'
        >>> decode_wsl_name("plain.txt")
        'plain.txt'
    """

    chars: list[str] = []

    for char in name:
        code = ord(char)
        if _WSL_PUA_START <= code <= _WSL_PUA_END:
            candidate = chr(code - _WSL_PUA_START)
            if candidate in _WSL_MAPPABLE:
                chars.append(candidate)
                continue

        chars.append(char)

    return "".join(chars)


def has_wsl_mapping(name: str) -> bool:
    """Return |True| when ``name`` contains a WSL private use area character."""

    for char in name:
        code = ord(char)
        if _WSL_PUA_START <= code <= _WSL_PUA_END and chr(code - _WSL_PUA_START) in _WSL_MAPPABLE:
            return True

    return False


def _is_case_insensitive(platform: Platform) -> bool:
    return platform in _CASE_INSENSITIVE_PLATFORMS


def _byte_len(text: str, encoding: str) -> int:
    return len(text.encode(encoding, "surrogatepass"))


def split_name(name: str) -> tuple[str, str]:
    """Split a file name into a stem and an extension.

    Unlike :py:meth:`pathlib.PurePath.suffix`, this keeps compound extensions
    such as ``".tar.gz"`` together, and treats dot files (``".bashrc"``) as
    having no extension at all.

    Args:
        name: A file name (not a path).

    Returns:
        A ``(stem, extension)`` tuple. ``extension`` is either empty or starts
        with a dot.

    Example:
        >>> split_name("archive.tar.gz")
        ('archive', '.tar.gz')
        >>> split_name(".bashrc")
        ('.bashrc', '')
        >>> split_name("notes")
        ('notes', '')
    """

    if name in (".", "..") or not name:
        return name, ""

    parts = name.split(".")

    if len(parts) < 2 or not parts[0] and len(parts) == 2:
        # no dot at all, or a dot file such as ".bashrc"
        return name, ""

    suffix_parts: list[str] = []

    for part in reversed(parts[1:]):
        if not part or len(part) > _MAX_EXTENSION_LEN:
            break

        candidate = suffix_parts + [part]

        if len(".".join(candidate)) > _MAX_EXTENSION_LEN:
            break

        suffix_parts = candidate

        if len(suffix_parts) >= _MAX_EXTENSION_PARTS:
            break

    if not suffix_parts:
        return name, ""

    extension = "." + ".".join(reversed(suffix_parts))
    stem = name[: len(name) - len(extension)]

    if not stem:
        return name, ""

    return stem, extension


def fit_length(name: str, max_len: int, encoding: str) -> str:
    """Truncate ``name`` to ``max_len`` bytes while preserving its extension.

    Args:
        name: File name to fit.
        max_len: Maximum byte length. A value lower than one disables fitting.
        encoding: Filesystem encoding used to measure the byte length.

    Returns:
        The original name when it already fits, otherwise a truncated name that
        keeps the extension returned by :py:func:`split_name`.
    """

    if max_len < 1 or _byte_len(name, encoding) <= max_len:
        return name

    stem, extension = split_name(name)
    extension_len = _byte_len(extension, encoding)

    if not extension or extension_len >= max_len:
        return truncate_str(name, encoding, max_len)

    budget = max_len - extension_len
    truncated_stem = truncate_str(stem, encoding, budget)

    if not truncated_stem:
        return truncate_str(extension.lstrip(".") or "_", encoding, max_len)

    return truncated_stem + extension


@dataclass(frozen=True)
class Issue:
    """A single problem found on a path or on one of its components."""

    code: str
    """Machine readable code, e.g. ``"PV1100"`` or ``"PVX001"``."""

    kind: str
    """Short machine readable name, e.g. ``"INVALID_CHARACTER"``."""

    message: str
    """Human readable description."""

    severity: str
    """Either ``"error"`` (the path is unusable as is) or ``"warning"``."""

    component: Optional[str] = None
    """The offending path component, when the issue is component scoped."""

    index: Optional[int] = None
    """Zero based index of :py:attr:`component` within the path."""

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "code": self.code,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
        }

        if self.component is not None:
            data["component"] = self.component
        if self.index is not None:
            data["index"] = self.index

        return data


@dataclass(frozen=True)
class PathReport:
    """Diagnostics for a single path."""

    path: Path
    relative: str
    issues: tuple[Issue, ...]
    is_dir: bool = False
    is_symlink: bool = False

    @property
    def is_valid(self) -> bool:
        """bool: |True| when no ``error`` severity issue was found."""

        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    def as_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "relative": self.relative,
            "is_dir": self.is_dir,
            "is_symlink": self.is_symlink,
            "valid": self.is_valid,
            "issues": [issue.as_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class ScanResult:
    """The outcome of :py:func:`scan_paths`."""

    root: Path
    platform: Platform
    reports: tuple[PathReport, ...]
    errors: tuple[tuple[str, str], ...] = ()
    """``(path, message)`` pairs for entries that could not be read."""

    @property
    def problem_count(self) -> int:
        return sum(1 for report in self.reports if report.has_issues)

    @property
    def invalid_count(self) -> int:
        return sum(1 for report in self.reports if not report.is_valid)

    def as_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "platform": self.platform.value,
            "scanned": len(self.reports),
            "invalid": self.invalid_count,
            "with_issues": self.problem_count,
            "errors": [{"path": path, "message": message} for path, message in self.errors],
            "entries": [report.as_dict() for report in self.reports if report.has_issues],
        }


def _classify(exc: ValidationError) -> tuple[str, str]:
    try:
        kind = exc.reason.name
        code = exc.reason.code
    except AttributeError:  # pragma: no cover - defensive
        kind = "UNKNOWN"
        code = "PV0000"

    return code, kind


def _invisible_chars(text: str) -> list[str]:
    found: list[str] = []

    for char in text:
        if unicodedata.category(char) in ("Cf", "Cc", "Cs"):
            found.append(char)

    return found


def _check_component(
    component: str,
    index: int,
    platform: Platform,
    check_unicode: bool,
    additional_reserved_names: Optional[Sequence[str]],
) -> list[Issue]:
    issues: list[Issue] = []

    try:
        validate_filename(
            component,
            platform=platform,
            additional_reserved_names=additional_reserved_names,
        )
    except ValidationError as exc:
        code, kind = _classify(exc)
        issues.append(
            Issue(
                code=code,
                kind=kind,
                message=str(exc),
                severity="error",
                component=component,
                index=index,
            )
        )

    if not check_unicode:
        return issues

    if has_wsl_mapping(component):
        decoded = decode_wsl_name(component)
        issues.append(
            Issue(
                code=_CODE_WSL_MAPPED,
                kind="WSL_MAPPED_CHARACTER",
                message=(
                    "character(s) remapped into the Unicode private use area by WSL, "
                    f"original name is {decoded!r}"
                ),
                severity="warning",
                component=component,
                index=index,
            )
        )

    invisible = _invisible_chars(component)
    if invisible:
        rendered = ", ".join(f"U+{ord(char):04X}" for char in dict.fromkeys(invisible))
        issues.append(
            Issue(
                code=_CODE_INVISIBLE,
                kind="INVISIBLE_CHARACTER",
                message=f"invisible character(s) found: {rendered}",
                severity="warning",
                component=component,
                index=index,
            )
        )

    if component != unicodedata.normalize("NFC", component):
        issues.append(
            Issue(
                code=_CODE_UNNORMALIZED,
                kind="UNNORMALIZED_UNICODE",
                message="file name is not in Unicode NFC form",
                severity="warning",
                component=component,
                index=index,
            )
        )

    return issues


def _iter_tree(
    root: Path,
    recursive: bool,
    follow_symlinks: bool,
    errors: list[tuple[str, str]],
) -> Iterator[tuple[Path, bool, bool]]:
    """Yield ``(path, is_dir, is_symlink)`` for every entry below ``root``."""

    stack: list[Path] = [root]

    while stack:
        current = stack.pop()

        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError as exc:
            errors.append((str(current), str(exc)))
            continue

        for entry in entries:
            path = Path(entry.path)
            try:
                is_symlink = entry.is_symlink()
                is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
            except OSError as exc:
                errors.append((str(path), str(exc)))
                continue

            yield path, is_dir, is_symlink

            if is_dir and recursive and (follow_symlinks or not is_symlink):
                stack.append(path)


def scan_paths(
    root: "os.PathLike[str] | str",
    *,
    platform: Optional[str] = None,
    recursive: bool = True,
    check_unicode: bool = True,
    follow_symlinks: bool = False,
    additional_reserved_names: Optional[Sequence[str]] = None,
) -> ScanResult:
    """Check every path component below ``root`` for portability problems.

    The scan is strictly read only. ``root`` itself is only reported when it is
    a file: the assumption is that the caller has already decided on the name of
    the directory it points at.

    Args:
        root: Directory or file to scan.
        platform: Target platform name (``"windows"``, ``"linux"``, ``"macos"``,
            ``"posix"``, ``"universal"`` or ``"auto"``). Defaults to ``"auto"``,
            i.e. the platform this code runs on.
        recursive: If |True| (default), descend into sub directories.
        check_unicode: If |True| (default), also report invisible characters and
            names that are not NFC normalized.
        follow_symlinks: If |True|, descend into symlinked directories.
        additional_reserved_names: Extra reserved names, case insensitive.

    Returns:
        :py:class:`ScanResult` with one :py:class:`PathReport` per entry.

    Example:
        >>> result = scan_paths("some/dir", platform="windows")
        >>> result.invalid_count
        2
    """

    root_path = Path(root)
    target_platform = normalize_platform(platform if platform else "auto")
    errors: list[tuple[str, str]] = []
    reports: list[PathReport] = []

    if not root_path.exists() and not root_path.is_symlink():
        raise FileNotFoundError(f"no such file or directory: {root_path}")

    if root_path.is_file() or root_path.is_symlink() and not root_path.is_dir():
        parent = root_path.parent
        report = PathReport(
            path=root_path,
            relative=root_path.name,
            issues=tuple(
                _check_component(
                    root_path.name, 0, target_platform, check_unicode, additional_reserved_names
                )
            ),
            is_dir=False,
            is_symlink=root_path.is_symlink(),
        )
        del parent
        return ScanResult(
            root=root_path, platform=target_platform, reports=(report,), errors=tuple(errors)
        )

    for path, is_dir, is_symlink in _iter_tree(root_path, recursive, follow_symlinks, errors):
        relative = path.relative_to(root_path)
        # Every entry reports only its own leaf name. Each directory therefore
        # gets exactly one report, instead of one per file it contains.
        leaf_index = len(relative.parts) - 1
        issues = _check_component(
            relative.parts[leaf_index],
            leaf_index,
            target_platform,
            check_unicode,
            additional_reserved_names,
        )

        reports.append(
            PathReport(
                path=path,
                relative=str(relative),
                issues=tuple(issues),
                is_dir=is_dir,
                is_symlink=is_symlink,
            )
        )

    return ScanResult(
        root=root_path, platform=target_platform, reports=tuple(reports), errors=tuple(errors)
    )


@dataclass(frozen=True)
class Rename:
    """A single planned rename operation."""

    source: Path
    target: Path
    reasons: tuple[str, ...] = ()

    @property
    def depth(self) -> int:
        return len(self.source.parts)

    @property
    def is_case_only(self) -> bool:
        """bool: |True| when only the letter case of the name changes.

        Case insensitive filesystems need a two step rename for these.
        """

        return (
            self.source != self.target
            and str(self.source).casefold() == str(self.target).casefold()
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "target": str(self.target),
            "reasons": list(self.reasons),
        }


class BatchRenameError(OSError):
    """Raised when applying a :py:class:`FixPlan` fails.

    The renames that already succeeded are rolled back before this is raised.
    """

    def __init__(self, message: str, failed: Optional[Rename] = None) -> None:
        super().__init__(message)
        self.failed = failed


@dataclass(frozen=True)
class ApplyResult:
    """The outcome of :py:meth:`FixPlan.apply`."""

    applied: tuple[Rename, ...]
    skipped: tuple[Rename, ...] = ()

    @property
    def changed_count(self) -> int:
        return len(self.applied)


@dataclass
class FixPlan:
    """A set of renames computed by :py:func:`plan_fixes`."""

    root: Path
    platform: Platform
    renames: tuple[Rename, ...] = ()
    unresolved: tuple[tuple[Path, str], ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.renames)

    def __len__(self) -> int:
        return len(self.renames)

    def __iter__(self) -> Iterator[Rename]:
        return iter(self.renames)

    def as_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "platform": self.platform.value,
            "renames": [rename.as_dict() for rename in self.renames],
            "unresolved": [
                {"path": str(path), "reason": reason} for path, reason in self.unresolved
            ],
        }

    def apply(self) -> ApplyResult:
        """Execute the plan.

        Children are renamed before their parent directories, so a planned
        target path stays valid for as long as it is needed.

        Raises:
            BatchRenameError: If any rename fails. Every rename that already
                succeeded is rolled back first.
        """

        applied: list[Rename] = []

        for rename in self.renames:
            try:
                _rename(rename.source, rename.target)
            except OSError as exc:
                for done in reversed(applied):
                    try:
                        _rename(done.target, done.source)
                    except OSError:  # pragma: no cover - best effort rollback
                        pass

                raise BatchRenameError(
                    f"failed to rename {rename.source} -> {rename.target}: {exc}", failed=rename
                ) from exc

            applied.append(rename)

        return ApplyResult(applied=tuple(applied))


def _rename(source: Path, target: Path) -> None:
    if source == target:
        return

    if str(source).casefold() == str(target).casefold():
        # case only rename: go through a temporary name so that case insensitive
        # filesystems actually pick up the change
        temporary = source.with_name(f".pvscan-tmp-{os.getpid()}-{source.name}")
        _os_rename(source, temporary)
        _os_rename(temporary, target)
        return

    _os_rename(source, target)


def _needs_extended_prefix(path: Path) -> bool:
    """Return |True| when a Windows path cannot be reached without ``\\\\?\\``.

    Windows silently strips trailing spaces and dots from a path before handing
    it to the filesystem. A file that *does* carry such a name therefore cannot
    be opened, renamed or deleted through its ordinary path; the extended length
    prefix bypasses that normalization.
    """

    if os.name != "nt":
        return False

    return bool(path.name) and path.name[-1] in (" ", ".")


def _os_rename(source: Path, target: Path) -> None:
    use_prefix = _needs_extended_prefix(source) or _needs_extended_prefix(target)

    if use_prefix:
        os.rename(_extended_path(source), _extended_path(target))
        return

    os.rename(source, target)


def _extended_path(path: Path) -> str:
    # os.path.abspath() strips trailing spaces and dots on Windows, which would
    # silently turn "trail." into "trail". Join the components by hand instead so
    # that the name reaches the filesystem unchanged.
    raw = str(path)
    resolved = raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw)

    if resolved.startswith("\\\\?\\"):
        return resolved

    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]

    return "\\\\?\\" + resolved


def _fix_component(
    component: str,
    platform: Platform,
    replacement_text: str,
    max_len: Optional[int],
    encoding: str,
    fix_invisible: bool,
    normalize_unicode: bool,
    additional_reserved_names: Optional[Sequence[str]],
) -> str:
    # A WSL remapped name has to be decoded *before* sanitizing, otherwise the
    # private use characters survive and the name stays broken on other systems.
    component = decode_wsl_name(component)

    if fix_invisible:
        component = "".join(
            char for char in component if unicodedata.category(char) not in ("Cf", "Cc", "Cs")
        )

    if normalize_unicode:
        component = unicodedata.normalize("NFC", component)

    if not component:
        return "_"

    sanitized = str(
        sanitize_filename(
            component,
            replacement_text=replacement_text,
            platform=platform,
            max_len=-1,
            additional_reserved_names=additional_reserved_names,
        )
    )

    if not sanitized:
        return "_"

    if max_len is not None:
        sanitized = fit_length(sanitized, max_len, encoding)

    return sanitized


def _unique_name(
    candidate: str,
    taken: set[str],
    case_insensitive: bool,
    max_len: Optional[int],
    encoding: str,
) -> str:
    def normalize(value: str) -> str:
        return value.casefold() if case_insensitive else value

    if normalize(candidate) not in taken:
        return candidate

    stem, extension = split_name(candidate)
    counter = 2

    while True:
        suffix = _COLLISION_TMPL.format(counter)
        proposal = f"{stem}{suffix}{extension}"

        if max_len is not None:
            proposal = fit_length(proposal, max_len, encoding)
            # fitting may have eaten the counter; rebuild against the budget
            if normalize(proposal) in taken:
                stem_budget = max_len - _byte_len(suffix + extension, encoding)
                if stem_budget < 1:
                    proposal = truncate_str(f"{counter}{extension}", encoding, max_len)
                else:
                    proposal = truncate_str(stem, encoding, stem_budget) + suffix + extension

        if normalize(proposal) not in taken:
            return proposal

        counter += 1


def plan_fixes(
    scan_result: ScanResult,
    *,
    replacement_text: str = "_",
    max_len: Optional[int] = 255,
    fs_encoding: Optional[str] = None,
    fix_invisible: bool = True,
    normalize_unicode: bool = True,
    resolve_collisions: bool = True,
    additional_reserved_names: Optional[Sequence[str]] = None,
) -> FixPlan:
    """Compute the renames required to make a scanned tree portable.

    Args:
        scan_result: Result of :py:func:`scan_paths`.
        replacement_text: Replacement for invalid characters. Defaults to ``"_"``.
        max_len: Maximum byte length per component, or |None| to leave the
            length untouched. Defaults to ``255``.
        fs_encoding: Encoding used to measure byte lengths. Defaults to the
            filesystem encoding of the running interpreter.
        fix_invisible: Remove invisible formatting characters.
        normalize_unicode: Normalize names to Unicode NFC.
        resolve_collisions: Disambiguate names that would collapse into the same
            target name. Without this, ``"a:b"`` and ``"a|b"`` would both become
            ``"a_b"`` and the second rename would fail.
        additional_reserved_names: Extra reserved names, case insensitive.

    Returns:
        A :py:class:`FixPlan` ordered for bottom-up application.
    """

    encoding = fs_encoding or sys.getfilesystemencoding()
    platform = scan_result.platform
    case_insensitive = _is_case_insensitive(platform)

    # group reports by their parent directory
    children: dict[Path, list[PathReport]] = {}

    for report in scan_result.reports:
        children.setdefault(report.path.parent, []).append(report)

    desired: dict[Path, str] = {}
    reasons: dict[Path, list[str]] = {}
    unresolved: list[tuple[Path, str]] = []

    for report in scan_result.reports:
        if report.is_symlink and report.is_dir:
            # never rewrite the name of a directory symlink target by accident
            desired[report.path] = report.path.name
            continue

        original = report.path.name
        fixed = _fix_component(
            original,
            platform=platform,
            replacement_text=replacement_text,
            max_len=max_len,
            encoding=encoding,
            fix_invisible=fix_invisible,
            normalize_unicode=normalize_unicode,
            additional_reserved_names=additional_reserved_names,
        )

        if fixed == original:
            desired[report.path] = original
            continue

        try:
            validate_filename(
                fixed,
                platform=platform,
                additional_reserved_names=additional_reserved_names,
            )
        except ValidationError as exc:
            unresolved.append((report.path, str(exc)))
            desired[report.path] = original
            continue

        desired[report.path] = fixed
        reasons.setdefault(report.path, []).append("sanitize")

    if resolve_collisions:
        for reports in children.values():
            taken: set[str] = set()
            pending: list[PathReport] = []

            for report in reports:
                if desired[report.path] == report.path.name:
                    key = report.path.name.casefold() if case_insensitive else report.path.name
                    taken.add(key)
                else:
                    pending.append(report)

            for report in sorted(pending, key=lambda item: item.path.name):
                candidate = desired[report.path]
                unique = _unique_name(candidate, taken, case_insensitive, max_len, encoding)

                if unique != candidate:
                    reasons.setdefault(report.path, []).append("collision")

                desired[report.path] = unique
                taken.add(unique.casefold() if case_insensitive else unique)

    renames: list[Rename] = []

    for report in scan_result.reports:
        new_name = desired[report.path]

        if new_name == report.path.name:
            continue

        renames.append(
            Rename(
                source=report.path,
                target=report.path.with_name(new_name),
                reasons=tuple(reasons.get(report.path, ())),
            )
        )

    # deepest first so that a parent rename never invalidates a pending child path
    renames.sort(key=lambda rename: (-rename.depth, str(rename.source)))

    return FixPlan(
        root=scan_result.root,
        platform=platform,
        renames=tuple(renames),
        unresolved=tuple(unresolved),
    )


def apply_fixes(
    root: "os.PathLike[str] | str",
    *,
    platform: Optional[str] = None,
    recursive: bool = True,
    replacement_text: str = "_",
    max_len: Optional[int] = 255,
    fs_encoding: Optional[str] = None,
    check_unicode: bool = True,
    follow_symlinks: bool = False,
    additional_reserved_names: Optional[Sequence[str]] = None,
) -> tuple[ScanResult, FixPlan, ApplyResult]:
    """Scan a tree and immediately apply the resulting fixes.

    This is a thin convenience wrapper around :py:func:`scan_paths`,
    :py:func:`plan_fixes` and :py:meth:`FixPlan.apply`.

    Returns:
        A ``(scan_result, plan, apply_result)`` tuple.
    """

    result = scan_paths(
        root,
        platform=platform,
        recursive=recursive,
        check_unicode=check_unicode,
        follow_symlinks=follow_symlinks,
        additional_reserved_names=additional_reserved_names,
    )
    plan = plan_fixes(
        result,
        replacement_text=replacement_text,
        max_len=max_len,
        fs_encoding=fs_encoding,
        additional_reserved_names=additional_reserved_names,
    )

    return result, plan, plan.apply()


def iter_reports(scan_result: ScanResult, only_problems: bool = True) -> Iterable[PathReport]:
    """Iterate over the reports of a scan, optionally filtering clean entries."""

    for report in scan_result.reports:
        if only_problems and not report.has_issues:
            continue

        yield report
