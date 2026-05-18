"""Tests for scripts/prepare_dep_source.

Exercises the dependency lookup, naming, and overlay logic against
fixture data so the script can be developed on dev hosts without a
Noble chroot. The end-to-end flow is driven by a fake downloader that
materializes a tarball with a known sha256 in place of an actual HTTP
fetch.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import tarfile
import textwrap
from pathlib import Path

import pytest

import prepare_dep_source as pds


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Build a minimal repo-root scaffold under ``tmp_path``.

    Lays out ``debian/dependency-map.toml`` with one pypi-sdist row,
    one debian-rebuild row, and a stub ``packages/widget/debian/``
    overlay the pypi-sdist branch can copy.
    """
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
    """Build a tarball that unpacks to ``unpack_name/`` with one file."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        payload = b"hello\n"
        info = tarfile.TarInfo(name=f"{unpack_name}/PKG-INFO")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def _set_sha(map_path: Path, sha: str) -> None:
    text = map_path.read_text().replace("PLACEHOLDER", sha)
    map_path.write_text(text)


def test_find_dep_resolves_canonical_pypi_name(fake_repo: Path) -> None:
    dep = pds.find_dep(
        fake_repo / "debian" / "dependency-map.toml", "Widget"
    )
    assert dep.pypi_name == "widget"
    assert dep.provenance == "pypi-sdist"


def test_find_dep_normalizes_underscore_to_dash(fake_repo: Path) -> None:
    # The map row is `widget` (with no underscore); ask for it via the
    # underscore form and confirm the canonicalization matches.
    map_path = fake_repo / "debian" / "dependency-map.toml"
    map_path.write_text(
        map_path.read_text().replace(
            'pypi_name = "widget"', 'pypi_name = "wid_get"'
        )
    )
    dep = pds.find_dep(map_path, "wid-get")
    assert dep.pypi_name == "wid_get"


def test_find_dep_missing_row_raises(fake_repo: Path) -> None:
    with pytest.raises(LookupError, match="no \\[\\[dep\\]\\] row"):
        pds.find_dep(
            fake_repo / "debian" / "dependency-map.toml", "missing"
        )


def test_source_name_lowercases_and_dashes() -> None:
    dep = pds.DepRow(
        pypi_name="RestrictedPython",
        provenance="pypi-sdist",
        min_version="8.0",
        sdist_url="",
        sdist_sha256="",
        debian_source_pkg="",
        debian_suite="",
    )
    assert pds.source_name(dep) == "restrictedpython"


def test_upstream_version_parses_sdist_url() -> None:
    dep = pds.DepRow(
        pypi_name="humanize",
        provenance="pypi-sdist",
        min_version="4.12.3",
        sdist_url=(
            "https://files.pythonhosted.org/packages/22/d1/"
            "bbc4d251187a43f69844f7fd8941426549bbe4723e8ff0a7441796b07"
            "89f/humanize-4.12.3.tar.gz"
        ),
        sdist_sha256="",
        debian_source_pkg="",
        debian_suite="",
    )
    assert pds.upstream_version(dep) == "4.12.3"


def test_upstream_version_strips_v_prefix_for_github_archives() -> None:
    # GitHub source-archive URLs use `<tag>.tar.gz` where the tag is
    # commonly `v1.2.3`. The regex must swallow the leading `v` so the
    # version comes out matching the unpack-dir suffix.
    dep = pds.DepRow(
        pypi_name="playwright",
        provenance="pypi-sdist",
        min_version="1.55.0",
        sdist_url=(
            "https://github.com/microsoft/playwright-python/"
            "archive/refs/tags/v1.55.0.tar.gz"
        ),
        sdist_sha256="",
        debian_source_pkg="",
        debian_suite="",
    )
    assert pds.upstream_version(dep) == "1.55.0"


def test_prepare_pypi_sdist_overlays_packaging(fake_repo: Path) -> None:
    archive = _make_sdist("widget-1.2.3")
    expected_sha = hashlib.sha256(archive).hexdigest()
    _set_sha(fake_repo / "debian" / "dependency-map.toml", expected_sha)

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive)

    dep = pds.find_dep(
        fake_repo / "debian" / "dependency-map.toml", "widget"
    )
    out = pds.prepare_pypi_sdist(dep, fake_repo, fetcher=fake_fetch)

    assert out == fake_repo / "build" / "deps" / "widget-1.2.3"
    assert (out / "PKG-INFO").is_file()
    # Overlay was copied on top.
    assert (out / "debian" / "control").read_text() == "Source: widget\n"
    # Orig tarball is in place and verifies.
    orig = fake_repo / "build" / "deps" / "widget_1.2.3.orig.tar.gz"
    assert pds.sha256_file(orig) == expected_sha


def test_prepare_pypi_sdist_renames_underscore_form(
    fake_repo: Path,
) -> None:
    # PyPI canonicalizes `-` and `_` in distribution names; the sdist
    # tarball usually unpacks to the underscore form even when the
    # package's source-name is dashed (e.g. youtube_transcript_api
    # for source `youtube-transcript-api`, google_genai for
    # `google-genai`). The prepare helper must rename to the dashed
    # form expected by `dpkg-buildpackage`.
    map_path = fake_repo / "debian" / "dependency-map.toml"
    map_path.write_text(
        map_path.read_text().replace(
            'pypi_name = "widget"', 'pypi_name = "wid-get"'
        )
    )
    # Overlay directory follows the dashed source name.
    (fake_repo / "packages" / "widget").rename(
        fake_repo / "packages" / "wid-get"
    )

    archive = _make_sdist("wid_get-1.2.3")  # underscore unpack form
    expected_sha = hashlib.sha256(archive).hexdigest()
    _set_sha(map_path, expected_sha)

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive)

    dep = pds.find_dep(map_path, "wid-get")
    out = pds.prepare_pypi_sdist(dep, fake_repo, fetcher=fake_fetch)

    assert out == fake_repo / "build" / "deps" / "wid-get-1.2.3"
    assert (out / "PKG-INFO").is_file()
    assert (out / "debian" / "control").exists()


def test_prepare_pypi_sdist_rejects_sha_mismatch(fake_repo: Path) -> None:
    archive = _make_sdist("widget-1.2.3")
    _set_sha(fake_repo / "debian" / "dependency-map.toml", "deadbeef" * 8)

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive)

    dep = pds.find_dep(
        fake_repo / "debian" / "dependency-map.toml", "widget"
    )
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        pds.prepare_pypi_sdist(dep, fake_repo, fetcher=fake_fetch)


def test_prepare_pypi_sdist_requires_overlay(fake_repo: Path) -> None:
    archive = _make_sdist("widget-1.2.3")
    expected_sha = hashlib.sha256(archive).hexdigest()
    _set_sha(fake_repo / "debian" / "dependency-map.toml", expected_sha)
    shutil.rmtree(fake_repo / "packages" / "widget")

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive)

    dep = pds.find_dep(
        fake_repo / "debian" / "dependency-map.toml", "widget"
    )
    with pytest.raises(FileNotFoundError, match="no packaging overlay"):
        pds.prepare_pypi_sdist(dep, fake_repo, fetcher=fake_fetch)


def test_debian_pool_url_handles_letter_and_library_layout() -> None:
    assert (
        pds.debian_pool_url("jinja2", "3.1.6-2")
        == "https://deb.debian.org/debian/pool/main/j/jinja2/"
        "jinja2_3.1.6-2.dsc"
    )
    # Libraries live in pool/main/lib<x>/ rather than pool/main/l/.
    assert (
        pds.debian_pool_url("libxml2", "2.12.7-1")
        == "https://deb.debian.org/debian/pool/main/libx/libxml2/"
        "libxml2_2.12.7-1.dsc"
    )


_DSC_FIXTURE = """\
-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA512

