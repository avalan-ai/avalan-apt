# uvicorn (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `uvicorn 0.35.0`). Noble ships an older 0.27.x and Debian
sid carries 0.38.x — both outside Avalan's `>= 0.35, < 0.36` window —
so the rebuild pins the 0.35.0 sdist.

## Build backend notes

uvicorn uses `hatchling.build` with `[tool.hatch.version] path =
"uvicorn/__init__.py"`. The version literal lives next to the code
(`__version__ = "0.35.0"`), so hatchling reads it directly from the
sdist — no `hatch-vcs`, no `SETUPTOOLS_SCM_PRETEND_VERSION` override
needed.

Runtime deps (`click >= 7.0`, `h11 >= 0.8`) are already in Noble at
satisfying versions and pulled in via `${python3:Depends}` — no
explicit duplication in `debian/control`. The `typing_extensions`
fallback is gated on `python_version < '3.11'`, so on Noble's default
3.12 it isn't required.

## What is not built

- The optional `[standard]` extra (`httptools`, `uvloop`,
  `watchfiles`, `websockets`, `PyYAML`, `python-dotenv`, plus
  `colorama` on Windows) is intentionally **not** declared as a
  Depends. Avalan's server stack runs fine on the lightweight install
  profile; callers that want the performance extras can
  `apt-get install python3-httptools python3-uvloop ...` alongside.
- `override_dh_auto_test` skips the upstream test suite — it requires
  every `[standard]` extra at uvicorn-specific floors plus
  `pytest-xdist` for the parallel runner. Correctness for the rebuild
  is covered by upstream CI plus the autopkgtest smoke import.
