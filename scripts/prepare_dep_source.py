"""Fetch, verify, and overlay one Avalan dependency's source tree.

Reads ``debian/dependency-map.toml``, locates the row for the named
dependency, and prepares it for ``dpkg-buildpackage``:

* ``provenance = "pypi-sdist"``: download the recorded ``sdist_url``
  into ``build/deps/`` as ``<source>_<version>.orig.tar.gz``, verify
  the ``sdist_sha256``, unpack, and copy ``packages/<source>/debian/``
  on top.
* ``provenance = "debian-rebuild"``: download the matching ``.dsc``
  from deb.debian.org's pool plus every file it references
  (``.orig.tar.*``, ``.debian.tar.*``, multi-tarball component
  tarballs) into ``build/deps/``, verify each against the
  ``Checksums-Sha256`` block in the ``.dsc``. The caller runs
  ``dpkg-source -x <dsc>`` on Noble to materialize a buildable tree
  (this script avoids reimplementing dpkg-source's quilt logic).

The final stdout line is the absolute path to either the unpacked
source tree (pypi-sdist) or the verified ``.dsc`` (debian-rebuild),
so callers can do ``src=$(scripts/prepare-dep-source <name>)``.
Trace output goes to stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class DepRow:
    pypi_name: str
    provenance: str
    min_version: str
    sdist_url: str
    sdist_sha256: str
    debian_source_pkg: str
    debian_suite: str
    debian_version: str = ""
    cargo_vendor: bool = False


# Tail of a sdist URL: PyPI uses `<name>-<version>.tar.gz`; GitHub
# release archives use `<tag>.tar.gz` with the tag often prefixed `v`
# (e.g. `v1.55.0.tar.gz`). Match either form, swallowing the optional
# `v` before the version digits.
_VERSION_FROM_URL = re.compile(
    r"[/_-]v?([0-9][^/]*?)\.tar\.(?:gz|bz2|xz)$"
)


def find_dep(map_path: Path, name: str) -> DepRow:
    data = tomllib.loads(map_path.read_text())
    canon = name.lower().replace("_", "-")
    for entry in data.get("dep", ()):
        if entry["pypi_name"].lower().replace("_", "-") == canon:
            return DepRow(
                pypi_name=entry["pypi_name"],
                provenance=entry.get("provenance", ""),
                min_version=entry["min_version"],
                sdist_url=entry.get("sdist_url", ""),
                sdist_sha256=entry.get("sdist_sha256", ""),
                debian_source_pkg=entry.get("debian_source_pkg", ""),
                debian_suite=entry.get("debian_suite", ""),
                debian_version=entry.get("debian_version", ""),
                cargo_vendor=bool(entry.get("cargo_vendor", False)),
            )
    raise LookupError(
        f"{name!r}: no [[dep]] row in {map_path}; expected one of "
        f"{sorted(e['pypi_name'] for e in data.get('dep', ()))}"
    )


def source_name(dep: DepRow) -> str:
    """Debian source package name for ``dep``.

    Convention: lowercase the PyPI name and replace underscores with
    dashes. The handful of explicit Debian-name remaps live in
    ``debian/py3dist-overrides`` for ``dh_python3``; they don't change
    the source-package directory under ``packages/``.
    """
    return dep.pypi_name.lower().replace("_", "-")


def upstream_version(dep: DepRow) -> str:
    """The version pinned in the sdist URL (e.g. 4.12.3 from
    humanize-4.12.3.tar.gz). For debian-rebuild rows, falls back to
    ``min_version``.
    """
    if dep.sdist_url:
        m = _VERSION_FROM_URL.search(urlparse(dep.sdist_url).path)
        if not m:
            raise ValueError(
                f"sdist_url for {dep.pypi_name!r} has no parseable "
                f"version suffix: {dep.sdist_url!r}"
            )
        return m.group(1)
    return dep.min_version


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path, *, downloader: str = "wget") -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if downloader == "wget":
        cmd = ["wget", "--no-verbose", "-O", str(dest), url]
    elif downloader == "curl":
        cmd = ["curl", "-sSL", "-o", str(dest), url]
    else:
        raise ValueError(f"unknown downloader: {downloader!r}")
    subprocess.run(cmd, check=True)


def prepare_pypi_sdist(
    dep: DepRow,
    repo_root: Path,
    *,
    fetcher=None,
) -> Path:
    if fetcher is None:
        fetcher = fetch
    src_name = source_name(dep)
    version = upstream_version(dep)
    deps_dir = repo_root / "build" / "deps"
    orig = deps_dir / f"{src_name}_{version}.orig.tar.gz"

    # See the comment in prepare_debian_rebuild: trust the I/O
    # boundary rather than .is_file() because Docker Desktop's macOS
    # bind-mount stat cache occasionally lies.
    try:
        existing_sha = sha256_file(orig)
    except FileNotFoundError:
        existing_sha = None
    if existing_sha != dep.sdist_sha256:
        orig.unlink(missing_ok=True)
        fetcher(dep.sdist_url, orig)

    actual = sha256_file(orig)
    if actual != dep.sdist_sha256:
        raise RuntimeError(
            f"sha256 mismatch for {orig}: expected "
            f"{dep.sdist_sha256}, got {actual}"
        )

    unpack_dir = deps_dir / f"{src_name}-{version}"
    if unpack_dir.exists():
        shutil.rmtree(unpack_dir)
    subprocess.run(
        ["tar", "-C", str(deps_dir), "-xf", str(orig)], check=True
    )
    if not unpack_dir.is_dir():
        # Some sdists unpack to a normalized form -- typically the
        # underscore-spelling of a dashed distribution name (PyPI
        # canonicalizes the two; sdists like youtube_transcript_api,
        # google_genai, a2a_sdk all do this). Match either form.
        src_name_alt = src_name.replace("-", "_")
        prefixes = {src_name, src_name_alt}
        candidates = [
            p
            for p in deps_dir.iterdir()
            if p.is_dir()
            and any(p.name.startswith(prefix) for prefix in prefixes)
            and version in p.name
        ]
        if len(candidates) == 1:
            candidates[0].rename(unpack_dir)
        else:
            raise RuntimeError(
                f"sdist did not unpack to {unpack_dir} and could not "
                f"unambiguously locate the source tree under "
                f"{deps_dir} (saw: {[p.name for p in candidates]})"
            )

    overlay = repo_root / "packages" / src_name / "debian"
    if not overlay.is_dir():
        raise FileNotFoundError(
            f"no packaging overlay at {overlay} — create "
            f"packages/{src_name}/debian/ before preparing this dep"
        )
    shutil.copytree(overlay, unpack_dir / "debian", dirs_exist_ok=False)
    if dep.cargo_vendor:
        cargo_vendor(unpack_dir)
    return unpack_dir


# Vendor the crates under debian/ rather than at the project root.
# Anything outside debian/ would land as "unrepresentable changes"
# under dpkg-source's 3.0 (quilt) format and break the source-only
# build mode that Launchpad consumes. The matching cargo registry
# redirect lives in debian/rules' override_dh_auto_configure, so the
# upstream .cargo/ tree stays untouched and the vendored path uses
# $(CURDIR) at build time to dodge cargo's relative-to-config-file
# path resolution.
_CARGO_VENDOR_REL_DIR = "debian/vendor"


def cargo_vendor(
    source_dir: Path,
    *,
    runner=None,
) -> None:
    """Vendor the Cargo dependencies of ``source_dir`` for offline build.

    Runs ``cargo vendor`` against the source tree's ``Cargo.toml`` /
    ``Cargo.lock``, writing all transitive crate sources under
    ``debian/vendor/``. The vendored tree lives under ``debian/`` so
    dpkg-source's ``3.0 (quilt)`` format treats it as part of the
    Debian packaging and not as an unrepresentable change to the
    upstream tarball. Also write
    ``debian/source/include-binaries`` listing every binary file under
    ``debian/vendor/`` so ``3.0 (quilt)`` accepts the tree.

    Post-process each crate's ``.cargo-checksum.json`` to drop entries
    whose backing file is missing from the vendored tree. Cargo 1.75
    on different hosts disagrees on which files it copies (``Cargo
    .toml.orig`` shows up under amd64 but not arm64), and the build
    step refuses to proceed if the checksum json references a file
    that is not present.

    The matching cargo registry redirect is written by
    ``debian/rules`` at build time; this helper does not touch the
    upstream ``.cargo/config.toml``.

    Vendoring happens at prepare time (network is allowed) so the
    later ``dpkg-buildpackage`` step can stay hermetic.
    """
    if runner is None:
        runner = subprocess.run
    if shutil.which("cargo") is None:
        raise EnvironmentError(
            "cargo not on PATH; cargo_vendor=true rows require the "
            "Noble cargo package. Run via scripts/dockerized-build "
            "or install `cargo` on the host."
        )
    cargo_toml = source_dir / "Cargo.toml"
    cargo_lock = source_dir / "Cargo.lock"
    if not cargo_toml.is_file():
        raise FileNotFoundError(
            f"{cargo_toml} missing; cargo_vendor=true row but the "
            f"upstream sdist has no Cargo.toml at the root"
        )
    if not cargo_lock.is_file():
        raise FileNotFoundError(
            f"{cargo_lock} missing; cargo vendor needs a Cargo.lock "
            f"for deterministic resolution"
        )
    runner(
        ["cargo", "vendor", "--locked", _CARGO_VENDOR_REL_DIR],
        cwd=str(source_dir),
        check=True,
    )
    _prune_vendor_checksums(source_dir / _CARGO_VENDOR_REL_DIR)
    _write_include_binaries(source_dir)


def _prune_vendor_checksums(vendor_dir: Path) -> None:
    if not vendor_dir.is_dir():
        return
    for checksum in vendor_dir.glob("*/.cargo-checksum.json"):
        data = json.loads(checksum.read_text())
        files = data.get("files", {})
        pruned = {
            name: digest
            for name, digest in files.items()
            if (checksum.parent / name).is_file()
        }
        if pruned != files:
            data["files"] = pruned
            checksum.write_text(json.dumps(data, separators=(",", ":")))


def _looks_binary(path: Path, *, chunk: int = 4096) -> bool:
    """Heuristic: a file is binary if its first chunk contains a NUL.

    Mirrors what ``dpkg-source --before-build`` does when it decides
    whether a file under ``debian/`` triggers the "unwanted binary
    file" guardrail in ``3.0 (quilt)`` mode.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(chunk)
    except OSError:
        return False
    return b"\x00" in head


