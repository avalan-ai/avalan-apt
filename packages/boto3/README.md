# boto3 (Avalan PPA transitive)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `boto3 1.40.61`). Required transitively by `aioboto3`
via aiobotocore's `[boto3]` extra (Avalan's `vendors` extra).
Noble ships `python3-boto3 1.34.46+dfsg-1ubuntu1`, below
aiobotocore 2.25.1's `>= 1.40.46, < 1.40.62` window for botocore
and boto3.

## Why not a debian-rebuild

Same iceberg as `botocore`: the Debian snapshot pool's nearest
versions either fall below the floor or above the ceiling of the
aiobotocore window. Hand-package from PyPI at the matching
`1.40.61` instead.

## Build backend notes

Upstream ships `setup.py` and a near-empty `pyproject.toml`
(pytest/ruff config only, no `[build-system]` block). pybuild
defaults to setuptools' legacy build path, which Noble's
python3-setuptools 68 handles without modification. No quilt
patches are needed.

## What is not built

`override_dh_auto_test` skips the upstream test suite at build
time. The suite touches live AWS endpoints and pulls dev-only
pytest plugins not in Noble's archive. Runtime correctness is
covered by the Avalan smoke import.
