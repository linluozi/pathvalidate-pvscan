"""
Tests for the batch scanning helpers.

The expectations here are concrete strings and concrete file system states, not
shape assertions: ``isinstance(x, str)`` would pass for a completely broken
implementation.
"""

import os
import sys

import pytest

from pathvalidate.batch import (
    BatchRenameError,
    _extended_path,
    apply_fixes,
    decode_wsl_name,
    fit_length,
    has_wsl_mapping,
    plan_fixes,
    scan_paths,
    split_name,
)

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win") and os.environ.get("PVSCAN_SKIP_FS") == "1",
    reason="filesystem tests disabled",
)


def _wsl(name: str) -> str:
    """Build a name the way WSL stores forbidden characters on NTFS."""

    table = {char: chr(0xF000 + ord(char)) for char in '<>:"/\\|?*'}

    return "".join(table.get(char, char) for char in name)


class Test_split_name:
    @pytest.mark.parametrize(
        ["name", "expected"],
        [
            ("archive.tar.gz", ("archive", ".tar.gz")),
            ("photo.jpeg", ("photo", ".jpeg")),
            ("notes", ("notes", "")),
            (".bashrc", (".bashrc", "")),
            ("..", ("..", "")),
            (".", (".", "")),
            ("", ("", "")),
            ("a.", ("a.", "")),
            ("a.b.c.d.e", ("a.b", ".c.d.e")),
            ("UPPER.TXT", ("UPPER", ".TXT")),
        ],
    )
    def test_split_name(self, name, expected):
        assert split_name(name) == expected

    def test_round_trip(self):
        for name in ("archive.tar.gz", "notes", ".bashrc", "a.b.c.d.e"):
            stem, extension = split_name(name)
            assert stem + extension == name


class Test_fit_length:
    def test_preserves_compound_extension(self):
        name = "a" * 250 + ".tar.gz"
        fitted = fit_length(name, 255, "utf-8")

        assert len(fitted.encode("utf-8")) == 255
        assert fitted.endswith(".tar.gz")
        # 255 bytes - 7 bytes for ".tar.gz" = 248 characters
        assert fitted == "a" * 248 + ".tar.gz"

    def test_short_name_untouched(self):
        assert fit_length("photo.jpeg", 255, "utf-8") == "photo.jpeg"

    def test_multibyte_is_measured_in_bytes(self):
        name = "中" * 200 + ".txt"
        fitted = fit_length(name, 60, "utf-8")

        assert len(fitted.encode("utf-8")) <= 60
        assert fitted.endswith(".txt")
        # 60 - 4 bytes for ".txt" = 56 bytes = 18 three byte characters
        assert fitted == "中" * 18 + ".txt"

    def test_extension_longer_than_budget(self):
        fitted = fit_length("name.tar.gz", 4, "utf-8")

        assert len(fitted.encode("utf-8")) <= 4

    def test_no_extension_still_truncates(self):
        fitted = fit_length("x" * 300, 10, "utf-8")

        assert fitted == "x" * 10

    def test_disabled_budget(self):
        assert fit_length("x" * 300, -1, "utf-8") == "x" * 300


class Test_wsl_mapping:
    def test_decode(self):
        assert decode_wsl_name(_wsl("a|b.txt")) == "a|b.txt"
        assert decode_wsl_name(_wsl("sub:dir")) == "sub:dir"
        assert decode_wsl_name("plain.txt") == "plain.txt"

    def test_decode_leaves_unrelated_pua_alone(self):
        # U+F8FF is in the private use area but is not a WSL remap
        assert decode_wsl_name("a\uf8ffb") == "a\uf8ffb"

    def test_has_mapping(self):
        assert has_wsl_mapping(_wsl("a|b.txt")) is True
        assert has_wsl_mapping("a|b.txt") is False
        assert has_wsl_mapping("\uf8ff") is False


