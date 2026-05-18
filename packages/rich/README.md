# rich (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `rich 14.3.4`). Debian sid carries rich 15.x, which is
above the ceiling Avalan tracks (`>= 14.1.0, < 15.0.0`), so the
rebuild ships the latest 14.x release at the time of pinning.

## Build backend notes

rich uses `poetry-core` as its PEP 517 backend, declared via legacy
`[tool.poetry]` rather than PEP 621 `[project]`. `pybuild-plugin-pyproject`
reads `[build-system]` directly, so the legacy table doesn't trip it
up; the only build dependency this adds over the humanize template is
`python3-poetry-core`.

Runtime deps (`pygments`, `markdown-it-py`) both ship in Noble at
versions that satisfy rich 14.3.4's lower bounds. `dh_python3` picks
them up from the produced wheel's `Requires-Dist`, so they appear in
`${python3:Depends}` without explicit duplication in `debian/control`.

## What is not built

`override_dh_auto_test` short-circuits the test step: the upstream
sdist does not ship the `tests/` directory, so there is nothing to
run at build time anyway. Correctness for the rebuild is covered by
upstream CI plus the smoke import in Avalan's autopkgtest.