Format: 3.0 (quilt)
Source: python-gear
Version: 2.5.0-1
Checksums-Sha1:
 1111111111111111111111111111111111111111 245115 python-gear_2.5.0.orig.tar.gz
 2222222222222222222222222222222222222222 10180 python-gear_2.5.0-1.debian.tar.xz
Checksums-Sha256:
 aaaa000000000000000000000000000000000000000000000000000000000001 245115 python-gear_2.5.0.orig.tar.gz
 bbbb000000000000000000000000000000000000000000000000000000000002 10180 python-gear_2.5.0-1.debian.tar.xz
Files:
 cccc 245115 python-gear_2.5.0.orig.tar.gz
 dddd 10180 python-gear_2.5.0-1.debian.tar.xz

-----BEGIN PGP SIGNATURE-----
fake signature
-----END PGP SIGNATURE-----
"""


def test_parse_dsc_sha256_extracts_checksums_block() -> None:
    files = pds.parse_dsc_sha256(_DSC_FIXTURE)
    assert files == {
        "python-gear_2.5.0.orig.tar.gz": (
            "aaaa000000000000000000000000000000000000"
            "000000000000000000000001"
        ),
        "python-gear_2.5.0-1.debian.tar.xz": (
            "bbbb000000000000000000000000000000000000"
            "000000000000000000000002"
        ),
    }


def test_parse_dsc_sha256_raises_when_block_missing() -> None:
    with pytest.raises(ValueError, match="no Checksums-Sha256"):
        pds.parse_dsc_sha256("Format: 3.0 (quilt)\n")


def test_prepare_debian_rebuild_fetches_and_verifies(
    fake_repo: Path,
) -> None:
    map_path = fake_repo / "debian" / "dependency-map.toml"
    dep = pds.find_dep(map_path, "gear")

    # Build a self-consistent .dsc that references payloads we know
    # the exact sha256 of, then mock-fetch each in turn.
    orig_payload = b"orig contents\n"
    debian_payload = b"debian contents\n"
    orig_sha = hashlib.sha256(orig_payload).hexdigest()
    debian_sha = hashlib.sha256(debian_payload).hexdigest()
    dsc_text = (
        "-----BEGIN PGP SIGNED MESSAGE-----\n"
        "Hash: SHA512\n"
        "\n"
        "Format: 3.0 (quilt)\n"
        "Source: python-gear\n"
        "Version: 2.5.0-1\n"
        "Checksums-Sha256:\n"
        f" {orig_sha} {len(orig_payload)} "
        "python-gear_2.5.0.orig.tar.gz\n"
        f" {debian_sha} {len(debian_payload)} "
        "python-gear_2.5.0-1.debian.tar.xz\n"
        "Files:\n"
        " aa 14 python-gear_2.5.0.orig.tar.gz\n"
        " bb 16 python-gear_2.5.0-1.debian.tar.xz\n"
        "\n"
    )
    payloads = {
        "python-gear_2.5.0-1.dsc": dsc_text.encode(),
        "python-gear_2.5.0.orig.tar.gz": orig_payload,
        "python-gear_2.5.0-1.debian.tar.xz": debian_payload,
    }

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payloads[dest.name])

    out = pds.prepare_debian_rebuild(dep, fake_repo, fetcher=fake_fetch)

    deps_dir = fake_repo / "build" / "deps"
    assert out == deps_dir / "python-gear_2.5.0-1.dsc"
    assert out.is_file()
    assert (
        deps_dir / "python-gear_2.5.0.orig.tar.gz"
    ).read_bytes() == orig_payload
    assert (
        deps_dir / "python-gear_2.5.0-1.debian.tar.xz"
    ).read_bytes() == debian_payload


def test_prepare_debian_rebuild_rejects_sha_mismatch(
    fake_repo: Path,
) -> None:
    map_path = fake_repo / "debian" / "dependency-map.toml"
    dep = pds.find_dep(map_path, "gear")

    # .dsc advertises a sha256 that no payload will match.
    dsc_text = (
        "Format: 3.0 (quilt)\n"
        "Checksums-Sha256:\n"
        " deadbeef00000000000000000000000000000000"
        "000000000000000000000000 14 "
        "python-gear_2.5.0.orig.tar.gz\n"
        "\n"
    )

    def fake_fetch(url: str, dest: Path, *, downloader: str = "wget"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.name.endswith(".dsc"):
            dest.write_bytes(dsc_text.encode())
        else:
            dest.write_bytes(b"different bytes\n")

    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        pds.prepare_debian_rebuild(
            dep, fake_repo, fetcher=fake_fetch
        )


def test_prepare_debian_rebuild_requires_debian_version(
    fake_repo: Path,
) -> None:
    map_path = fake_repo / "debian" / "dependency-map.toml"
    map_path.write_text(
        map_path.read_text().replace(
            'debian_version = "2.5.0-1"\n', ""
        )
    )
    dep = pds.find_dep(map_path, "gear")
    assert dep.debian_version == ""
    with pytest.raises(ValueError, match="debian_version"):
        pds.prepare_debian_rebuild(dep, fake_repo)


def test_main_debian_rebuild_now_drives_fetch(
    fake_repo: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # main() routes debian-rebuild rows through prepare_debian_rebuild;
    # patch the fetcher so the test doesn't hit deb.debian.org.
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
    monkeypatch.chdir(fake_repo)
    rc = pds.main(
        [
            "gear",
            "--map",
            str(fake_repo / "debian" / "dependency-map.toml"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "python-gear_2.5.0-1.dsc" in captured.out
