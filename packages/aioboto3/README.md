# aioboto3 (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `aioboto3 15.5.0`). Avalan ships it in its `vendors`
extra at `>= 15.0.0, < 16.0.0`. Not in Debian.

## Build backend notes

Upstream uses `setuptools.build_meta` with
`setuptools >= 68.2.0` + `setuptools-scm >= 8`. Noble ships
`python3-setuptools 68.1.2-2ubuntu1.2`, two patch releases below
the floor. A quilt patch (`pyproject-for-noble`) softens the
build-system pin to plain `setuptools` and drops the
`Programming Language :: Python :: 3.14` trove classifier.

`setuptools-scm` falls back to the version baked into the sdist's
`aioboto3/_version.py`. `debian/rules` also exports
`SETUPTOOLS_SCM_PRETEND_VERSION=15.5.0` so a stray VCS probe
inside the build container cannot override the pinned upstream
release.

## What is not built

`override_dh_auto_test` skips the upstream test suite at build
time. The suite stands up a `moto` server, exercises live S3
mocks, and pulls dev-only pytest plugins not in Noble's archive.
Runtime correctness is covered by the Avalan smoke import.
