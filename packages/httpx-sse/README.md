# httpx-sse (Avalan PPA transitive)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `httpx-sse 0.4.3`). Built because `mcp` (Avalan's `server`
extras) requires `httpx-sse >= 0.4` and neither Debian nor Noble carry
the distribution.

## Build backend notes

setuptools + setuptools-scm + wheel, driven by `pyproject.toml`'s
`setuptools.build_meta` backend. The `setuptools-scm` build-requires
entry is vestigial — the actual version is resolved by
`[tool.setuptools.dynamic] version = { attr = "httpx_sse.__version__" }`,
which reads the constant baked into `src/httpx_sse/__init__.py`. No
`SETUPTOOLS_SCM_PRETEND_VERSION` override is needed.

The upstream license metadata already uses the legacy
`license = { text = "MIT" }` table form, so no Noble-specific quilt
patch is required.

## What is not built

`override_dh_auto_test` skips the upstream test suite. It depends on
`pytest-asyncio` plus a local SSE server fixture and targets 100%
branch coverage via `pytest-cov`; the version pins do not all match
Noble's archive. Correctness for this rebuild is covered by upstream
CI plus the smoke import in Avalan's autopkgtest.
