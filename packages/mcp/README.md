# mcp (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `mcp 1.27.1`). Not in Debian at all; the upstream build
requires `uv-dynamic-versioning` (not in Noble) and a handful of
runtime extras (`pydantic-settings`, `sse-starlette`) that Noble's
archive does not carry.

## Build backend notes

Upstream uses hatchling + uv-dynamic-versioning. Noble ships
`python3-hatchling` 1.21 but not `uv-dynamic-versioning`, so the quilt
patch `pyproject-for-noble` replaces the dynamic version source with a
static `version = "1.27.1"`. The same string was already present in
the sdist's `PKG-INFO`, so the resulting wheel metadata is identical
to upstream's.

## What is not declared

Three upstream runtime deps are intentionally absent from the binary
package's `Depends:` (and stripped from the patched pyproject) because
Noble's archive does not carry them:

- `pydantic-settings`: only reached from `FastMCP` (mcp's HTTP-server
  ergonomic wrapper). Avalan implements MCP over its own FastAPI
  router and never touches FastMCP.
- `sse-starlette`: only reached from `mcp.server.sse` and
  `mcp.server.streamable_http`. Same story.
- `pyjwt[crypto]`: only reached from `mcp.server.auth.*`. The plain
  `python3-jwt` package is still in `Depends:`; Noble's 2.7.0 covers
  the API the lazy-loaded auth handlers would call.

Callers that opt into FastMCP / SSE / the OAuth handlers get a clean
ImportError on first use telling them which package is missing. The
`import mcp` path Avalan exercises does not touch any of them.

## Quilt patches

- `0001-pyproject-for-noble.patch` — static version, dropped uv
  blocks, dropped unavailable runtime deps, relaxed floors that fall
  above Noble's archive on stable API surface. See the DEP-3 header
  for the rationale on each line.
- `0002-lazy-fastmcp-import.patch` — replaces the eager
  `from .fastmcp import FastMCP` in `mcp/server/__init__.py` with a
  PEP 562 `__getattr__` shim so the heavy FastMCP transitive deps
  only load when something actually reaches for `mcp.server.FastMCP`.
  Without this, `import mcp` would fail on a Noble host because
  `pydantic_settings` is unavailable.
- `0003-defer-typevar-default-annotations.patch` — adds
  `from __future__ import annotations` to the three modules that
  subscribe `RequestContext` with only two of its three TypeVars
  (`client.session`, `client.experimental.task_handlers`,
  `shared.progress`) and spells out the third TypeVar explicitly at
  one runtime call site in `_received_request`. Noble's
  typing_extensions 4.10 carries the `default=` keyword on `TypeVar`
  but does not patch `Generic.__class_getitem__` to fill it in (that
  hook only landed in typing_extensions 4.12). PEP 563 string
  annotations sidestep the eager evaluation; the explicit third
  argument keeps the surviving runtime expression valid. Drop the
  patch once Noble ships typing_extensions >= 4.12.
