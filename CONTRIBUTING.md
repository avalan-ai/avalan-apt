# Contributing to avalan-apt

Build and lint the Avalan package locally on Ubuntu 24.04 (Noble).
Other Ubuntu releases are out of scope.

## Host prerequisites

On a fresh Noble host, install every build dependency in one apt
invocation:

```sh
sudo apt update
sudo apt install -y \
    devscripts \
    debhelper \
    dh-python \
    pybuild-plugin-pyproject \
    sbuild \
    lintian \
    autopkgtest \
    piuparts \
    dput \
    gnupg
```

Why each is needed:

- **`devscripts`** — `dch`, `debsign`, `debuild`, and the rest of the
  release helpers used by `scripts/` and the manual release flow.
- **`debhelper`**, **`dh-python`**, **`pybuild-plugin-pyproject`** —
  the build pipeline that `debian/rules` drives; the pybuild plugin is
  what lets `dh-python` work against upstream's `pyproject.toml`.
- **`sbuild`** — clean-room build in a Noble chroot
  (`scripts/clean-build`). Needs a one-time chroot setup; those steps
  land with that script in a later phase.
- **`lintian`** — package linter (`scripts/lint-package`).
- **`autopkgtest`** — runs `debian/tests/smoke` against the built
  `.deb` (`scripts/test-package`).
- **`piuparts`** — install/remove/purge/reinstall cycle tester
  (`scripts/test-package`).
- **`dput`** — uploads signed source packages to Launchpad
  (`scripts/upload-ppa`).
- **`gnupg`** — signing key tooling; provides `gpg` plus the agents
  and pinentry that `debsign` invokes.

## Build artifacts

All build outputs — the unpacked upstream tarball, the `.dsc`,
`.debian.tar.xz`, `.deb`, `.changes` files, and sbuild logs — live
under `build/` at the repo root. `build/` is gitignored.

This is a small deviation from the Debian default of writing
artifacts to the parent directory: it keeps every byte associated
with this repo and avoids any chance of artifacts colliding with
sibling projects under `~/Code/`. `dpkg-buildpackage` writes outputs
to the parent of the source tree, so `scripts/prepare-source` unpacks
the upstream sdist to `build/avalan-<version>/` and the artifacts
land in `build/` automatically — no extra flags needed.

## Auditing the dependency map

`scripts/check-dependencies` cross-checks `debian/dependency-map.toml`
against three references: the Homebrew formula (parity baseline for
default extras), the upstream sdist's `pyproject.toml` (authoritative
constraints), and `apt-cache madison` for the Noble archive (and, in
later phases, the configured PPA index).

Default run, against the real inputs:

```sh
scripts/check-dependencies
```

The script reads the Homebrew formula from `../homebrew-avalan/Formula/
avalan.rb` and the upstream `pyproject.toml` from
`build/avalan-<version>/`, so it needs `scripts/prepare-source` to have
been run first (and the homebrew-avalan repo checked out as a sibling).
Override either with `--formula PATH` / `--pyproject PATH`.

The `apt-cache madison` call only runs on a host that has `apt-cache`
on `PATH`, i.e. a Noble VM/container. On other dev hosts, pass
`--apt-fixture PATH` (and optionally `--ppa-fixture PATH`) with JSON
files keyed by Debian package name mapping to a list of
`[[version, suite]]` pairs — see `tests/fixtures/apt_cache_ok.json` for
the shape.

Unit tests live under `tests/`:

```sh
pytest tests/
```

The tests exercise every failure mode the audit needs to catch
(`source = "unknown"`, missing row for a default-profile extra, version
below floor, missing provenance on a `source = "ppa"` row, constraint
disagreement with `pyproject.toml`) using fixture data, so they pass on
macOS or any other dev host without an apt chroot.

`packaging` (used for PEP 440 specifier comparison) is needed at
runtime; on Noble it comes from `python3-packaging`. On other hosts,
either install it system-wide or run the script via a venv that has
`packaging` available.

## Building a dependency for the Avalan PPA

Every runtime dep that doesn't ship in Noble at a satisfying version
is rebuilt or hand-packaged into the Avalan PPA — see
`debian/dependency-map.toml` for the inventory and
[`packages/README.md`](packages/README.md) for the per-dep layout
convention. The two provenance kinds are driven differently:

