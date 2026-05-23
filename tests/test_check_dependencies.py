"""Tests for scripts/check_dependencies.

The script audits debian/dependency-map.toml against three reference
inputs:

  - the Homebrew formula (parity baseline for which extras the package
    ships),
  - the upstream sdist's pyproject.toml (authoritative dependency
    constraints),
  - apt-cache madison results for noble and the configured PPA index.

Tests run entirely off fixtures so they work on macOS dev hosts without
a Noble chroot.
"""

import textwrap
from pathlib import Path

import check_dependencies as cd

FIXTURES = Path(__file__).parent / "fixtures"


def _pypi_sdist_map() -> str:
    return textwrap.dedent(
        """\
        [meta]
        upstream_version = "0.0.0"
        homebrew_formula_sha = "fixture"

        [[dep]]
        pypi_name = "widget"
        constraint = ">=1.0,<2.0"
        debian_name = "python3-widget"
        extra = "base"
        source = "ppa"
        provenance = "pypi-sdist"
        sdist_url = "https://example.invalid/widget-1.0.tar.gz"
        sdist_sha256 = "deadbeef"
        min_version = "1.0"
        """
    )


def _ok_args(**overrides):
    args = {
        "formula": str(FIXTURES / "formula_ok.rb"),
        "pyproject": str(FIXTURES / "pyproject_ok.toml"),
        "map": str(FIXTURES / "depmap_ok.toml"),
        "apt_fixture": str(FIXTURES / "apt_cache_ok.json"),
        "ppa_fixture": str(FIXTURES / "ppa_index_ok.json"),
    }
    args.update(overrides)
    return [
        f"--{k.replace('_', '-')}={v}"
        for k, v in args.items()
        if v is not None
    ]


def _run(capsys, **overrides):
    rc = cd.main(_ok_args(**overrides))
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_happy_path_exits_zero(capsys):
    rc, stdout, stderr = _run(capsys)
    assert rc == 0, f"expected 0, got {rc}\nstdout: {stdout}\nstderr: {stderr}"


def test_unknown_source_fails(capsys):
    rc, _, stderr = _run(
        capsys, map=str(FIXTURES / "depmap_unknown.toml")
    )
    assert rc == 1
    assert "rich" in stderr
    assert "unknown" in stderr


def test_missing_row_for_default_extra_fails(capsys):
    rc, _, stderr = _run(
        capsys, map=str(FIXTURES / "depmap_missing_row.toml")
    )
    assert rc == 1
    # The pyproject default profile lists jinja2 (via the `agent`
    # extra); the script must call that out.
    assert "jinja2" in stderr


def test_constraint_mismatch_fails(capsys):
    rc, _, stderr = _run(
        capsys, map=str(FIXTURES / "depmap_bad_constraint.toml")
    )
    assert rc == 1
    assert "jinja2" in stderr
    assert "constraint" in stderr


def test_ppa_row_without_provenance_fails(capsys):
    rc, _, stderr = _run(
        capsys, map=str(FIXTURES / "depmap_ppa_no_provenance.toml")
    )
    assert rc == 1
    assert "fastapi" in stderr
    assert "provenance" in stderr


def test_noble_version_below_floor_fails(capsys):
    rc, _, stderr = _run(
        capsys, apt_fixture=str(FIXTURES / "apt_cache_below_floor.json")
    )
    assert rc == 1
    assert "python3-rich" in stderr
    assert "below floor" in stderr


