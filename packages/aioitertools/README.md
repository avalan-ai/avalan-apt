# aioitertools (Avalan PPA transitive)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `aioitertools 0.13.0`). Required transitively by
`aiobotocore` (Avalan's `vendors` extra, reached via `aioboto3`).
Noble does not ship it at all.

## Build backend notes

Upstream uses `flit_core >=3.11,<4`. Noble ships `flit 3.9.0-2`
which bundles `flit_core 3.9.0`. A quilt patch
(`pyproject-for-noble`) softens the build-system pin to plain
`flit_core`, rewrites the PEP 639 SPDX `license = "MIT"` string to
the legacy `license = { file = "LICENSE" }` table form, and drops
the `license-files = ["LICENSE"]` key — none of which flit_core 3.9
understands. The wheel metadata still carries the LICENSE file via
the table form.

The runtime is pure Python with no dependencies on Python 3.10+
(`typing_extensions` is the only stated runtime dep and is gated to
`python_version < '3.10'`); Noble's Python 3.12 sees zero runtime
requirements.

## What is not built

Nothing is excluded — the upstream test suite runs under
`unittest discover` and passes on Noble's stdlib, so `dh_auto_test`
runs it during the build.
