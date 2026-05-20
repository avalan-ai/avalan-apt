# aiobotocore (Avalan PPA transitive)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `aiobotocore 2.25.1`). `aioboto3 15.5.0` (Avalan's
`vendors` extra) hard-pins this exact version via
`aiobotocore[boto3]==2.25.1`. Not in Debian.

## Build backend notes

Upstream uses `setuptools.build_meta` with `setuptools>=77.0.0`.
Noble ships `python3-setuptools 68.1.2-2ubuntu1.2`. A quilt patch
(`pyproject-for-noble`) softens the build-system pin to plain
`setuptools`, rewrites the PEP 639 SPDX
`license = "Apache-2.0"` string to the legacy
`license = { file = "LICENSE" }` table form, drops the
`Programming Language :: Python :: 3.14` trove classifier, and
softens the runtime `aiohttp >= 3.9.2` floor to `>= 3.9.1` so
Noble's `python3-aiohttp 3.9.1-1ubuntu0.1` resolves. The gap
between 3.9.1 and 3.9.2 is a single security backport on the
response-parsing path that aiobotocore does not exercise
differently across the two releases.

## What is not built

`override_dh_auto_test` skips the upstream test suite at build
time. The suite stands up a `moto` server, exercises live S3
mocks, and pulls dev-only pytest plugins not in Noble's archive.
Runtime correctness is covered by the Avalan smoke import.
