# aiomysql (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `aiomysql 0.2.0`). Noble ships 0.1.1 (below floor) and
Debian sid ships 0.3.2 (above ceiling), so the rebuild lands at 0.2.0
to satisfy Avalan's `>= 0.2, < 0.3` window.

## Build backend notes

aiomysql uses `setuptools.build_meta` driven by `setup.cfg` plus a
small `[tool.setuptools_scm]` block in `pyproject.toml`. Runtime
dependency is just `PyMySQL >= 1.0`, which ships in Noble — it lands
in the Depends via `${python3:Depends}`.

`debian/rules` sets
`SETUPTOOLS_SCM_PRETEND_VERSION_FOR_AIOMYSQL=0.2.0` defensively;
setuptools-scm falls back to PKG-INFO when building from an sdist,
but pinning the version cuts off the failure mode where a stray
`.git` checkout on the build host shadows that fallback.

## Quilt patch: relax-build-system-requires

Upstream's `[build-system].requires` reads:

```
"setuptools_scm[toml] >= 6.4, < 7",
"setuptools_scm_git_archive >= 1.1",
```

Both lines predate setuptools-scm 7+, which **(a)** integrates the
git-archive support into the main package (`setuptools_scm_git_archive`
is no longer separately packaged in Noble) and **(b)** publishes
incompatible 8.x releases that the `< 7` upper bound rejects. With
`PIP_NO_BUILD_ISOLATION=1` the build pipeline still verifies the
constraint declarations before running the backend, so the patch
loosens the upper bound and removes the obsolete plugin row.

This is the first patch in the per-dep packaging tree, so it doubles
as the template for future debian-rebuild-style fixes that have to
land on a pypi-sdist row: drop one DEP-3 file under
`debian/patches/`, add it to `debian/patches/series`, mention it in
the changelog. Build-Depends adds `quilt` so `dpkg-buildpackage`'s
patch-application step has the tooling it needs even outside `sbuild`.

## What is not built

`override_dh_auto_test` skips the upstream test suite — it needs a
running MySQL/MariaDB instance plus `pytest-asyncio` at floors that
float across point releases. The optional `[sa]` extra
(`sqlalchemy < 1.4`) is also not declared as a Depends; Avalan
already pulls in PPA `python3-sqlalchemy` 2.x and the two are not
compatible. Correctness for the rebuild is covered by upstream CI
plus the autopkgtest smoke import.
