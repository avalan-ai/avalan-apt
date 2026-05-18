# playwright (Avalan PPA pin)

Hand-packaged from the upstream GitHub source archive pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `playwright 1.55.0`). Avalan tracks `>= 1.54, < 2.0`.

## Flipped from debian-rebuild

The first cut of this row used `provenance = "debian-rebuild"` against
Debian sid's `python-playwright 1.55.0+ds-2`. Sid's source still ships
the upstream PEP 639 `license = "Apache-2.0"` SPDX form, which Noble's
older `python3-setuptools` rejects during `dh_auto_clean` ("`project.
license` must be valid exactly by one definition"). APT.md forbids
landing Avalan-side patches on debian-rebuild rows, so the cleanest
fix was the flip: source comes from upstream's GitHub tag instead,
and the license tweak lives in `debian/patches/`.

## Source archive notes

Upstream's PyPI distribution is wheels-only: each wheel bundles a
platform-specific copy of the Playwright Node.js driver plus the
chromium/firefox/webkit pre-built browsers. We do not want any of
that in the apt-installed package, so the sdist URL points at
GitHub's `archive/refs/tags/v1.55.0.tar.gz` instead. The downloaded
tarball unpacks to `playwright-python-1.55.0/`; `prepare-dep-source`
renames it to `playwright-1.55.0/` to match the dashed source name.

## Build backend notes

setuptools.build_meta with setuptools-scm for the dynamic version.
`debian/rules` pins `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PLAYWRIGHT=
1.55.0` because the GitHub archive has neither a `PKG-INFO` (sdist
fallback) nor a `.git` directory (VCS fallback). Without the pin
setuptools-scm errors out trying to determine the version.

`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` and
`PLAYWRIGHT_SKIP_DRIVER_DOWNLOAD=1` in `debian/rules` instruct
upstream's `setup.py` to skip the network fetch of the Node.js
driver bundle and the browser binaries. That keeps the build offline
(matches the global `PIP_NO_INDEX=1`) and ensures the resulting
`.deb` does not redistribute upstream's bundled Chromium build.

## What is not built

- **Browser drivers and browser binaries** -- the wheel form ships
  ~150 MB per platform of bundled Node.js driver + browser binaries.
  Our rebuild includes only the pure-Python client. Users install
  chromium or firefox via apt (Recommends), and Playwright drives
  whichever browser the user has installed.
- **Test suite** -- `override_dh_auto_test` skips. The upstream
  suite needs a running browser plus floor pins on pytest-asyncio
  that don't reliably match Noble's archive.

## Quilt patch: pyproject-for-noble

Relaxes the strict `==` pins on upstream's `[build-system].requires`
(`setuptools==80.9.0`, `setuptools-scm==8.3.1`, `wheel==0.45.1`,
`auditwheel==6.2.0`) to lower bounds Noble actually has, and
rewrites `license = "Apache-2.0"` to the legacy
`license = { text = "Apache-2.0" }` table form. Wheel metadata is
equivalent; no runtime impact.
