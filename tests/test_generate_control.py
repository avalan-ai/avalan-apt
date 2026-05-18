"""Tests for scripts/generate_control.

Drives the dep-map → ``debian/control`` Depends-block generator with
fixture inputs so the assertions are deterministic across Avalan
upstream version bumps.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import generate_control as gc


def _fixture_map(*, extras=()) -> str:
    base = textwrap.dedent(
        """\
        [meta]
        upstream_version = "1.0.0"
        homebrew_formula_sha = "fixture"

        [[dep]]
        pypi_name = "widget"
        constraint = ">=1.0,<2.0"
        debian_name = "python3-widget"
        extra = "base"
        source = "noble"
        min_version = "1.0.0"

        [[dep]]
        pypi_name = "alpha"
        constraint = ">=0.5,<1.0"
        debian_name = "python3-alpha"
        extra = "tool"
        source = "ppa"
        provenance = "pypi-sdist"
        sdist_url = "https://example.invalid/alpha-0.5.0.tar.gz"
        sdist_sha256 = "deadbeef"
        min_version = "0.5.0"
        """
    )
    for extra in extras:
        base += extra
    return base


def test_parse_map_sorts_by_debian_name() -> None:
    rows = gc.parse_map(_fixture_map())
    assert [r.debian_name for r in rows] == [
        "python3-alpha",
        "python3-widget",
    ]
    assert [r.min_version for r in rows] == ["0.5.0", "1.0.0"]


def test_render_formats_one_per_line_with_lower_bound() -> None:
    rows = gc.parse_map(_fixture_map())
    out = gc.render(rows)
    assert out == (
        " python3-alpha (>= 0.5.0),\n"
        " python3-widget (>= 1.0.0),"
    )


def test_replace_block_drops_in_between_sentinels() -> None:
    control = (
        "Depends:\n"
        " ${misc:Depends},\n"
        "# BEGIN generated-depends\n"
        " python3-stale (>= 0.0.0),\n"
        "# END generated-depends\n"
        "Suggests: chromium\n"
    )
    new = gc.replace_block(control, " python3-fresh (>= 9.9.9),")
    assert "stale" not in new
    assert " python3-fresh (>= 9.9.9)," in new
    # Surrounding non-block content untouched.
    assert "Depends:" in new
    assert "Suggests: chromium" in new


def test_replace_block_empty_body_collapses() -> None:
    control = (
        "# BEGIN generated-depends\n"
        " python3-old (>= 0.0.0),\n"
        "# END generated-depends\n"
    )
    new = gc.replace_block(control, "")
    assert new == "# BEGIN generated-depends\n# END generated-depends\n"


def test_replace_block_idempotent_on_unchanged_content() -> None:
    block = " python3-x (>= 1.0),"
    control = (
        "# BEGIN generated-depends\n"
        f"{block}\n"
        "# END generated-depends\n"
    )
    assert gc.replace_block(control, block) == control


def test_replace_block_requires_both_sentinels() -> None:
    with pytest.raises(ValueError, match="sentinels"):
        gc.replace_block("Depends:\n ${misc:Depends},\n", "x")


def test_main_update_writes_in_place(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    map_path = tmp_path / "debian" / "dependency-map.toml"
    map_path.parent.mkdir(parents=True)
    map_path.write_text(_fixture_map())

    control_path = tmp_path / "debian" / "control"
    control_path.write_text(
        "Source: avalan\n"
        "Depends:\n"
        " ${misc:Depends},\n"
        "# BEGIN generated-depends\n"
        "# END generated-depends\n"
        "Suggests: chromium\n"
    )

    rc = gc.main(
        [
            "--map",
            str(map_path),
            "--control",
            str(control_path),
            "--update",
        ]
    )
    assert rc == 0
    text = control_path.read_text()
    assert " python3-alpha (>= 0.5.0),\n" in text
    assert " python3-widget (>= 1.0.0),\n" in text
    # Block still bracketed by sentinels.
    assert text.index("BEGIN") < text.index("python3-alpha")
    assert text.index("python3-widget") < text.index("END")


def test_main_default_mode_prints_block(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    map_path = tmp_path / "debian" / "dependency-map.toml"
    map_path.parent.mkdir(parents=True)
    map_path.write_text(_fixture_map())
    rc = gc.main(["--map", str(map_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert " python3-alpha (>= 0.5.0),\n" in out
    assert " python3-widget (>= 1.0.0)," in out


def test_parse_map_skips_transitive_rows() -> None:
    # Transitive rows get pulled into the install set via the parent's
    # wheel Requires-Dist (through ${python3:Depends}); the generator
    # must not list them again in debian/control.
    map_text = _fixture_map() + textwrap.dedent(
        """\

        [[dep]]
        pypi_name = "tag-along"
        constraint = ">=1.0,<2.0"
        debian_name = "python3-tag-along"
        extra = "vendors"
        transitive_of = "widget"
        source = "ppa"
        provenance = "pypi-sdist"
        sdist_url = "https://example.invalid/tag-along-1.0.tar.gz"
        sdist_sha256 = "deadbeef"
        min_version = "1.0.0"
        """
    )
    names = [r.debian_name for r in gc.parse_map(map_text)]
    assert "python3-tag-along" not in names
    assert "python3-widget" in names
    assert "python3-alpha" in names
