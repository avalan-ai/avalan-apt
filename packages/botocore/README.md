# botocore (Avalan PPA transitive)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `botocore 1.40.61`). Required transitively by
`aiobotocore` and `boto3` (Avalan's `vendors` extra, reached via
`aioboto3`). Noble ships `python3-botocore 1.34.46+repack-1ubuntu1`,
below the floor aiobotocore 2.25.1 needs (`>=1.40.46,<1.40.62`).

## Why not a debian-rebuild

`aiobotocore 2.25.1` ceilings botocore at `1.40.62`. The Debian
snapshot pool jumps from `1.37.9+repack-1` straight to
`1.40.68+repack-1` — there is no version inside the aiobotocore
window to rebuild. Hand-package from PyPI at `1.40.61` (the top of
the window) instead.

## Build backend notes

Upstream ships `setup.py` and a near-empty `pyproject.toml`
(pytest/ruff config only, no `[build-system]` block). pybuild
defaults to setuptools' legacy build path, which Noble's
python3-setuptools 68 handles without modification. No quilt
patches are needed.

## What is not built

`override_dh_auto_test` skips the upstream test suite at build
time. The suite needs dev-only pytest plugins not in Noble's
archive at matching pins and runs a large model-validation matrix
against AWS service JSONs. Runtime correctness is covered by the
Avalan smoke import.
