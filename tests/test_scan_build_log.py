"""Tests for scripts/scan_build_log.

The scanner reads a captured build log and exits non-zero on any
forbidden network call (pip install, easy_install, direct PyPI fetch,
...). Tests cover both the in-memory ``scan_lines`` helper and the
CLI ``main`` entry point so the script can be exercised on dev hosts
without driving a real Debian build.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

import scan_build_log as sbl


def test_clean_log_passes() -> None:
    lines = [
        "+ cd build/avalan-1.4.8",
        "+ dpkg-buildpackage -b -us -uc",
        "dpkg-buildpackage: info: source package avalan",
        "dh build --buildsystem=pybuild",
        "dh_auto_build -O--buildsystem=pybuild",
        "I: pybuild base:311: python3.12 -m build",
    ]
    assert sbl.scan_lines(lines) == []


@pytest.mark.parametrize(
    "line, description_fragment",
    [
        ("+ pip install foo", "pip install"),
        ("+ pip3 install bar", "pip install"),
        ("+ python -m pip install baz", "python -m pip install"),
        ("+ python3 -m pip install qux", "python -m pip install"),
        ("+ easy_install some-pkg", "easy_install"),
        ("+ python setup.py install", "setup.py install"),
        (
            "fetching https://files.pythonhosted.org/packages/...",
            "pythonhosted.org",
        ),
        ("downloading from https://pypi.org/simple/...", "pypi.org"),
    ],
)
def test_forbidden_patterns_match(
    line: str, description_fragment: str
) -> None:
    hits = sbl.scan_lines([line])
    assert len(hits) == 1, hits
    assert hits[0].lineno == 1
    assert hits[0].text == line
    assert description_fragment in hits[0].description


def test_multiple_hits_report_lineno() -> None:
    lines = [
        "first line ok",
        "+ pip install one",
        "another ok line",
        "+ easy_install two",
    ]
    hits = sbl.scan_lines(lines)
    assert [h.lineno for h in hits] == [2, 4]


def test_one_hit_per_line_even_if_multi_pattern() -> None:
    # A pathological line matching multiple patterns should still
    # produce a single hit so the report is not noisy.
    lines = ["+ python -m pip install setup.py install"]
    hits = sbl.scan_lines(lines)
    assert len(hits) == 1


def test_allow_substring_suppresses_hit() -> None:
    line = "ImportError: install jiter with 'pip install jiter'"
    hits = sbl.scan_lines([line], allow=("pip install jiter",))
    assert hits == []


def test_allow_substring_only_matches_literal() -> None:
    # An allow entry for 'foo' must not silence a 'pip install bar'
    # line just because 'foo' is unrelated.
    line = "+ pip install bar"
    hits = sbl.scan_lines([line], allow=("foo",))
    assert len(hits) == 1


def test_main_clean_log_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "build.log"
    log.write_text("dh build --buildsystem=pybuild\nOK\n")
    rc = sbl.main([str(log)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK" in captured.out
    assert captured.err == ""


def test_main_forbidden_log_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "build.log"
    log.write_text(
        "configuring\n+ pip install requests\ndone\n"
    )
    rc = sbl.main([str(log)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "FAIL" in captured.err
    assert "pip install" in captured.err
    assert "build.log:2:" in captured.err


def test_main_reads_stdin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = "ok\n+ pip install junk\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    rc = sbl.main(["-"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "stdin:2:" in captured.err


def test_main_allow_flag_repeatable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "build.log"
    log.write_text(
        "hint: run 'pip install jiter'\n"
        "hint: run 'pip install httpx'\n"
        "+ pip install bad\n"
    )
    rc = sbl.main(
        [
            str(log),
            "--allow",
            "pip install jiter",
            "--allow",
            "pip install httpx",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "pip install bad" in captured.err
    # The two allowed lines must not show up in the failure report.
    assert "pip install jiter" not in captured.err
    assert "pip install httpx" not in captured.err