- `provenance = "debian-rebuild"`: `scripts/prepare-dep-source
  <name>` fetches the `.dsc` and every file it references
  (`.orig.tar.*`, `.debian.tar.*`, multi-tarball components) from
  deb.debian.org's pool into `build/deps/`, sha256-checked against
  the `Checksums-Sha256` block in the `.dsc`. The downloaded artifact
  set is bit-identical to what `dpkg-source -x` consumes; on Noble,
  run `dpkg-source -x build/deps/<source>_<version>.dsc` to unpack
  into a buildable tree, then drive the same
  `scripts/build-source` / `scripts/clean-build` flow as the top-
  level Avalan package. No new `debian/` is authored; the rebuild
  ships the Debian source as-is. (`debian_version` in
  `dependency-map.toml` is what locks the fetched version; if a
  newer Debian revision needs to be picked up, bump that field and
  re-run `prepare-dep-source`.)
- `provenance = "pypi-sdist"`: the upstream tarball is fetched from
  PyPI and overlaid with a hand-authored `debian/` under
  `packages/<source>/`. The fetch + verify + unpack + overlay step is
  what `scripts/prepare-dep-source` does; the
  `scripts/build-dep-package` wrapper chains it together with
  `dpkg-buildpackage` so a single command produces the artifact set
  on a Noble host:

  ```sh
  scripts/build-dep-package humanize             # source build (.dsc)
  scripts/build-dep-package humanize --mode binary  # .deb
  ```

  Output lands under `build/deps/` (gitignored, same as `build/`).
  `build-dep-package` handles both provenance kinds: for `pypi-sdist`
  it `cd`'s into the prepared overlayed tree; for `debian-rebuild`
  it runs `dpkg-source -x` against the verified `.dsc` first, then
  invokes `dpkg-buildpackage` from the unpacked tree. It bails out
  with a clear message on non-Debian dev hosts (no
  `dpkg-buildpackage` / `dpkg-source`) so a stray macOS invocation
  fails loudly rather than confusing the caller with a
  `FileNotFoundError`.

Tests for `scripts/prepare-dep-source` live alongside the
`check-dependencies` tests; they synthesize tarballs in memory so the
full lookup + sha-verify + overlay path runs without touching the
network.

### Running per-dep builds from a non-Linux dev host

`scripts/dockerized-build` runs `scripts/build-dep-package` inside a
clean `ubuntu:24.04` container with the repo bind-mounted at `/work`.
The container image is built from `recipes/Dockerfile.builder`, which
pre-installs the union of every Build-Depends across the per-dep
overlays (hatchling / hatch-vcs / poetry-core / pdm-backend /
setuptools-scm / quilt / lintian) plus Pillow's codec headers, so
`docker build` runs once and subsequent invocations are fast.

```sh
scripts/dockerized-build humanize             # source build (.dsc)
scripts/dockerized-build humanize --mode binary  # .deb
```

For `debian-rebuild` rows the source-only path is what gets uploaded
to Launchpad; Launchpad installs the sid Build-Depends on its own
builders. Pass `--allow-unmet-build-deps` to skip the local
`dpkg-checkbuilddeps` step so the .dsc + _source.changes generate
without insisting Noble has every sid build-dep at the right
versions:

```sh
scripts/dockerized-build jinja2 --allow-unmet-build-deps
```

The wrapper also runs `dch --local +noble --distribution noble` on
the unpacked sid source before building, bumping the version (e.g.
`3.1.6-2` -> `3.1.6-2+noble1`) and re-targeting the topmost
`debian/changelog` entry from `unstable` to `noble`. Without this,
Launchpad rejects the upload (`bad-distribution-in-changes-file
unstable`). Override the suffix with `--ppa-suffix STRING` or pass
`--ppa-suffix ''` to keep sid's metadata verbatim.

Artifacts land on the host under `build/deps/` because of the bind-
mount. Use this for slice-level verification only; the public PPA
upload still goes through `sbuild` against a real Noble chroot in
Phases 7-8.

### Tracking Phase 3 progress

`scripts/check-dependencies` ties the `packages/` tree back to the
dependency map. The default invocation passes `--packages-dir
packages` and fails on **orphan** directories — `packages/<name>/`
trees whose `pypi-sdist` row is gone from the map (typically left
behind after a row flipped to `debian-rebuild`).

Pass `--strict-overlays` to also fail on **missing** overlays: every
`pypi-sdist` row in the map must have a matching
`packages/<source>/debian/control`. That mode is opt-in because
Phase 3 is iterative — the map currently lists 16 `pypi-sdist` rows
and only a couple ship overlays. Run

```sh
scripts/check-dependencies --strict-overlays
```

to see the remaining work as a checklist; flip it to default once
every row has its overlay.