def test_live_ppa_uses_apt_query_for_ppa_rows(capsys):
    # When --live-ppa is set, the same apt fixture is reused for both
    # noble and ppa rows -- mirroring apt-cache madison's behaviour on
    # a Noble host with the PPA configured.
    rc = cd.main(
        [
            f"--formula={FIXTURES / 'formula_ok.rb'}",
            f"--pyproject={FIXTURES / 'pyproject_ok.toml'}",
            f"--map={FIXTURES / 'depmap_ok.toml'}",
            f"--apt-fixture={FIXTURES / 'apt_cache_live_ppa_ok.json'}",
            "--live-ppa",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, f"{captured.out}\n{captured.err}"


def test_live_ppa_missing_package_fails(capsys):
    rc = cd.main(
        [
            f"--formula={FIXTURES / 'formula_ok.rb'}",
            f"--pyproject={FIXTURES / 'pyproject_ok.toml'}",
            f"--map={FIXTURES / 'depmap_ok.toml'}",
            f"--apt-fixture={FIXTURES / 'apt_cache_live_ppa_missing.json'}",
            "--live-ppa",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "python3-fastapi" in captured.err
    assert "PPA" in captured.err


def test_live_ppa_conflicts_with_ppa_fixture(capsys):
    import pytest

    with pytest.raises(SystemExit):
        cd.main(
            [
                f"--formula={FIXTURES / 'formula_ok.rb'}",
                f"--pyproject={FIXTURES / 'pyproject_ok.toml'}",
                f"--map={FIXTURES / 'depmap_ok.toml'}",
                f"--apt-fixture={FIXTURES / 'apt_cache_ok.json'}",
                f"--ppa-fixture={FIXTURES / 'ppa_index_ok.json'}",
                "--live-ppa",
            ]
        )
    captured = capsys.readouterr()
    assert "mutually exclusive" in captured.err


def test_unit_homebrew_formula_parser():
    text = (FIXTURES / "formula_ok.rb").read_text()
    snap = cd.parse_homebrew_formula(text)
    assert snap.version == "1.4.7"
    assert snap.sha256 == (
        "0f12d0786ace337c665e2ed8482ec3f6d30c79f583d135474f02b4670ff8fcd4"
    )
    assert snap.extras == ("agent", "server")


def test_unit_pyproject_parser_ignores_non_default_extras():
    text = (FIXTURES / "pyproject_ok.toml").read_text()
    snap = cd.parse_pyproject(text)
    assert snap.base == {"rich": ">=14.1.0,<15.0.0"}
    # Heavyweight extras are still parsed; the audit just ignores
    # those not in the formula's default profile.
    assert "local" in snap.extras
    assert snap.extras["agent"] == {"jinja2": ">=3.1.6,<4.0.0"}


def test_overlay_missing_is_tolerated_by_default(tmp_path: Path) -> None:
    # Without --strict-overlays, missing overlays are a Phase 3 TODO,
    # not a failure. Only orphans fail by default.
    depmap = cd.parse_dep_map(_pypi_sdist_map())
    report = cd.Report()
    cd.verify_packaging_overlays(depmap, tmp_path / "packages", report)
    assert report.ok(), report.errors


def test_overlay_missing_fails_under_strict(tmp_path: Path) -> None:
    depmap = cd.parse_dep_map(_pypi_sdist_map())
    report = cd.Report()
    cd.verify_packaging_overlays(
        depmap, tmp_path / "packages", report, strict_missing=True
    )
    assert not report.ok()
    assert any(
        "widget" in err and "packages/widget" in err
        for err in report.errors
    )


def test_overlay_present_passes(tmp_path: Path) -> None:
    overlay = tmp_path / "packages" / "widget" / "debian"
    overlay.mkdir(parents=True)
    (overlay / "control").write_text("Source: widget\n")

    depmap = cd.parse_dep_map(_pypi_sdist_map())
    report = cd.Report()
    cd.verify_packaging_overlays(
        depmap, tmp_path / "packages", report, strict_missing=True
    )
    assert report.ok(), report.errors


def test_overlay_orphan_directory_fails(tmp_path: Path) -> None:
    # Matching overlay for the mapped dep …
    (tmp_path / "packages" / "widget" / "debian").mkdir(parents=True)
    (tmp_path / "packages" / "widget" / "debian" / "control").write_text(
        "Source: widget\n"
    )
    # … plus a stale leftover directory with no row in the map.
    (tmp_path / "packages" / "stale" / "debian").mkdir(parents=True)
    (tmp_path / "packages" / "stale" / "debian" / "control").write_text(
        "Source: stale\n"
    )

    depmap = cd.parse_dep_map(_pypi_sdist_map())
    report = cd.Report()
    cd.verify_packaging_overlays(depmap, tmp_path / "packages", report)
    assert not report.ok()
    assert any(
        "packages/stale" in err and "no matching" in err
        for err in report.errors
    )


def test_overlay_source_name_canonicalizes() -> None:
    # PyPI names like RestrictedPython / google_genai map to lowercase
    # dashed directory names — the overlay check has to match the same
    # convention prepare-dep-source uses.
    assert cd._source_name("RestrictedPython") == "restrictedpython"
    assert cd._source_name("google_genai") == "google-genai"


def test_transitive_row_bypasses_pyproject_check(tmp_path: Path) -> None:
    # A row marked `transitive_of = <parent>` should NOT be required
    # in pyproject.toml -- it's packaged because its parent dep is.
    pyproject_text = (FIXTURES / "pyproject_ok.toml").read_text()
    formula_text = (FIXTURES / "formula_ok.rb").read_text()
    map_text = (FIXTURES / "depmap_ok.toml").read_text() + textwrap.dedent(
        """\

        [[dep]]
        pypi_name = "widget"
        constraint = ">=1.0,<2.0"
        debian_name = "python3-widget"
        extra = "agent"
        transitive_of = "jinja2"
        source = "ppa"
        provenance = "pypi-sdist"
        sdist_url = "https://example.invalid/widget-1.0.tar.gz"
        sdist_sha256 = "deadbeef"
        min_version = "1.0"
        """
    )
    formula = cd.parse_homebrew_formula(formula_text)
    pyproject = cd.parse_pyproject(pyproject_text)
    depmap = cd.parse_dep_map(map_text)
    report = cd.Report()
    cd.verify_parity(formula, pyproject, depmap, report)
    assert report.ok(), report.errors


def test_transitive_of_unknown_parent_fails() -> None:
    # If the parent named in transitive_of isn't actually a default
    # profile dep, the row is suspicious -- flag it.
    pyproject_text = (FIXTURES / "pyproject_ok.toml").read_text()
    formula_text = (FIXTURES / "formula_ok.rb").read_text()
    map_text = (FIXTURES / "depmap_ok.toml").read_text() + textwrap.dedent(
        """\

        [[dep]]
        pypi_name = "widget"
        constraint = ">=1.0,<2.0"
        debian_name = "python3-widget"
        extra = "agent"
        transitive_of = "imaginary-direct-dep"
        source = "ppa"
        provenance = "pypi-sdist"
        sdist_url = "https://example.invalid/widget-1.0.tar.gz"
        sdist_sha256 = "deadbeef"
        min_version = "1.0"
        """
    )
    formula = cd.parse_homebrew_formula(formula_text)
    pyproject = cd.parse_pyproject(pyproject_text)
    depmap = cd.parse_dep_map(map_text)
    report = cd.Report()
    cd.verify_parity(formula, pyproject, depmap, report)
    assert not report.ok()
    assert any(
        "transitive_of" in err and "imaginary-direct-dep" in err
        for err in report.errors
    )
