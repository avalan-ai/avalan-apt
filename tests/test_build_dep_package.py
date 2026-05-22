"""Tests for scripts/build_dep_package.

Exercises the wrapper's branching on provenance and build mode by
mocking the subprocess.run boundary. The actual dpkg-buildpackage /
dpkg-source invocations only exist on Debian-based hosts; the unit
layer captures the command lines and asserts the right tool was
invoked with the right flags from the right working directory.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import textwrap
from pathlib import Path
from typing import Any

import pytest

import build_dep_package as bdp
import prepare_dep_source as pds


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    map_path = tmp_path / "debian" / "dependency-map.toml"
    map_path.parent.mkdir(parents=True)
    map_path.write_text(
        textwrap.dedent(
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
            sdist_url = "https://example.invalid/widget-1.2.3.tar.gz"
            sdist_sha256 = "PLACEHOLDER"
            min_version = "1.2.3"

            [[dep]]
            pypi_name = "gear"
            constraint = ">=2.0,<3.0"
            debian_name = "python3-gear"
            extra = "base"
            source = "ppa"
            provenance = "debian-rebuild"
            debian_source_pkg = "python-gear"
            debian_suite = "sid"
            debian_version = "2.5.0-1"
            min_version = "2.5.0"
            """
        )
    )
    overlay = tmp_path / "packages" / "widget" / "debian"
    overlay.mkdir(parents=True)
    (overlay / "control").write_text("Source: widget\n")
    return tmp_path


