"""
Tests for the ``pvscan`` command line interface.

Every test asserts on concrete output fragments and on the resulting file system
state. The read only guarantee of ``check`` is verified by snapshotting the
directory listing before and after.
"""

import json
import os

import pytest

from pathvalidate._cli import main
from pathvalidate.batch import _extended_path


def _run(argv, capsys):
    code = main(argv)
    captured = capsys.readouterr()

    return code, captured.out, captured.err


def _listing(path):
    return sorted(entry.name for entry in os.scandir(path))


def _make_bad_tree(root):
    (root / "CON.txt").write_text("x")
    (root / "ok.txt").write_text("x")
    bad = root / "sub\uf03adir"
    bad.mkdir()
    (bad / "inner\uf03c1\uf03e.log").write_text("x")


class Test_check:
    def test_clean_tree_exits_zero(self, tmp_path, capsys):
        (tmp_path / "ok.txt").write_text("x")

        code, out, _ = _run(["check", str(tmp_path), "--platform", "windows"], capsys)

        assert code == 0
        assert "1 scanned, 0 invalid" in out

    def test_invalid_tree_exits_one(self, tmp_path, capsys):
        (tmp_path / "CON.txt").write_text("x")

        code, out, _ = _run(["check", str(tmp_path), "--platform", "windows"], capsys)

        assert code == 1
        assert "RESERVED_NAME" in out
        assert "CON.txt" in out

    def test_check_is_read_only(self, tmp_path, capsys):
        _make_bad_tree(tmp_path)
        before = _listing(tmp_path)

        code, _, _ = _run(["check", str(tmp_path), "--platform", "windows"], capsys)

        assert code == 1
        assert _listing(tmp_path) == before

    def test_quiet_prints_only_summary(self, tmp_path, capsys):
        (tmp_path / "CON.txt").write_text("x")

        _, out, _ = _run(["check", str(tmp_path), "--platform", "windows", "--quiet"], capsys)

        lines = [line for line in out.splitlines() if line.strip()]
        assert len(lines) == 1
        assert "1 scanned, 1 invalid" in lines[0]

    def test_fail_on_never(self, tmp_path, capsys):
        (tmp_path / "CON.txt").write_text("x")

        code, _, _ = _run(
            ["check", str(tmp_path), "--platform", "windows", "--fail-on", "never"], capsys
        )

        assert code == 0

    def test_fail_on_warning(self, tmp_path, capsys):
        (tmp_path / "inv\u200bisible.txt").write_text("x")

        code, _, _ = _run(
            ["check", str(tmp_path), "--platform", "windows", "--fail-on", "warning"], capsys
        )

        assert code == 1

    def test_warning_only_is_not_invalid(self, tmp_path, capsys):
        (tmp_path / "inv\u200bisible.txt").write_text("x")

        code, out, _ = _run(["check", str(tmp_path), "--platform", "windows"], capsys)

        assert code == 0
        assert "0 invalid, 1 with issues" in out

    def test_matrix(self, tmp_path, capsys):
        (tmp_path / "CON.txt").write_text("x")

        _, out, _ = _run(["check", str(tmp_path), "--platform", "windows", "--matrix"], capsys)

        assert "Windows=FAIL" in out
        assert "Linux=ok" in out
        assert "macOS=ok" in out

    def test_json_output(self, tmp_path, capsys):
        (tmp_path / "CON.txt").write_text("x")

        _, out, _ = _run(["check", str(tmp_path), "--platform", "windows", "--json"], capsys)
        payload = json.loads(out)

        assert payload["results"][0]["invalid"] == 1
        entry = payload["results"][0]["entries"][0]
        assert entry["relative"] == "CON.txt"
        assert entry["issues"][0]["kind"] == "RESERVED_NAME"

    def test_invisible_characters_are_escaped_in_output(self, tmp_path, capsys):
        (tmp_path / "inv\u200bisible.txt").write_text("x")

        _, out, _ = _run(["check", str(tmp_path), "--platform", "windows"], capsys)

        # the raw zero width space must not be printed verbatim
        assert "\u200b" not in out
        assert "\\u200b" in out

    def test_missing_path_exits_usage(self, tmp_path, capsys):
        code, _, err = _run(["check", str(tmp_path / "nope")], capsys)

        assert code == 2
        assert "no such file" in err

    def test_no_recursive(self, tmp_path, capsys):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "CON.txt").write_text("x")

        code, _, _ = _run(
            ["check", str(tmp_path), "--platform", "windows", "--no-recursive"], capsys
        )

        assert code == 0

    def test_extra_reserved_name(self, tmp_path, capsys):
        (tmp_path / "private.txt").write_text("x")

        code, out, _ = _run(
            ["check", str(tmp_path), "--platform", "linux", "--reserved", "private"], capsys
        )

        assert code == 1
        assert "RESERVED_NAME" in out