class Test_scan_paths:
    def test_missing_path(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            scan_paths(tmp_path / "does-not-exist")

    def test_clean_tree(self, tmp_path):
        (tmp_path / "ok.txt").write_text("x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "deep.txt").write_text("x")

        result = scan_paths(tmp_path, platform="windows")

        assert len(result.reports) == 3
        assert result.invalid_count == 0
        assert result.problem_count == 0

    def test_reports_leaf_only(self, tmp_path):
        bad_dir = tmp_path / _wsl("sub:dir")
        bad_dir.mkdir()
        (bad_dir / "ok.txt").write_text("x")

        result = scan_paths(tmp_path, platform="windows")

        assert result.problem_count == 1
        report = next(item for item in result.reports if item.has_issues)
        assert report.relative == _wsl("sub:dir")
        assert report.is_dir is True
        assert [issue.kind for issue in report.issues] == ["WSL_MAPPED_CHARACTER"]

    def test_reserved_name_is_error(self, tmp_path):
        (tmp_path / "CON.txt").write_text("x")

        result = scan_paths(tmp_path, platform="windows")

        report = result.reports[0]
        assert report.is_valid is False
        assert report.errors[0].code == "PV1002"
        assert report.errors[0].kind == "RESERVED_NAME"

    def test_reserved_name_ok_on_linux(self, tmp_path):
        (tmp_path / "CON.txt").write_text("x")

        result = scan_paths(tmp_path, platform="linux")

        assert result.invalid_count == 0
        assert result.problem_count == 0

    def test_trailing_dot_is_error_on_windows(self, tmp_path):
        # A trailing dot cannot be created through the ordinary path API on
        # Windows (it is stripped), so use the extended length prefix, which is
        # exactly the case the scanner has to cope with in the wild.
        name = "trail."
        target = _extended_path(tmp_path / name)
        os.close(os.open(target, os.O_CREAT | os.O_WRONLY))

        try:
            result = scan_paths(tmp_path, platform="windows")

            assert result.invalid_count == 1
            assert result.reports[0].errors[0].kind == "INVALID_CHARACTER"
        finally:
            os.unlink(target)

    def test_invisible_character_is_warning(self, tmp_path):
        (tmp_path / "inv\u200bisible.txt").write_text("x")

        result = scan_paths(tmp_path, platform="windows")

        report = result.reports[0]
        assert report.is_valid is True
        assert report.warnings[0].code == "PVX001"
        assert report.warnings[0].kind == "INVISIBLE_CHARACTER"

    def test_unicode_check_can_be_disabled(self, tmp_path):
        (tmp_path / "inv\u200bisible.txt").write_text("x")

        result = scan_paths(tmp_path, platform="windows", check_unicode=False)

        assert result.problem_count == 0

    def test_unnormalized_unicode_is_warning(self, tmp_path):
        import unicodedata

        name = unicodedata.normalize("NFD", "café.txt")
        (tmp_path / name).write_text("x")

        result = scan_paths(tmp_path, platform="windows")

        kinds = [issue.kind for issue in result.reports[0].issues]
        assert "UNNORMALIZED_UNICODE" in kinds

    def test_non_recursive(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "CON.txt").write_text("x")

        result = scan_paths(tmp_path, platform="windows", recursive=False)

        assert len(result.reports) == 1
        assert result.reports[0].relative == "sub"

    def test_single_file(self, tmp_path):
        target = tmp_path / "CON.txt"
        target.write_text("x")

        result = scan_paths(target, platform="windows")

        assert len(result.reports) == 1
        assert result.reports[0].relative == "CON.txt"
        assert result.reports[0].is_dir is False

    def test_as_dict_is_json_serializable(self, tmp_path):
        import json

        (tmp_path / "CON.txt").write_text("x")

        payload = scan_paths(tmp_path, platform="windows").as_dict()
        rendered = json.dumps(payload)

        assert '"invalid": 1' in rendered
        assert '"kind": "RESERVED_NAME"' in rendered


class Test_plan_fixes:
    def test_no_changes_for_clean_tree(self, tmp_path):
        (tmp_path / "ok.txt").write_text("x")

        result = scan_paths(tmp_path, platform="windows")
        plan = plan_fixes(result)

        assert plan.has_changes is False
        assert len(plan) == 0

    def test_reserved_name_gets_underscore(self, tmp_path):
        (tmp_path / "CON.txt").write_text("x")

        plan = plan_fixes(scan_paths(tmp_path, platform="windows"))

        assert len(plan) == 1
        assert plan.renames[0].target.name == "CON_.txt"

    def test_collision_is_disambiguated(self, tmp_path):
        (tmp_path / _wsl("a|b.txt")).write_text("one")
        (tmp_path / _wsl("a?b.txt")).write_text("two")

        plan = plan_fixes(scan_paths(tmp_path, platform="windows"))
        targets = sorted(rename.target.name for rename in plan)

        assert targets == ["a_b (2).txt", "a_b.txt"]
        assert len(set(targets)) == 2

    def test_collision_check_can_be_disabled(self, tmp_path):
        (tmp_path / _wsl("a|b.txt")).write_text("one")
        (tmp_path / _wsl("a?b.txt")).write_text("two")

        plan = plan_fixes(scan_paths(tmp_path, platform="windows"), resolve_collisions=False)
        targets = [rename.target.name for rename in plan]

        assert targets == ["a_b.txt", "a_b.txt"]

    def test_collision_with_existing_file(self, tmp_path):
        # the clean "a_b.txt" is already taken, so the fix must avoid it
        (tmp_path / "a_b.txt").write_text("taken")
        (tmp_path / _wsl("a|b.txt")).write_text("bad")

        plan = plan_fixes(scan_paths(tmp_path, platform="windows"))

        assert [rename.target.name for rename in plan] == ["a_b (2).txt"]

    def test_children_before_parents(self, tmp_path):
        parent = tmp_path / _wsl("p:dir")
        parent.mkdir()
        (parent / _wsl("c:1.txt")).write_text("x")

        plan = plan_fixes(scan_paths(tmp_path, platform="windows"))

        assert len(plan) == 2
        assert plan.renames[0].source.name == _wsl("c:1.txt")
        assert plan.renames[1].source.name == _wsl("p:dir")

    def test_max_len_is_applied(self, tmp_path):
        (tmp_path / ("y" * 100 + ".tar.gz")).write_text("x")

        plan = plan_fixes(scan_paths(tmp_path, platform="windows"), max_len=40)
        target = plan.renames[0].target.name

        assert len(target.encode("utf-8")) == 40
        assert target.endswith(".tar.gz")

    def test_max_len_none_keeps_long_name(self, tmp_path):
        (tmp_path / ("y" * 100 + ".txt")).write_text("x")

        plan = plan_fixes(scan_paths(tmp_path, platform="windows"), max_len=None)

        assert plan.has_changes is False

    def test_reasons_are_recorded(self, tmp_path):
        (tmp_path / _wsl("a|b.txt")).write_text("one")
        (tmp_path / _wsl("a?b.txt")).write_text("two")

        plan = plan_fixes(scan_paths(tmp_path, platform="windows"))
        by_target = {rename.target.name: rename.reasons for rename in plan}

        assert by_target["a_b.txt"] == ("sanitize",)
        assert by_target["a_b (2).txt"] == ("sanitize", "collision")

    def test_wsl_name_is_decoded_then_sanitized(self, tmp_path):
        # ":" is legal on POSIX but not on Windows, so decoding and sanitizing
        # must both happen: the result may not keep the private use character.
        (tmp_path / _wsl("a:b.txt")).write_text("x")

        plan = plan_fixes(scan_paths(tmp_path, platform="windows"))
        target = plan.renames[0].target.name

        assert target == "a_b.txt"
        assert not any(0xF000 <= ord(char) <= 0xF0FF for char in target)


class Test_apply:
    def test_apply_changes_filesystem(self, tmp_path):
        (tmp_path / "CON.txt").write_text("x")

        result = scan_paths(tmp_path, platform="windows")
        plan = plan_fixes(result)
        applied = plan.apply()

        assert applied.changed_count == 1
        assert sorted(path.name for path in tmp_path.iterdir()) == ["CON_.txt"]

    def test_apply_is_idempotent(self, tmp_path):
        (tmp_path / "CON.txt").write_text("x")

        apply_fixes(tmp_path, platform="windows")
        second = apply_fixes(tmp_path, platform="windows")

        assert second[1].has_changes is False
        assert sorted(path.name for path in tmp_path.iterdir()) == ["CON_.txt"]

    def test_nested_tree_is_fully_repaired(self, tmp_path):
        parent = tmp_path / _wsl("p:dir")
        parent.mkdir()
        (parent / _wsl("c|1.txt")).write_text("x")
        (parent / "keep.txt").write_text("x")

        _, _, applied = apply_fixes(tmp_path, platform="windows")

        assert applied.changed_count == 2
        assert (tmp_path / "p_dir" / "c_1.txt").exists()
        assert (tmp_path / "p_dir" / "keep.txt").exists()

        recheck = scan_paths(tmp_path, platform="windows")
        assert recheck.invalid_count == 0
        assert recheck.problem_count == 0

    def test_rollback_on_failure(self, tmp_path, monkeypatch):
        (tmp_path / "CON.txt").write_text("x")
        (tmp_path / "NUL.txt").write_text("x")

        plan = plan_fixes(scan_paths(tmp_path, platform="windows"))
        assert len(plan) == 2

        calls = {"count": 0}
        original = os.rename

        def flaky_rename(src, dst):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("simulated failure")
            return original(src, dst)

        monkeypatch.setattr(os, "rename", flaky_rename)

        with pytest.raises(BatchRenameError):
            plan.apply()

        monkeypatch.setattr(os, "rename", original)

        names = sorted(path.name for path in tmp_path.iterdir())
        assert names == ["CON.txt", "NUL.txt"]

    def test_trailing_space_file_is_repairable(self, tmp_path):
        # "lead " is only reachable through the extended prefix on Windows
        name = "lead "
        target = _extended_path(tmp_path / name)
        os.close(os.open(target, os.O_CREAT | os.O_WRONLY))

        try:
            result = scan_paths(tmp_path, platform="windows")
            assert result.invalid_count == 1

            plan = plan_fixes(result)
            assert [rename.target.name for rename in plan] == ["lead"]

            plan.apply()
            assert sorted(path.name for path in tmp_path.iterdir()) == ["lead"]
            assert scan_paths(tmp_path, platform="windows").invalid_count == 0
        finally:
            leftover = tmp_path / "lead"
            if leftover.exists():
                leftover.unlink()


class Test_public_api:
    def test_exports(self):
        import pathvalidate

        for name in (
            "scan_paths",
            "plan_fixes",
            "apply_fixes",
            "split_name",
            "fit_length",
            "decode_wsl_name",
            "has_wsl_mapping",
            "ScanResult",
            "FixPlan",
            "Rename",
            "Issue",
            "PathReport",
            "ApplyResult",
            "BatchRenameError",
        ):
            assert hasattr(pathvalidate, name), name

    def test_upstream_behaviour_is_unchanged(self):
        # the batch layer must not alter the documented single name behaviour
        import pathvalidate

        assert pathvalidate.sanitize_filename("CON.txt", platform="windows") == "CON_.txt"
        assert pathvalidate.sanitize_filename("a|b", platform="linux") == "a|b"
        assert pathvalidate.is_valid_filename("a|b", platform="windows") is False