def _make_sdist(unpack_name: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        payload = b"hello\n"
        info = tarfile.TarInfo(name=f"{unpack_name}/PKG-INFO")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


class _RunCapture:
    """Stand-in for subprocess.run that records each invocation."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, args, **kwargs):
        self.calls.append({"args": list(args), **kwargs})

        class _Done:
            returncode = 0

        return _Done()


def test_source_tree_for_dsc_strips_revision() -> None:
    dsc = Path("/tmp/build/deps/python-gear_2.5.0-1.dsc")
    assert (
        bdp._source_tree_for_dsc(dsc)
        == Path("/tmp/build/deps/python-gear-2.5.0")
    )


def test_build_args_flag_selection() -> None:
    # -sa is always included on source builds so the orig tarball
    # rides along even on non-first Debian revisions. Launchpad
    # rejects the first upload of a ~ppa1~noble2-style revision into
    # an empty PPA otherwise.
    assert bdp._build_args("source") == [
        "dpkg-buildpackage",
        "-S",
        "-us",
        "-uc",
        "-sa",
    ]
    assert bdp._build_args("binary") == [
        "dpkg-buildpackage",
        "-b",
        "-us",
        "-uc",
    ]
    with pytest.raises(ValueError, match="unknown build mode"):
        bdp._build_args("garbage")


def test_build_args_allow_unmet_build_deps_appends_d() -> None:
    assert bdp._build_args(
        "source", allow_unmet_build_deps=True
    ) == ["dpkg-buildpackage", "-S", "-us", "-uc", "-sa", "-d"]
    assert bdp._build_args(
        "binary", allow_unmet_build_deps=True
    ) == ["dpkg-buildpackage", "-b", "-us", "-uc", "-d"]
    # Confirm the strict default keeps `-d` out.
    assert "-d" not in bdp._build_args("source")
    assert "-d" not in bdp._build_args("binary")


def test_pypi_sdist_invokes_dpkg_buildpackage_in_unpacked_tree(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _make_sdist("widget-1.2.3")
    sha = hashlib.sha256(archive).hexdigest()
    map_path = fake_repo / "debian" / "dependency-map.toml"
    map_path.write_text(map_path.read_text().replace("PLACEHOLDER", sha))

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive)

    monkeypatch.setattr(pds, "fetch", fake_fetch)

    dep = pds.find_dep(map_path, "widget")
    runner = _RunCapture()
    out = bdp.build_pypi_sdist(
        dep, fake_repo, mode="source", runner=runner
    )

    assert out == fake_repo / "build" / "deps" / "widget-1.2.3"
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["args"] == [
        "dpkg-buildpackage",
        "-S",
        "-us",
        "-uc",
        "-sa",
    ]
    assert call["cwd"] == str(out)
    assert call["check"] is True


def test_pypi_sdist_binary_mode_flips_dpkg_flag(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _make_sdist("widget-1.2.3")
    sha = hashlib.sha256(archive).hexdigest()
    map_path = fake_repo / "debian" / "dependency-map.toml"
    map_path.write_text(map_path.read_text().replace("PLACEHOLDER", sha))

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive)

    monkeypatch.setattr(pds, "fetch", fake_fetch)

    dep = pds.find_dep(map_path, "widget")
    runner = _RunCapture()
    bdp.build_pypi_sdist(dep, fake_repo, mode="binary", runner=runner)

    assert runner.calls[0]["args"][1] == "-b"


def test_debian_rebuild_retargets_to_noble_via_dch(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The full debian-rebuild flow runs dpkg-source -x, then dch to
    # bump version + retarget to noble, then dpkg-buildpackage. Verify
    # all three land in order with the right args.
    orig = b"orig\n"
    deb = b"deb\n"
    dsc_text = (
        "Format: 3.0 (quilt)\n"
        "Checksums-Sha256:\n"
        f" {hashlib.sha256(orig).hexdigest()} {len(orig)} "
        "python-gear_2.5.0.orig.tar.gz\n"
        f" {hashlib.sha256(deb).hexdigest()} {len(deb)} "
        "python-gear_2.5.0-1.debian.tar.xz\n"
        "\n"
    )
    payloads = {
        "python-gear_2.5.0-1.dsc": dsc_text.encode(),
        "python-gear_2.5.0.orig.tar.gz": orig,
        "python-gear_2.5.0-1.debian.tar.xz": deb,
    }

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payloads[dest.name])

    monkeypatch.setattr(pds, "fetch", fake_fetch)

    map_path = fake_repo / "debian" / "dependency-map.toml"
    dep = pds.find_dep(map_path, "gear")
    runner = _RunCapture()

    bdp.build_debian_rebuild(
        dep, fake_repo, mode="source", runner=runner,
    )

    assert [c["args"][:2] for c in runner.calls] == [
        ["dpkg-source", "-x"],
        ["dch", "--local"],
        ["dpkg-buildpackage", "-S"],
    ]
    dch_call = runner.calls[1]
    assert dch_call["args"] == [
        "dch",
        "--local",
        "+noble",
        "--distribution",
        "noble",
        "--force-distribution",
        "Rebuild for the Avalan PPA. No source changes.",
    ]
    assert dch_call["cwd"] == str(
        fake_repo / "build" / "deps" / "python-gear-2.5.0"
    )


def test_debian_rebuild_empty_suffix_skips_dch(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orig = b"orig\n"
    deb = b"deb\n"
    dsc_text = (
        "Format: 3.0 (quilt)\n"
        "Checksums-Sha256:\n"
        f" {hashlib.sha256(orig).hexdigest()} {len(orig)} "
        "python-gear_2.5.0.orig.tar.gz\n"
        f" {hashlib.sha256(deb).hexdigest()} {len(deb)} "
        "python-gear_2.5.0-1.debian.tar.xz\n"
        "\n"
    )
    payloads = {
        "python-gear_2.5.0-1.dsc": dsc_text.encode(),
        "python-gear_2.5.0.orig.tar.gz": orig,
        "python-gear_2.5.0-1.debian.tar.xz": deb,
    }

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payloads[dest.name])

    monkeypatch.setattr(pds, "fetch", fake_fetch)

    map_path = fake_repo / "debian" / "dependency-map.toml"
    dep = pds.find_dep(map_path, "gear")
    runner = _RunCapture()

    bdp.build_debian_rebuild(
        dep, fake_repo, mode="source", runner=runner, ppa_suffix="",
    )

    invoked = [c["args"][0] for c in runner.calls]
    assert "dch" not in invoked
    assert invoked == ["dpkg-source", "dpkg-buildpackage"]


def test_debian_rebuild_runs_dpkg_source_then_buildpackage(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orig = b"orig\n"
    deb = b"deb\n"
    dsc_text = (
        "Format: 3.0 (quilt)\n"
        "Checksums-Sha256:\n"
        f" {hashlib.sha256(orig).hexdigest()} {len(orig)} "
        "python-gear_2.5.0.orig.tar.gz\n"
        f" {hashlib.sha256(deb).hexdigest()} {len(deb)} "
        "python-gear_2.5.0-1.debian.tar.xz\n"
        "\n"
    )
    payloads = {
        "python-gear_2.5.0-1.dsc": dsc_text.encode(),
        "python-gear_2.5.0.orig.tar.gz": orig,
        "python-gear_2.5.0-1.debian.tar.xz": deb,
    }

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payloads[dest.name])

    monkeypatch.setattr(pds, "fetch", fake_fetch)

    map_path = fake_repo / "debian" / "dependency-map.toml"
    dep = pds.find_dep(map_path, "gear")
    runner = _RunCapture()

    out = bdp.build_debian_rebuild(
        dep, fake_repo, mode="source", runner=runner, ppa_suffix="",
    )

    assert out == fake_repo / "build" / "deps" / "python-gear-2.5.0"
    # First call: dpkg-source -x, second call: dpkg-buildpackage.
    assert runner.calls[0]["args"][:2] == ["dpkg-source", "-x"]
    assert runner.calls[0]["args"][-1] == str(out)
    assert runner.calls[1]["args"] == [
        "dpkg-buildpackage",
        "-S",
        "-us",
        "-uc",
        "-sa",
    ]
    assert runner.calls[1]["cwd"] == str(out)


def test_main_bails_when_dpkg_tooling_missing(
    fake_repo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def explode(_tools):
        raise EnvironmentError("dpkg-buildpackage not on PATH (test)")

    runner = _RunCapture()
    with pytest.raises(EnvironmentError, match="not on PATH"):
        bdp.main(
            [
                "widget",
                "--map",
                str(fake_repo / "debian" / "dependency-map.toml"),
            ],
            runner=runner,
            tool_checker=explode,
        )
    assert runner.calls == []


def test_main_routes_by_provenance(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # pypi-sdist row hits prepare_pypi_sdist + one runner call.
    archive = _make_sdist("widget-1.2.3")
    sha = hashlib.sha256(archive).hexdigest()
    map_path = fake_repo / "debian" / "dependency-map.toml"
    map_path.write_text(map_path.read_text().replace("PLACEHOLDER", sha))

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive)

    monkeypatch.setattr(pds, "fetch", fake_fetch)

    runner = _RunCapture()
    rc = bdp.main(
        ["widget", "--map", str(map_path)],
        runner=runner,
        tool_checker=lambda _t: None,
    )
    assert rc == 0
    assert len(runner.calls) == 1
    assert runner.calls[0]["args"][0] == "dpkg-buildpackage"
    captured = capsys.readouterr()
    assert str(fake_repo / "build" / "deps" / "widget-1.2.3") in captured.out
