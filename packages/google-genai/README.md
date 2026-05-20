# google-genai (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `google-genai 1.75.0`). Not in Debian at all; the upstream
sdist needs three Noble-specific tweaks before Noble's setuptools 68
can produce a wheel.

## Build backend notes

Plain setuptools.build_meta. The quilt patch trims the build-system
requires from `[setuptools, wheel, twine, packaging, pkginfo]` down
to `[setuptools, wheel]` (the other three are distribution-upload
helpers, not wheel builders) and rewrites the PEP 639 SPDX string
`license = "Apache-2.0"` to the legacy `license = { file = "LICENSE" }`
table form.

## What is not declared

The three optional extras upstream defines (`aiohttp`, `local-tokenizer`,
`pyopenssl`) are intentionally not declared as Depends. They live behind
try/except ImportError guards inside the SDK, and Avalan exercises only
the default httpx transport. Callers that opt into those code paths get
a clear ImportError telling them which package to install into a
user-controlled venv.

## Runtime-dependency floor softening

Three of upstream's nominal floors fall above Noble's archive (and one
above sid). The Avalan-side patch lowers each to the version that
resolves against Noble + the Avalan PPA without touching API surface
google-genai actually calls; the patch's DEP-3 header records the
specific module/symbol audit for each one.

- `google-auth[requests] >= 2.48.1` -> `>= 2.48.0` (PPA build from sid).
- `httpx >= 0.28.1` -> `>= 0.26` (Noble universe).
- `typing-extensions >= 4.14.0` -> `>= 4.10` (Noble main).

## PPA transitives

This package depends on two `debian-rebuild` rows that the PPA must
ship alongside it: `python3-google-auth` (sid `2.48.0-3` rebuilt for
Noble) and `python3-websockets` (sid `16.0-1` rebuilt for Noble — the
`websockets.asyncio.client` subpackage layout introduced in 13 is
what google-genai's `live.py` imports against). Both are tracked in
`dependency-map.toml`.
