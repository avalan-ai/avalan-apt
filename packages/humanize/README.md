# humanize (Avalan PPA rebuild)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `humanize 4.12.3`). Noble's `python3-humanize` is 4.9.0 and
Debian sid's is 4.12.1, both below the `>= 4.12.3` floor Avalan
requires.

## Build backend notes

humanize uses `hatchling.build` with `hatch-vcs` for dynamic
versioning. The upstream sdist ships a pre-baked `PKG-INFO` and a
generated `src/humanize/_version.py`, so `hatch-vcs` falls back to the
version embedded in the sdist instead of trying to query git at build
time. No `SETUPTOOLS_SCM_PRETEND_VERSION` override is needed.

## What is not built

`override_dh_auto_test` skips the upstream test suite. It depends on
`freezegun` and `pytest-cov` at versions not currently in Noble's
archive at matching pins, and on an editable install layout that
`pybuild` does not produce. Correctness for this rebuild is covered by
upstream CI plus the smoke import in Avalan's autopkgtest.
