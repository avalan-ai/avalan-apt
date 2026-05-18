# starlette (Avalan PPA transitive dep)

Hand-packaged for the Avalan PPA because `fastapi` (Avalan's
`server` extra) requires `starlette >= 0.46.0` and Noble's archive
ships 0.36.x. Pinned at the current `1.0.0`. The dep-map row carries
`transitive_of = "fastapi"`.

## Build backend notes

hatchling. Pure Python. Runtime deps `anyio` and `typing_extensions`
both come from Noble's archive at versions that satisfy starlette's
floors.

## Quilt patch: pyproject-license-for-noble

Rewrites the PEP 639 `license = "BSD-3-Clause"` + `license-files =
["LICENSE.md"]` pair to the legacy `license = { file = "LICENSE.md" }`
table form -- the older hatchling that Noble ships rejects the
modern pair as ambiguous during `dh_auto_clean`. No runtime impact.
