# annotated-doc (Avalan PPA transitive dep)

Hand-packaged for the Avalan PPA because `fastapi` (Avalan's
`server` extra) requires `annotated-doc >= 0.0.2`. Not in Debian.
Pinned at 0.0.4. The dep-map row carries `transitive_of = "fastapi"`.

Zero runtime deps; the install is just the Python module.

## Build backend notes

pdm-backend (`python3-pdm-backend` in Noble). The quilt patch
rewrites the PEP 639 license pair to the legacy `license = { file =
"LICENSE" }` table form, same as the rest of the per-dep tree.
