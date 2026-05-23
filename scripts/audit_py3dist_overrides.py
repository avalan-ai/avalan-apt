"""Audit hand-packaged deps for missing py3dist-overrides entries.

For each row in ``debian/dependency-map.toml`` with ``source = "ppa"``:

1. Parse upstream ``Requires-Dist`` from the dep's ``.orig`` tarball
   under ``build/deps/`` (or wherever the cached source lives), skipping
   any entry whose environment marker references ``extra == "<name>"``
   -- those are opt-in install extras and don't belong in default
   Depends.
2. Cross-reference each required dist against the set of OTHER
   hand-packaged PyPI names from the same map.
3. Read the binary ``.deb``'s ``Depends`` and check which intra-PPA
   names are actually present.
4. Flag any cross-reference that should be in Depends but isn't, and
   note whether a ``packages/<dep>/debian/py3dist-overrides`` already
   handles the missing mapping.

Use::

    scripts/audit-py3dist-overrides

Requires ``dpkg-deb`` on PATH, so on a non-Debian dev host run the
script inside the builder container::

    docker run --rm --platform=linux/amd64 --volume "$PWD:/work" \
        --workdir /work avalan-apt-builder:noble \
        scripts/audit-py3dist-overrides
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGES_DIR = REPO / "packages"
BUILD_DEPS = REPO / "build" / "deps"


def canon(name: str) -> str:
    """Canonicalize a PyPI distribution name (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def pyname_to_deb(name: str) -> str:
    return f"python3-{canon(name)}"


def hand_packaged_pypi_names() -> set[str]:
    data = tomllib.loads(
        (REPO / "debian" / "dependency-map.toml").read_text()
    )
    return {
        canon(d["pypi_name"])
        for d in data.get("dep", ())
        if d.get("source") == "ppa"
    }


def parse_requires_dist(text: str) -> list[str]:
    """Distribution names from PKG-INFO ``Requires-Dist`` lines,
    SKIPPING entries gated on an ``extra ==`` marker."""
    out: list[str] = []
    for line in text.splitlines():
        if not line.startswith("Requires-Dist:"):
            continue
        spec = line.split(":", 1)[1].strip()
        if ";" in spec:
            head, marker = spec.split(";", 1)
            if "extra" in marker and "==" in marker:
                continue
            spec = head
        name = re.split(r"[<>=! ]", spec, 1)[0]
        name = re.sub(r"\[[^\]]*\]", "", name).strip()
        if name:
            out.append(name)
    return out


def extract_upstream_requires(orig_tar: Path) -> list[str]:
    """Return Requires-Dist from PKG-INFO inside the .orig tarball.
    Prefers the top-level PKG-INFO; falls back to any nested one."""
    try:
        with tarfile.open(orig_tar) as tar:
            top_level: list[str] | None = None
            nested: list[str] | None = None
            for member in tar.getmembers():
                if not member.name.endswith("PKG-INFO"):
                    continue
                fh = tar.extractfile(member)
                if not fh:
                    continue
                payload = fh.read().decode("utf-8", errors="replace")
                parsed = parse_requires_dist(payload)
                # Top-level PKG-INFO has exactly one '/' in the path.
                if member.name.count("/") == 1:
                    top_level = parsed
                elif nested is None:
                    nested = parsed
            if top_level is not None:
                return top_level
            if nested is not None:
                return nested
    except (FileNotFoundError, tarfile.TarError):
        pass
    return []


def find_orig_tarball(pyname: str) -> Path | None:
    candidates: list[Path] = []
    for ext in (".orig.tar.gz", ".orig.tar.xz", ".orig.tar.bz2"):
        for variant in (pyname, pyname.replace("-", "_")):
            candidates.extend(BUILD_DEPS.glob(f"{variant}_*{ext}"))
    return candidates[0] if candidates else None


def find_deb(pyname: str) -> Path | None:
    deb = pyname_to_deb(pyname)
    hits = sorted(
        BUILD_DEPS.glob(f"{deb}_*.deb"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return hits[0] if hits else None


def deb_depends(deb: Path) -> set[str]:
    out = subprocess.check_output(["dpkg-deb", "-I", str(deb)], text=True)
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Depends:"):
            return {
                part.strip().split(" ", 1)[0]
                for part in line[len("Depends:"):].split(",")
                if part.strip()
            }
    return set()


def has_override(dep_dir_name: str, override_for: str) -> bool:
    p = PACKAGES_DIR / dep_dir_name / "debian" / "py3dist-overrides"
    if not p.exists():
        return False
    target = canon(override_for)
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split(None, 1)[0]
        if canon(head) == target:
            return True
    return False


def main() -> int:
    if shutil.which("dpkg-deb") is None:
        print(
            "FATAL: dpkg-deb not on PATH. Run this script inside the "
            "avalan-apt-builder container:\n"
            "  docker run --rm --platform=linux/amd64 "
            "--volume \"$PWD:/work\" --workdir /work "
            "avalan-apt-builder:noble scripts/audit-py3dist-overrides",
            file=sys.stderr,
        )
        return 2

    hand = hand_packaged_pypi_names()
    dirs = {d.name for d in PACKAGES_DIR.iterdir() if d.is_dir()}

    problems = 0
    for dep_dir_name in sorted(dirs):
        canon_pyname = canon(dep_dir_name)
        if canon_pyname not in hand:
            continue
        orig = find_orig_tarball(canon_pyname)
        if not orig:
            print(
                f"  {dep_dir_name}: no orig tarball under "
                f"build/deps/, skipping (run scripts/prepare-dep-source "
                f"{dep_dir_name} first)"
            )
            continue
        requires = extract_upstream_requires(orig)
        intra_ppa = sorted({
            canon(r)
            for r in requires
            if canon(r) in hand and canon(r) != canon_pyname
        })
        if not intra_ppa:
            continue
        deb = find_deb(canon_pyname)
        if not deb:
            print(
                f"  {dep_dir_name}: no .deb under build/deps/, "
                f"can't verify (run scripts/build-dep-package "
                f"{dep_dir_name} --mode binary)"
            )
            continue
        depends = deb_depends(deb)
        for ref in intra_ppa:
            expected_deb = pyname_to_deb(ref)
            if expected_deb in depends:
                continue
            mark = (
                "(has override)"
                if has_override(dep_dir_name, ref)
                else "MISSING OVERRIDE"
            )
            print(
                f"  {dep_dir_name}: upstream Requires-Dist names {ref} "
                f"but the .deb's Depends omits {expected_deb}  {mark}"
            )
            if mark == "MISSING OVERRIDE":
                problems += 1
    print()
    print(f"{problems} hand-packaged dep(s) need new py3dist-overrides entries.")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