def _write_include_binaries(source_dir: Path) -> None:
    """List every binary file under ``debian/vendor/`` in
    ``debian/source/include-binaries``.

    ``3.0 (quilt)`` rejects binary files under ``debian/`` unless they
    are explicitly listed here. The vendored cargo registry contains
    a handful of test-fixture binaries (regex-automata DFAs, fuzzer
    crash inputs, ...) — list them so ``dpkg-source -b`` accepts the
    tree as-is.
    """
    vendor = source_dir / _CARGO_VENDOR_REL_DIR
    if not vendor.is_dir():
        return
    binaries: list[str] = []
    for path in sorted(vendor.rglob("*")):
        if not path.is_file():
            continue
        if not _looks_binary(path):
            continue
        binaries.append(str(path.relative_to(source_dir)))
    if not binaries:
        return
    include_path = source_dir / "debian" / "source" / "include-binaries"
    include_path.parent.mkdir(parents=True, exist_ok=True)
    include_path.write_text("\n".join(binaries) + "\n")


def debian_pool_url(source: str, version: str) -> str:
    """deb.debian.org pool URL for a Debian source package's .dsc.

    Debian's pool layout puts source packages under
    ``pool/main/<letter>/<source>/`` — ``<letter>`` is the source
    package's first character, except for libraries (which use the
    first four characters, ``lib<x>``).
    """
    prefix = source[:4] if source.startswith("lib") else source[0]
    return (
        "https://deb.debian.org/debian/pool/main/"
        f"{prefix}/{source}/{source}_{version}.dsc"
    )