class Test_fix:
    def test_dry_run_does_not_touch_filesystem(self, tmp_path, capsys):
        _make_bad_tree(tmp_path)
        before = _listing(tmp_path)

        code, out, _ = _run(["fix", str(tmp_path), "--platform", "windows"], capsys)

        assert code == 0
        assert "dry run" in out
        assert _listing(tmp_path) == before

    def test_apply_renames(self, tmp_path, capsys):
        (tmp_path / "CON.txt").write_text("x")

        code, out, _ = _run(["fix", str(tmp_path), "--platform", "windows", "--apply"], capsys)

        assert code == 0
        assert "applied 1 rename" in out
        assert _listing(tmp_path) == ["CON_.txt"]

    def test_apply_nested_tree(self, tmp_path, capsys):
        _make_bad_tree(tmp_path)

        code, _, _ = _run(["fix", str(tmp_path), "--platform", "windows", "--apply"], capsys)

        assert code == 0
        assert _listing(tmp_path) == ["CON_.txt", "ok.txt", "sub_dir"]
        assert _listing(tmp_path / "sub_dir") == ["inner_1_.log"]

    def test_nothing_to_fix(self, tmp_path, capsys):
        (tmp_path / "ok.txt").write_text("x")

        code, out, _ = _run(["fix", str(tmp_path), "--platform", "windows"], capsys)

        assert code == 0
        assert "nothing to fix" in out

    def test_custom_replacement(self, tmp_path, capsys):
        (tmp_path / "sub\uf03adir").mkdir()

        _run(
            [
                "fix",
                str(tmp_path),
                "--platform",
                "windows",
                "--replacement",
                "-",
                "--apply",
            ],
            capsys,
        )

        assert _listing(tmp_path) == ["sub-dir"]

    def test_max_len(self, tmp_path, capsys):
        (tmp_path / ("z" * 80 + ".tar.gz")).write_text("x")

        _run(
            ["fix", str(tmp_path), "--platform", "windows", "--max-len", "40", "--apply"],
            capsys,
        )

        (name,) = _listing(tmp_path)
        assert len(name.encode()) == 40
        assert name.endswith(".tar.gz")

    def test_json_dry_run(self, tmp_path, capsys):
        (tmp_path / "CON.txt").write_text("x")

        _, out, _ = _run(["fix", str(tmp_path), "--platform", "windows", "--json"], capsys)
        payload = json.loads(out)

        assert payload["applied"] is False
        assert payload["renames"][0]["target"].endswith("CON_.txt")

    def test_json_apply(self, tmp_path, capsys):
        (tmp_path / "CON.txt").write_text("x")

        _, out, _ = _run(
            ["fix", str(tmp_path), "--platform", "windows", "--json", "--apply"], capsys
        )
        payload = json.loads(out)

        assert payload["applied"] is True
        assert len(payload["renamed"]) == 1
        assert _listing(tmp_path) == ["CON_.txt"]

    def test_apply_is_idempotent(self, tmp_path, capsys):
        (tmp_path / "CON.txt").write_text("x")

        _run(["fix", str(tmp_path), "--platform", "windows", "--apply"], capsys)
        code, out, _ = _run(["fix", str(tmp_path), "--platform", "windows", "--apply"], capsys)

        assert code == 0
        assert "nothing to fix" in out

    def test_trailing_space_apply(self, tmp_path, capsys):
        target = _extended_path(tmp_path / "lead ")
        os.close(os.open(target, os.O_CREAT | os.O_WRONLY))

        code, _, _ = _run(["fix", str(tmp_path), "--platform", "windows", "--apply"], capsys)

        assert code == 0
        assert _listing(tmp_path) == ["lead"]

    def test_missing_path_exits_usage(self, tmp_path, capsys):
        code, _, err = _run(["fix", str(tmp_path / "nope")], capsys)

        assert code == 2
        assert "no such file" in err


class Test_argument_parsing:
    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])

        assert exc.value.code == 0
        assert "pvscan" in capsys.readouterr().out

    def test_requires_subcommand(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main([])

        assert exc.value.code == 2

    def test_unknown_platform_falls_back_to_universal(self, tmp_path, capsys):
        (tmp_path / "ok.txt").write_text("x")

        code, out, _ = _run(["check", str(tmp_path), "--platform", "beos"], capsys)

        assert code == 0
        assert "universal" in out

    def test_default_path_is_cwd(self, tmp_path, capsys, monkeypatch):
        (tmp_path / "ok.txt").write_text("x")
        monkeypatch.chdir(tmp_path)

        code, out, _ = _run(["check", "--platform", "windows"], capsys)

        assert code == 0
        assert "1 scanned" in out
