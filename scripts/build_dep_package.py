"""Drive ``prepare-dep-source`` + ``dpkg-buildpackage`` for one dep.

Looks up a row in ``debian/dependency-map.toml``, calls
``scripts/prepare_dep_source`` to materialize the source artifacts,
and then runs ``dpkg-buildpackage`` against the prepared tree:

* ``provenance = "pypi-sdist"``: prepare-dep-source already unpacks
  and overlays a ``packages/<source>/debian/`` tree on top of the
  upstream sdist. This script just ``cd``'s into that tree and runs
  ``dpkg-buildpackage``.

* ``provenance = "debian-rebuild"``: prepare-dep-source returns a
  verified ``.dsc``. This script then runs ``dpkg-source -x <dsc>``
  to unpack under ``build/deps/<source>-<upstream>/``, ``cd``'s in,
  and runs ``dpkg-buildpackage``.

Two modes:

* ``--mode source`` (default) runs ``dpkg-buildpackage -S -us -uc``,
  producing ``.dsc`` + ``.debian.tar.xz`` + ``_source.changes`` in
  ``build/deps/``.
* ``--mode binary`` runs ``dpkg-buildpackage -b -us -uc``, producing
  the per-arch ``.deb`` + ``_<arch>.changes``.

``dpkg-source`` and ``dpkg-buildpackage`` are Debian-only tools; the
script exits non-zero with a clear message if they aren't on PATH so
a stray dev-host invocation fails loudly instead of confusing the
caller with a `FileNotFoundError`.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import prepare_dep_source as pds


def _require_tools(tools: Sequence[str]) -> None:
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        names = ", ".join(missing)
        raise EnvironmentError(
            f"{names} not on PATH. dpkg/devscripts only exist on "
            f"Debian-based hosts; run scripts/build-dep-package from "
            f"a Noble VM/container."
        )


def _source_tree_for_dsc(dsc_path: Path) -> Path:
    """Where ``dpkg-source -x`` will unpack a ``.dsc``.

    ``dpkg-source -x foo_<upstream>-<revision>.dsc`` writes the
    unpacked tree to ``foo-<upstream>/`` (without the Debian
    revision). Build that path from the ``.dsc`` filename without
    actually running dpkg-source first, so the caller can choose to
    overwrite or skip.
    """
    stem = dsc_path.name.removesuffix(".dsc")
    source, _, version = stem.partition("_")
    upstream = version.split("-", 1)[0]
    return dsc_path.parent / f"{source}-{upstream}"


def build_pypi_sdist(
    dep: pds.DepRow,
    repo_root: Path,
    *,
    mode: str,
    runner=subprocess.run,
    allow_unmet_build_deps: bool = False,
) -> Path:
    src_dir = pds.prepare_pypi_sdist(dep, repo_root)
    runner(
        _build_args(mode, allow_unmet_build_deps=allow_unmet_build_deps),
        cwd=str(src_dir),
        check=True,
    )
    return src_dir


def build_debian_rebuild(
    dep: pds.DepRow,
    repo_root: Path,
    *,
    mode: str,
    runner=subprocess.run,
    allow_unmet_build_deps: bool = False,
    ppa_suffix: str = "+noble",
) -> Path:
    dsc_path = pds.prepare_debian_rebuild(dep, repo_root)
    src_dir = _source_tree_for_dsc(dsc_path)
    if src_dir.exists():
        shutil.rmtree(src_dir)
    runner(
        ["dpkg-source", "-x", str(dsc_path), str(src_dir)],
        check=True,
    )
    if ppa_suffix:
        _retarget_to_noble(src_dir, suffix=ppa_suffix, runner=runner)
    runner(
        _build_args(mode, allow_unmet_build_deps=allow_unmet_build_deps),
        cwd=str(src_dir),
        check=True,
    )
    return src_dir


def _retarget_to_noble(
    src_dir: Path,
    *,
    suffix: str,
    runner=subprocess.run,
) -> None:
    """Bump the source's version with ``<suffix>`` and re-target the
    top changelog entry to noble.

    Debian sid's source packages declare ``Distribution: unstable`` in
    the topmost ``debian/changelog`` entry, which Launchpad rejects on
    a noble-targeted PPA upload. ``dch --local <suffix>`` appends the
    suffix to the version (e.g. ``3.1.6-2`` -> ``3.1.6-2+noble1``) and
    creates a new entry; ``--distribution noble --force-distribution``
    sets the target. The added entry carries a single line stating
    the rebuild is source-identical to the Debian original so the
    audit trail is honest about us not having touched the source.
    """
    runner(
        [
            "dch",
            "--local",
            suffix,
            "--distribution",
            "noble",
            "--force-distribution",
            "Rebuild for the Avalan PPA. No source changes.",
        ],
        cwd=str(src_dir),
        check=True,
    )


_BUILD_FLAGS = {
    "source": ["-S", "-us", "-uc"],
    "binary": ["-b", "-us", "-uc"],
}


def _build_args(
    mode: str, *, allow_unmet_build_deps: bool = False
) -> list[str]:
    try:
        flags = list(_BUILD_FLAGS[mode])
    except KeyError as exc:
        raise ValueError(
            f"unknown build mode {mode!r}; "
            f"expected one of {sorted(_BUILD_FLAGS)}"
        ) from exc
    if allow_unmet_build_deps:
        # -d disables dpkg-checkbuilddeps; useful for source-only
        # builds of debian-rebuild rows where sid's Build-Depends do
        # not all exist in Noble's archive. Launchpad installs build
        # deps from its own profile on the builders, so a clean .dsc
        # is enough for upload even when local install is incomplete.
        flags.append("-d")
    return ["dpkg-buildpackage", *flags]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="PyPI distribution name")
    parser.add_argument(
        "--mode",
        choices=sorted(_BUILD_FLAGS),
        default="source",
        help="dpkg-buildpackage flavor (default: source)",
    )
    parser.add_argument(
        "--map",
        default="debian/dependency-map.toml",
        help="path to the dependency map (default: debian/...)",
    )
    parser.add_argument(
        "--allow-unmet-build-deps",
        action="store_true",
        help=(
            "pass -d to dpkg-buildpackage so the build does not require "
            "every Build-Depends to be installed locally. Useful for "
            "source-only builds of debian-rebuild rows where sid's "
            "build-deps differ from Noble's archive; Launchpad still "
            "installs them on its own builders."
        ),
    )
    parser.add_argument(
        "--ppa-suffix",
        default="+noble",
        help=(
            "for debian-rebuild rows, append this suffix to the source "
            "version and re-target the topmost debian/changelog entry "
            "to noble before building (so Launchpad accepts the upload "
            "instead of rejecting 'Distribution: unstable'). dch's "
            "--local mode appends an incrementing digit after the "
            "suffix, so default '+noble' produces '<orig>+noble1'. "
            "Pass an empty string to skip the rewrite. "
            "Default: %(default)s."
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner=subprocess.run,
    tool_checker=_require_tools,
) -> int:
    args = build_parser().parse_args(argv)
    script_repo_root = Path(__file__).resolve().parent.parent
    map_path = Path(args.map)
    if map_path.is_absolute():
        # Custom --map path implies a custom repo root sitting two
        # levels above (so packaging overlays resolve under the same
        # tree). Test invocations rely on this.
        repo_root = map_path.parent.parent
    else:
        repo_root = script_repo_root
        map_path = repo_root / map_path

    dep = pds.find_dep(map_path, args.name)

    if dep.provenance == "pypi-sdist":
        tool_checker(["dpkg-buildpackage"])
        out = build_pypi_sdist(
            dep,
            repo_root,
            mode=args.mode,
            runner=runner,
            allow_unmet_build_deps=args.allow_unmet_build_deps,
        )
    elif dep.provenance == "debian-rebuild":
        required = ["dpkg-source", "dpkg-buildpackage"]
        if args.ppa_suffix:
            required.append("dch")
        tool_checker(required)
        out = build_debian_rebuild(
            dep,
            repo_root,
            mode=args.mode,
            runner=runner,
            allow_unmet_build_deps=args.allow_unmet_build_deps,
            ppa_suffix=args.ppa_suffix,
        )
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
