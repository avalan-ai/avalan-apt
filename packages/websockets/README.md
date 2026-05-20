# websockets (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `websockets 16.0`). Built because `google-genai` (Avalan's
`vendors` extra) requires `websockets >= 13.0.0` and Noble ships
10.4-1 — a release that predates the asyncio.client subpackage
rename and is below the floor.

## Build backend notes

Plain setuptools. Upstream's `setup.py` builds an optional C speedups
extension (`websockets.speedups`); the rules file sets
`BUILD_EXTENSION=yes` so the extension is built (the Noble builder
image has `build-essential`), and the upstream code falls back to the
pure-Python path automatically when the extension is unavailable at
import time.

## Why pypi-sdist, not debian-rebuild

Debian sid carries `python-websockets 16.0-1` (binary package
`python3-websockets`), but the upstream `pyproject.toml` uses the
PEP 639 SPDX `license = "BSD-3-Clause"` string form. Noble's
python3-setuptools is 68 and rejects this — the string parses as
ambiguous against the auto-detected LICENSE file, and wheel metadata
validation fails before the build can run. The Avalan project does
not patch debian-rebuild rows, so the row flips to pypi-sdist and the
softening lives as a quilt patch here instead.

## What is not built

`override_dh_auto_test` skips the upstream test suite. websockets'
tests need `pytest-asyncio` and a network-fixture suite that spins up
real WS servers. Correctness for this rebuild comes from upstream CI
plus the Avalan smoke import.
