# sqlglot (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `sqlglot 27.29.0`). Debian sid carries sqlglot 30.x, which
is above the ceiling Avalan tracks (`>= 27.20, < 28`), so the rebuild
ships the latest 27.x release.

## Build backend notes

sqlglot uses `setuptools.build_meta` (PEP 621 `[project]` plus
`[build-system]` `requires = ["setuptools >= 61.0", "setuptools_scm"]`).
`debian/rules` sets `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_SQLGLOT=27.29.0`
defensively — `setuptools_scm` does fall back to PKG-INFO when building
from an sdist, but pinning the version avoids a stray `.git` checkout
on the build host accidentally redirecting it to a different number.

The sdist ships a `setup.py` that exists only to declare the `[dev]`
and `[rs]` extras dynamically (the `[rs]` line reads
`sqlglotrs/Cargo.toml` for its version). `setuptools.build_meta` loads
`setup.py` during the build, so the file must keep its expected layout
— do not strip it out as cruft.

## What is not built

- The optional Rust acceleration package `sqlglotrs` lives in a
  sibling subdirectory of the sdist with its own `pyproject.toml` and
  `Cargo.toml`. It builds via maturin and would need its own Debian
  source package; this rebuild ships pure-Python sqlglot only. sqlglot
  imports `sqlglotrs` opportunistically and falls back to its in-process
  tokenizer when the extension is missing, so the omission is
  transparent to callers.
- `override_dh_auto_test` skips the upstream test suite. Tests pull
  duckdb and pandas at versions not pinned in Noble at matching floors,
  and parts of the suite require reference SQL files fetched at runtime.
  Correctness for the rebuild is covered by upstream CI plus Avalan's
  autopkgtest smoke import.
