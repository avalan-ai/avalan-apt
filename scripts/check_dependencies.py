"""Audit debian/dependency-map.toml against the upstream sdist, the
Homebrew formula, and apt-cache madison.

Run from the repo root as either ``scripts/check-dependencies`` (the
POSIX shim) or ``python3 scripts/check_dependencies.py``. The module is
also importable so tests can drive ``main()`` directly with fixture
inputs.

Inputs
------
* ``--formula PATH``    Homebrew formula. Provides ``EXTRAS`` (parity
                        baseline) and the upstream sha256 / version
                        embedded in the ``url`` line.
* ``--pyproject PATH``  Upstream sdist's pyproject.toml. The authority
                        for every dependency constraint.
* ``--map PATH``        debian/dependency-map.toml — what we are
                        auditing.
* ``--apt-fixture PATH``   JSON dict of ``pkg -> [[version, suite]]``.
                        Replaces ``apt-cache madison`` on hosts without
                        a Noble chroot.
* ``--ppa-fixture PATH``   Same shape, but for the configured PPA.
* ``--live-ppa``        Query ``apt-cache madison`` for ``ppa`` rows
                        too. Use on a Noble host that already has the
                        Avalan PPA configured -- the same apt query
                        answers both source kinds because the madison
                        output combines every configured archive.

When ``--apt-fixture`` is not supplied the script invokes
``apt-cache madison`` directly. When neither ``--ppa-fixture`` nor
``--live-ppa`` is supplied, only PPA metadata (provenance,
source-package or sdist references) is audited.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


VALID_SOURCES = ("noble", "ppa", "unknown")
VALID_PROVENANCES = ("debian-rebuild", "pypi-sdist")
BASE_EXTRA = "base"


@dataclass(frozen=True)
class FormulaSnapshot:
    version: str
    sha256: str
    extras: tuple[str, ...]


@dataclass(frozen=True)
class PyprojectSnapshot:
    base: dict[str, str]
    extras: dict[str, dict[str, str]]

    def all_required(self, default_extras: Iterable[str]) -> dict[str, str]:
        merged: dict[str, str] = dict(self.base)
        for extra in default_extras:
            merged.update(self.extras.get(extra, {}))
        return merged


@dataclass(frozen=True)
class MapDep:
    pypi_name: str
    constraint: str
    debian_name: str
    extra: str
    source: str
    min_version: str
    notes: str = ""
    provenance: str = ""
    debian_source_pkg: str = ""
    debian_suite: str = ""
    debian_version: str = ""
    sdist_url: str = ""
    sdist_sha256: str = ""
    transitive_of: str = ""


@dataclass(frozen=True)
class DepMap:
    upstream_version: str
    homebrew_formula_sha: str
    deps: tuple[MapDep, ...]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


_URL_VERSION_RE = re.compile(r"avalan-([0-9][^/]+?)\.tar\.gz")
_SHA256_RE = re.compile(r'^\s*sha256\s+"([0-9a-fA-F]+)"', re.MULTILINE)
_EXTRAS_RE = re.compile(
    r"EXTRAS\s*=\s*%w\[([^\]]*)\]", re.MULTILINE
)


def parse_homebrew_formula(text: str) -> FormulaSnapshot:
    version_m = _URL_VERSION_RE.search(text)
    if not version_m:
        raise ValueError("formula: no avalan-<version>.tar.gz in url")
    sha_m = _SHA256_RE.search(text)
    if not sha_m:
        raise ValueError('formula: no sha256 "<...>" line')
    extras_m = _EXTRAS_RE.search(text)
    if not extras_m:
        raise ValueError("formula: no EXTRAS = %w[...] declaration")
    extras = tuple(extras_m.group(1).split())
    return FormulaSnapshot(
        version=version_m.group(1),
        sha256=sha_m.group(1).lower(),
        extras=extras,
    )


def parse_pyproject(text: str) -> PyprojectSnapshot:
    data = tomllib.loads(text)
    project = data.get("project") or {}
    base = _parse_requirements(project.get("dependencies") or [])
    raw_extras = project.get("optional-dependencies") or {}
    extras: dict[str, dict[str, str]] = {}
    for name, reqs in raw_extras.items():
        extras[name] = _parse_requirements(reqs)
    return PyprojectSnapshot(base=base, extras=extras)


def _parse_requirements(items: Sequence[str]) -> dict[str, str]:
    """Return ``canonical_pypi_name -> raw specifier string`` (as
    written upstream, e.g. ``>=14.1.0,<15.0.0``).

    Equality checks against the dependency map happen via
    :class:`SpecifierSet` so reorderings (``>=X,<Y`` vs ``<Y,>=X``)
    don't trip the audit; the raw string is kept only for human-
    readable error messages.
    """
    parsed: dict[str, str] = {}
    for item in items:
        req = Requirement(item)
        parsed[canonicalize_name(req.name)] = _raw_specifier(item)
    return parsed


_NAME_PREFIX_RE = re.compile(r"^[A-Za-z0-9_.\-]+\s*")


def _raw_specifier(requirement: str) -> str:
    """Strip the distribution-name prefix off a requirement string,
    leaving the constraint exactly as written (so a SpecifierSet
    round-trip doesn't reorder the operands in error messages).
    """
    stripped = _NAME_PREFIX_RE.sub("", requirement, count=1)
    # Drop any environment marker (``; python_version < '3.13'``) —
    # the audit ignores markers; they live in the upstream wheel.
    if ";" in stripped:
        stripped = stripped.split(";", 1)[0]
    return stripped.strip()


def parse_dep_map(text: str) -> DepMap:
    data = tomllib.loads(text)
    meta = data.get("meta") or {}
    raw_deps = data.get("dep") or []
    deps = tuple(
        MapDep(
            pypi_name=entry["pypi_name"],
            constraint=entry["constraint"],
            debian_name=entry["debian_name"],
            extra=entry["extra"],
            source=entry["source"],
            min_version=entry["min_version"],
            notes=entry.get("notes", ""),
            provenance=entry.get("provenance", ""),
            debian_source_pkg=entry.get("debian_source_pkg", ""),
            debian_suite=entry.get("debian_suite", ""),
            debian_version=entry.get("debian_version", ""),
            sdist_url=entry.get("sdist_url", ""),
            sdist_sha256=entry.get("sdist_sha256", ""),
            transitive_of=entry.get("transitive_of", ""),
        )
        for entry in raw_deps
    )
    return DepMap(
        upstream_version=meta.get("upstream_version", ""),
        homebrew_formula_sha=meta.get("homebrew_formula_sha", ""),
        deps=deps,
    )


# ---------------------------------------------------------------------------
# APT/PPA querying
# ---------------------------------------------------------------------------

AptQuery = Callable[[str], list[tuple[str, str]]]


def fixture_query(data: Mapping[str, Sequence[Sequence[str]]]) -> AptQuery:
    table = {
        key: [tuple(row) for row in rows] for key, rows in data.items()
    }

    def query(name: str) -> list[tuple[str, str]]:
        return list(table.get(name, []))

    return query


def real_apt_madison_query() -> AptQuery | None:
    """Return a callable that shells out to apt-cache madison, or
    ``None`` if apt-cache isn't on PATH (e.g. macOS dev host)."""
    if shutil.which("apt-cache") is None:
        return None

    def query(name: str) -> list[tuple[str, str]]:
        proc = subprocess.run(
            ["apt-cache", "madison", name],
            capture_output=True,
            text=True,
            check=False,
        )
        rows: list[tuple[str, str]] = []
        for line in proc.stdout.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                rows.append((parts[1], parts[2]))
        return rows

    return query


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.errors.append(msg)

    def ok(self) -> bool:
        return not self.errors


def verify_parity(
    formula: FormulaSnapshot,
    pyproject: PyprojectSnapshot,
    depmap: DepMap,
    report: Report,
) -> None:
    """Confirm formula EXTRAS, pyproject deps, and depmap rows agree.

    Three independently-maintained inputs ought to describe the same
    package; this is where drift surfaces.
    """
    formula_extras = set(formula.extras)
    map_extras = {dep.extra for dep in depmap.deps if dep.extra != BASE_EXTRA}
    pyproject_extras = set(pyproject.extras.keys())

    missing_in_pyproject = formula_extras - pyproject_extras
    for extra in sorted(missing_in_pyproject):
        report.fail(
            f"formula EXTRAS lists {extra!r} but pyproject.toml "
            f"[project.optional-dependencies] has no entry for it"
        )

    missing_in_map = formula_extras - map_extras
    for extra in sorted(missing_in_map):
        report.fail(
            f"formula EXTRAS lists {extra!r} but dependency-map.toml "
            f"has no [[dep]] rows with extra = {extra!r}"
        )

    extra_in_map = map_extras - formula_extras
    for extra in sorted(extra_in_map):
        report.fail(
            f"dependency-map.toml has rows for extra {extra!r} but "
            f"formula EXTRAS does not list it (drift from upstream "
            f"default profile)"
        )

    required = pyproject.all_required(formula_extras)
    map_by_pypi = {
        canonicalize_name(dep.pypi_name): dep for dep in depmap.deps
    }

    for canon_name, specifier in required.items():
        dep = map_by_pypi.get(canon_name)
        if dep is None:
            report.fail(
                f"pyproject.toml requires {canon_name!r} (constraint "
                f"{specifier!r}) but dependency-map.toml has no row "
                f"for it"
            )
            continue
        if SpecifierSet(specifier) != SpecifierSet(dep.constraint):
            report.fail(
                f"{canon_name}: pyproject.toml constraint {specifier!r} "
                f"does not match dependency-map.toml constraint "
                f"{dep.constraint!r}"
            )

    direct_pypi_names = {
        canonicalize_name(dep.transitive_of)
        for dep in depmap.deps
        if dep.transitive_of
    }
    base_canon = {canonicalize_name(n) for n in pyproject.base}
    for_canon = {canonicalize_name(n) for n in required}
    for dep in depmap.deps:
        canon = canonicalize_name(dep.pypi_name)
        if dep.transitive_of:
            # Transitive rows -- packaged because one of Avalan's
            # direct deps requires them. Skip the "must be in
            # pyproject" check; the parent dep is the one that has
            # to be in pyproject.
            if (
                canonicalize_name(dep.transitive_of) not in for_canon
            ):
                report.fail(
                    f"{dep.pypi_name}: transitive_of = "
                    f"{dep.transitive_of!r} but that dep is not in "
                    f"pyproject.toml's default profile"
                )
            continue
        if canon not in for_canon:
            report.fail(
                f"dependency-map.toml has row for {dep.pypi_name!r} but "
                f"the upstream pyproject default profile does not "
                f"require it"
            )
            continue
        expected_extra = BASE_EXTRA if canon in base_canon else None
        if expected_extra == BASE_EXTRA and dep.extra != BASE_EXTRA:
            report.fail(
                f"{dep.pypi_name}: marked extra = {dep.extra!r} but "
                f"appears in pyproject.toml [project] dependencies "
                f"(should be {BASE_EXTRA!r})"
            )


def verify_row_metadata(dep: MapDep, report: Report) -> None:
    if dep.source not in VALID_SOURCES:
        report.fail(
            f"{dep.pypi_name}: source = {dep.source!r} is not one of "
            f"{list(VALID_SOURCES)}"
        )
        return
    if dep.source == "unknown":
        report.fail(
            f"{dep.pypi_name}: source = 'unknown' — every row must be "
            f"resolved to 'noble' or 'ppa' before upload"
        )
        return
    if dep.source == "ppa":
        if dep.provenance not in VALID_PROVENANCES:
            report.fail(
                f"{dep.pypi_name}: source = 'ppa' requires provenance "
                f"in {list(VALID_PROVENANCES)} (got {dep.provenance!r})"
            )
            return
        if dep.provenance == "debian-rebuild":
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
                report.fail(
                    f"{dep.pypi_name}: provenance = 'debian-rebuild' "
                    f"requires {', '.join(missing)}"
                )
        elif dep.provenance == "pypi-sdist":
            if not dep.sdist_url or not dep.sdist_sha256:
                report.fail(
                    f"{dep.pypi_name}: provenance = 'pypi-sdist' "
                    f"requires both sdist_url and sdist_sha256"
                )


def _versions(rows: Sequence[tuple[str, str]]) -> list[Version]:
    versions: list[Version] = []
    for raw, _suite in rows:
        cleaned = re.sub(r"^[0-9]+:", "", raw)
        cleaned = re.split(r"[-+~]", cleaned, maxsplit=1)[0]
        try:
            versions.append(Version(cleaned))
        except InvalidVersion:
            continue
    return versions


def verify_availability(
    dep: MapDep,
    apt: AptQuery | None,
    ppa: AptQuery | None,
    report: Report,
) -> None:
    if dep.source == "noble" and apt is not None:
        rows = apt(dep.debian_name)
        _enforce_floor(dep, rows, report, label="Noble")
        return
    if dep.source == "ppa" and ppa is not None:
        rows = ppa(dep.debian_name)
        _enforce_floor(dep, rows, report, label="PPA")


def _source_name(pypi_name: str) -> str:
    """Debian source directory name for a pypi-sdist row.

    Mirrors the convention in scripts/prepare_dep_source.py — lowercase
    the PyPI name and replace underscores with dashes.
    """
    return pypi_name.lower().replace("_", "-")


def verify_packaging_overlays(
    depmap: DepMap,
    packages_dir: Path,
    report: Report,
    *,
    strict_missing: bool = False,
) -> None:
    """Tie pypi-sdist rows to packages/<source>/debian/ overlays.

    Two checks land here. The orphan check (always on) catches stale
    ``packages/<dir>/`` overlays whose row is gone from the dependency
    map — these are real bugs because they imply a row flipped
    provenance or got deleted without cleaning up the on-disk tree.

    The missing-overlay check is gated behind ``strict_missing``:
    during Phase 3 the dependency map lists more pypi-sdist rows than
    the repo has packaged yet, so failing on missing overlays would
    spam every run. Future slices can flip ``strict_missing`` on once
    every pypi-sdist row has its overlay.
    """
    expected: dict[str, MapDep] = {
        _source_name(dep.pypi_name): dep
        for dep in depmap.deps
        if dep.source == "ppa" and dep.provenance == "pypi-sdist"
    }
    if strict_missing:
        for name, dep in expected.items():
            control = packages_dir / name / "debian" / "control"
            if not control.is_file():
                report.fail(
                    f"{dep.pypi_name}: provenance = 'pypi-sdist' but "
                    f"{control} is missing — create the packaging "
                    f"overlay under packages/{name}/debian/ before "
                    f"building"
                )

    if not packages_dir.is_dir():
        return
    for child in sorted(packages_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name in expected:
            continue
        report.fail(
            f"packages/{child.name}/ has no matching pypi-sdist row in "
            f"the dependency map — drop the overlay or add the row"
        )


def _enforce_floor(
    dep: MapDep,
    rows: Sequence[tuple[str, str]],
    report: Report,
    *,
    label: str,
) -> None:
    if not rows:
        report.fail(
            f"{dep.debian_name}: not found in {label} index "
            f"(required for {dep.pypi_name})"
        )
        return
    try:
        floor = Version(dep.min_version)
    except InvalidVersion:
        report.fail(
            f"{dep.pypi_name}: min_version {dep.min_version!r} is not "
            f"PEP 440-parseable"
        )
        return
    available = _versions(rows)
    if not available or max(available) < floor:
        seen = ", ".join(v for v, _ in rows) or "(empty)"
        report.fail(
            f"{dep.debian_name}: {label} has {seen}, below floor "
            f"{dep.min_version} for {dep.pypi_name}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_fixture(path: str | None) -> AptQuery | None:
    if path is None:
        return None
    data = json.loads(Path(path).read_text())
    return fixture_query(data)


def _default_pyproject_path(repo_root: Path) -> Path:
    release_toml = repo_root / "release.toml"
    if not release_toml.is_file():
        raise FileNotFoundError(
            f"{release_toml}: no release.toml; pass --pyproject"
        )
    release = tomllib.loads(release_toml.read_text())
    version = release["upstream"]["version"]
    candidate = repo_root / "build" / f"avalan-{version}" / "pyproject.toml"
    if not candidate.is_file():
        raise FileNotFoundError(
            f"{candidate}: not found; run scripts/prepare-source "
            f"first or pass --pyproject"
        )
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit debian/dependency-map.toml against the upstream "
            "sdist, the Homebrew formula, and apt-cache madison."
        )
    )
    parser.add_argument(
        "--formula",
        default="../homebrew-avalan/Formula/avalan.rb",
        help="path to the Homebrew formula (default: sibling repo)",
    )
    parser.add_argument(
        "--pyproject",
        default=None,
        help=(
            "path to the upstream pyproject.toml (default: derived "
            "from release.toml + build/avalan-<version>/)"
        ),
    )
    parser.add_argument(
        "--map",
        default="debian/dependency-map.toml",
        help="path to the dependency map (default: debian/...)",
    )
    parser.add_argument(
        "--apt-fixture",
        default=None,
        help=(
            "JSON file of apt-cache madison results, keyed by package "
            "name. When unset, the script invokes apt-cache madison."
        ),
    )
    parser.add_argument(
        "--ppa-fixture",
        default=None,
        help=(
            "JSON file of PPA index results. When unset, ppa rows are "
            "checked for required metadata only; the live index is "
            "not queried."
        ),
    )
    parser.add_argument(
        "--live-ppa",
        action="store_true",
        help=(
            "query apt-cache madison for ppa rows in addition to noble "
            "rows. Use when running on a Noble host that already has "
            "the Avalan PPA configured: apt-cache madison returns "
            "every source's versions combined, so the same query "
            "answers both source kinds. Mutually exclusive with "
            "--ppa-fixture."
        ),
    )
    parser.add_argument(
        "--packages-dir",
        default=None,
        help=(
            "path to the per-dep packaging tree (default: skip). When "
            "set, every subdirectory must correspond to a pypi-sdist "
            "row in the map (orphans fail the audit)."
        ),
    )
    parser.add_argument(
        "--strict-overlays",
        action="store_true",
        help=(
            "additionally require every pypi-sdist row to have its "
            "<packages-dir>/<source>/debian/control overlay present. "
            "Opt-in until Phase 3 has packaged every pypi-sdist row."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    formula_path = Path(args.formula)
    if not formula_path.is_absolute():
        formula_path = repo_root / formula_path

    pyproject_path = (
        Path(args.pyproject)
        if args.pyproject
        else _default_pyproject_path(repo_root)
    )

    map_path = Path(args.map)
    if not map_path.is_absolute():
        map_path = repo_root / map_path

    formula = parse_homebrew_formula(formula_path.read_text())
    pyproject = parse_pyproject(pyproject_path.read_text())
    depmap = parse_dep_map(map_path.read_text())

    report = Report()
    verify_parity(formula, pyproject, depmap, report)

    if args.live_ppa and args.ppa_fixture is not None:
        parser.error("--live-ppa and --ppa-fixture are mutually exclusive")

    apt = _load_fixture(args.apt_fixture)
    if apt is None:
        apt = real_apt_madison_query()
    ppa = _load_fixture(args.ppa_fixture)
    if args.live_ppa:
        if apt is None:
            report.fail(
                "--live-ppa requires apt-cache on PATH; run on a Noble "
                "host with the Avalan PPA configured."
            )
        else:
            ppa = apt

    needs_noble_query = any(d.source == "noble" for d in depmap.deps)
    if needs_noble_query and apt is None:
        report.fail(
            "apt-cache not available and no --apt-fixture provided; "
            "Noble availability check skipped. Run on a Noble host or "
            "pass --apt-fixture."
        )

    for dep in depmap.deps:
        verify_row_metadata(dep, report)
        verify_availability(dep, apt, ppa, report)

    if args.packages_dir is not None:
        packages_dir = Path(args.packages_dir)
        if not packages_dir.is_absolute():
            packages_dir = repo_root / packages_dir
        verify_packaging_overlays(
            depmap,
            packages_dir,
            report,
            strict_missing=args.strict_overlays,
        )

    if not report.ok():
        for err in report.errors:
            print(f"FATAL: {err}", file=sys.stderr)
        print(
            f"{len(report.errors)} dependency-map issue(s) found.",
            file=sys.stderr,
        )
        return 1

    extras_summary = ", ".join(formula.extras) or "(none)"
    print(
        f"OK: {len(depmap.deps)} deps verified against formula "
        f"(extras: {extras_summary})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
