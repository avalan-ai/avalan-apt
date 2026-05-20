# sqlalchemy (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `SQLAlchemy 2.0.49`). Built because Avalan's `tool` extras
require `SQLAlchemy >= 2.0.43` and Noble ships `python3-sqlalchemy
1.4.50-1.1` — below the 2.x floor.

## Why pypi-sdist, not debian-rebuild

Debian sid carries `python-sqlalchemy 2.0.48+ds1-1`, but its source
`Build-Depends` on `python3-zzzeeksphinx (>= 1.6.1)` (sid's docs theme
for the SQLAlchemy / Mike Bayer doc family) and Noble carries
`python3-zzzeeksphinx 1.5.0-1` — below the floor sid asks for. The
Avalan project does not patch debian-rebuild sources, so the row flips
to pypi-sdist; the build skips the docs path entirely and only ships
the runtime wheel.

## Build backend notes

Plain setuptools with PEP 517 wiring (`pyproject.toml` declares
`setuptools >= 61` + `cython`). The optional Cython modules under
`sqlalchemy/cyextension/` build automatically when Cython is on the
path; upstream's `setup.py` marks every Extension `optional=True` so a
missing toolchain falls back silently to the pure-Python equivalents.
The Noble builder image carries `cython3` and `build-essential`, so
the extensions are built.

## What is not built

`override_dh_auto_test` skips the upstream test suite at build time.
The suite needs a pinned pytest stack and optional database drivers
(psycopg, asyncpg, aiomysql, ...) that we do not carry as build
dependencies. Runtime correctness is covered by the Avalan smoke
import.
