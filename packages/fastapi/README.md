# fastapi (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `fastapi 0.136.1`). Debian sid ships 0.135.3 (below
Avalan's `>= 0.136.1` floor), so the rebuild lands the pinned
sdist.

## Build backend notes

pdm-backend, served by Noble's `python3-pdm-backend`. Pure Python.

Runtime deps come from a split of Noble + the Avalan PPA:

* Noble's archive: `python3-typing-extensions`.
* Avalan PPA: `python3-starlette` (`>= 0.46`), `python3-pydantic`
  (`>= 2.9`), `python3-typing-inspection` (`>= 0.4.2`),
  `python3-annotated-doc` (`>= 0.0.2`). All four landed in earlier
  Phase 3 slices.

## Quilt patch: pyproject-for-noble

Rewrites the PEP 639 `license = "MIT"` + `license-files = [...]`
pair to the legacy `license = { file = "LICENSE" }` table form and
drops the `Programming Language :: Python :: 3.14` trove classifier
-- same Noble-pdm-backend / setuptools workaround used by the rest
of the per-dep tree. Wheel metadata is equivalent; no runtime
impact.

## What is not built

`override_dh_auto_test` skips the upstream test suite. It needs a
running starlette test server plus `pytest-asyncio` and several
fastapi-specific fixtures at floors that do not match Noble's
archive. Correctness for the rebuild is covered by upstream CI plus
Avalan's autopkgtest smoke import.
