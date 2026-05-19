# anthropic (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `anthropic 0.71.1`). Debian sid carries 0.91.x (above
Avalan's `< 0.72` ceiling), so the rebuild pins the upstream sdist.

## Build backend notes

hatchling + hatch-fancy-pypi-readme. Noble has python3-hatchling at
1.21 and python3-hatch-fancy-pypi-readme at 24.1; both are well
within anthropic 0.71's needs once the strict `==1.26.3` build pin
is relaxed.

## What is not declared

The `jiter` Rust-based JSON accelerator is upstream's
install_requires, but it is not in Noble at all (Rust 2024 edition
sources, no Debian source package). Every reference inside
`anthropic` is a lazy `from jiter import from_json` inside the
streaming-tool-input delta handler:

* `anthropic/lib/streaming/_messages.py:441`
* `anthropic/lib/streaming/_beta_messages.py:446`

Neither is reached during plain message sends, async / sync
transport setup, or response streaming -- only when an upstream
event is `input_json_delta` and the tracked content type opts in
to incremental tool-input parsing. Dropping `jiter` from
install_requires therefore lets the PPA ship a pure-Python wheel
without breaking the paths Avalan exercises. Callers who actually
need streaming tool-input parsing get a clear ImportError on first
use, with a message pointing them at `pip install jiter`.

## Quilt patch: pyproject-for-noble

Three small tweaks bundled into one patch -- legacy table form for
the PEP 639 license string, relaxed hatchling build pin, dropped
jiter install_requires. See the patch's DEP-3 header for the
rationale on each line.
