# anyio (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `anyio 4.12.1`). Built because `mcp` (Avalan's `server`
extras) requires `anyio >= 4.5` and Noble ships 4.2.0. The same pin
also covers `google-genai`'s stricter `>= 4.8.0` floor once that row
is packaged.

## Build backend notes

setuptools + setuptools_scm. The upstream sdist embeds no
`tool.setuptools_scm` configuration and ships no git tree, so
`setuptools-scm` would otherwise fall back to `0.0.0`. The rules file
pins `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_ANYIO=4.12.1` so the wheel
inherits the upstream tag.

## Why pypi-sdist, not debian-rebuild

Debian sid carries `python-anyio 4.12.1-1`, but its pyproject pins
`setuptools >= 77` and uses the PEP 639 SPDX `license = "MIT"`
string form. Noble's python3-setuptools is 68 and rejects both —
the `license` string parses as ambiguous against the auto-detected
LICENSE, and the `setuptools>=77` floor fails dpkg-checkbuilddeps.
Per APT.md we don't patch debian-rebuild rows, so the row flips to
pypi-sdist and the same metadata softening lives as a quilt patch
here instead.

## What is not built

`override_dh_auto_test` skips the upstream test suite. anyio's tests
need `pytest-asyncio`, `trio`, `uvloop`, and a network-fixture suite
at floors not all in Noble. Correctness for this rebuild comes from
upstream CI plus the Avalan smoke import.
