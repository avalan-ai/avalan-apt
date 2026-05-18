# youtube-transcript-api (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `youtube-transcript-api 1.2.4`). Not in Debian at all, so
the rebuild has to live in the Avalan PPA; Avalan tracks
`>= 1.2.2, < 2.0`.

## Build backend notes

Uses `poetry-core` as its PEP 517 backend, declared via legacy
`[tool.poetry]` (no PEP 621 `[project]` table). `pybuild-plugin-pyproject`
reads `[build-system]` directly, so the legacy layout is fine; the
only build dep needed beyond the shared template is
`python3-poetry-core`.

Runtime deps are `requests` (unpinned upstream) and
`defusedxml ^0.7.1`. Both ship in Noble at versions that satisfy
`dh_python3`'s resolution from the wheel's `Requires-Dist`, so neither
is explicitly listed in `debian/control` — they arrive through
`${python3:Depends}`.

The PyPI distribution name is `youtube-transcript-api` (dashes) but
the importable package and the console-script binary are
`youtube_transcript_api` (underscores). `debian/py3dist-overrides`
already maps the dashed PyPI name onto the dashed Debian binary name
(`python3-youtube-transcript-api`); the underscored CLI binary lands
at `/usr/bin/youtube_transcript_api` unchanged because that is what
upstream's `[tool.poetry.scripts]` entry declares.

## What is not built

`override_dh_auto_test` skips the upstream test suite. Tests live
inside the `youtube_transcript_api/test/` tree and depend on
`httpretty < 1.1`, which is not in Noble at a matching floor.
Correctness for the rebuild is covered by upstream CI plus Avalan's
autopkgtest smoke import.
