# typing-inspection (Avalan PPA transitive dep)

Hand-packaged for the Avalan PPA because `fastapi` (Avalan's
`server` extra) and `pydantic` both list it as a runtime dep at
`>= 0.4.2`. Not in Debian at all. Pinned at 0.4.2. The dep-map row
carries `transitive_of = "fastapi"`.

## Build backend notes

hatchling. Pure Python. Single runtime dep `typing-extensions` comes
from Noble's archive.

## Quilt patch: pyproject-license-for-noble

Rewrites the PEP 639 `license = "MIT"` + `license-files =
['LICENSE']` pair to the legacy `license = { file = "LICENSE" }`
table form. Equivalent wheel metadata; same Noble-hatchling
workaround as the rest of the per-dep tree.
