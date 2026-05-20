# s3transfer (Avalan PPA transitive)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `s3transfer 0.14.0`). Required transitively by `boto3`
1.40.61 (Avalan's `vendors` extra, reached via `aioboto3`). Noble
ships `python3-s3transfer 0.10.1-1ubuntu2`, below boto3 1.40.61's
`>= 0.14.0` floor.

## Build backend notes

Upstream ships `setup.py` and a near-empty `pyproject.toml`
(pytest/ruff config only, no `[build-system]` block). pybuild
defaults to setuptools' legacy build path, which Noble's
python3-setuptools 68 handles without modification. No quilt
patches are needed.

## What is not built

`override_dh_auto_test` skips the upstream test suite at build
time. The suite touches live S3 endpoints and pulls dev-only
pytest plugins not in Noble's archive. Runtime correctness is
covered by the Avalan smoke import.