_DSC_CHECKSUMS_HEADER = "Checksums-Sha256:"


def parse_dsc_sha256(text: str) -> dict[str, str]:
    """Extract ``{filename: sha256}`` from a Debian ``.dsc`` file.

    The ``.dsc`` is a Debian control-file-format document, optionally
    PGP-clearsigned. Within it, the ``Checksums-Sha256:`` field is a
    multi-line block where each continuation line lists
    ``<sha256> <size> <filename>`` separated by whitespace. The block
    ends at the first non-indented line.
    """
    files: dict[str, str] = {}
    in_block = False
    for raw_line in text.splitlines():
        if raw_line.startswith(_DSC_CHECKSUMS_HEADER):
            in_block = True
            continue
        if not in_block:
            continue
        # Continuation lines must start with whitespace; anything else
        # ends the field.
        if not raw_line or not raw_line[0].isspace():
            break
        parts = raw_line.split()
        if len(parts) != 3:
            continue
        sha256, _size, filename = parts
        files[filename] = sha256
    if not files:
        raise ValueError("no Checksums-Sha256 entries found in .dsc")
    return files


def prepare_debian_rebuild(
    dep: DepRow,
    repo_root: Path,
    *,
    fetcher=None,
) -> Path:
    if fetcher is None:
        fetcher = fetch
    """Fetch and verify a debian-rebuild row's source files.

    Downloads the ``.dsc`` from deb.debian.org's pool, then every file
    it references (``.orig.tar.*``, ``.debian.tar.*``, plus any
    additional component tarballs for multi-tarball sources) and
    verifies each against the ``.dsc``'s ``Checksums-Sha256`` block.
    The fetched files land under ``build/deps/`` alongside the
    pypi-sdist artifacts; the caller runs ``dpkg-source -x <dsc>``
    on Noble to unpack into a buildable tree.

    Returns the path to the verified ``.dsc``.
    """
    missing = [
        field
        for field, value in (
            ("debian_source_pkg", dep.debian_source_pkg),
            ("debian_suite", dep.debian_suite),
            ("debian_version", dep.debian_version),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            f"{dep.pypi_name}: debian-rebuild row missing "
            f"{', '.join(missing)}"
        )

    src = dep.debian_source_pkg
    version = dep.debian_version
    deps_dir = repo_root / "build" / "deps"
    deps_dir.mkdir(parents=True, exist_ok=True)

    dsc_url = debian_pool_url(src, version)
    dsc_path = deps_dir / f"{src}_{version}.dsc"
    if not dsc_path.is_file():
        fetcher(dsc_url, dsc_path)

    sha_by_file = parse_dsc_sha256(dsc_path.read_text())
    base_url = dsc_url.rsplit("/", 1)[0]

    for filename, expected_sha in sha_by_file.items():
        target = deps_dir / filename
        # `target.is_file()` can race against the bind-mount stat
        # cache on Docker Desktop's macOS filesystem layer, returning
        # True for a path that does not yet exist. Trust the I/O
        # boundary instead -- attempt to hash, and only on success
        # short-circuit; otherwise fall through to fetch.
        try:
            existing_sha = sha256_file(target)
        except FileNotFoundError:
            existing_sha = None
        if existing_sha == expected_sha:
            continue
        target.unlink(missing_ok=True)
        fetcher(f"{base_url}/{filename}", target)
        actual = sha256_file(target)
        if actual != expected_sha:
            raise RuntimeError(
                f"sha256 mismatch for {target}: expected "
                f"{expected_sha}, got {actual}"
            )

    return dsc_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch, verify, and overlay one dependency's source tree "
            "for dpkg-buildpackage."
        )
    )
    parser.add_argument("name", help="PyPI distribution name")
    parser.add_argument(
        "--map",
        default="debian/dependency-map.toml",
        help="path to the dependency map (default: debian/...)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    script_repo_root = Path(__file__).resolve().parent.parent
    map_path = Path(args.map)
    if map_path.is_absolute():
        # Custom --map path implies a custom repo root sitting two
        # levels above (so build/deps/ and packages/<source>/ resolve
        # under the same tree as the map).
        repo_root = map_path.parent.parent
    else:
        repo_root = script_repo_root
        map_path = repo_root / map_path

    dep = find_dep(map_path, args.name)
    if dep.provenance == "pypi-sdist":
        out = prepare_pypi_sdist(dep, repo_root)
    elif dep.provenance == "debian-rebuild":
        out = prepare_debian_rebuild(dep, repo_root)
    else:
        print(
            f"{dep.pypi_name}: provenance = {dep.provenance!r} is not "
            f"yet handled by this script",
            file=sys.stderr,
        )
        return 2

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
