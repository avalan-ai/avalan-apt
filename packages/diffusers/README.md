# diffusers (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `diffusers 0.37.1`). Not in Debian. Avalan ships diffusers
in its `vendors` extra at `>= 0.37.1, < 0.38`.

## Build backend notes

Upstream's `pyproject.toml` only carries linter (ruff) config; the
`[build-system]` block is absent, so the build falls back to a
classic setuptools `setup.py` invocation. `pybuild-plugin-pyproject`
handles that path transparently -- no extra rules-file glue, no
quilt patches.

## Runtime deps and the heavyweight stack

`diffusers` declares its core install_requires through a
`dependency_versions_table.py` keyed on the same nine names Avalan
needs at the apt layer: `importlib_metadata`, `filelock`, `httpx`,
`huggingface-hub`, `numpy`, `regex`, `requests`, `safetensors`,
`Pillow`. Every one of those resolves via `${python3:Depends}`:

* Noble's archive: `python3-importlib-metadata`,
  `python3-filelock`, `python3-httpx` (0.27), `python3-numpy`,
  `python3-regex`, `python3-requests`, `python3-safetensors`.
* Avalan PPA: `python3-huggingface-hub` (0.34.0 transitive-of-
  diffusers row) and `python3-pil` (11.3.0).

The heavyweight ML deps that diffusers's `dependency_versions_table`
references for its `[test]` / `[training]` / `[flax]` / `[torch]`
extras (`torch`, `accelerate`, `transformers`, `jax`, `jaxlib`,
`scipy`, `peft`, `bitsandbytes`, `compel`, `invisible-watermark`,
`note_seq`, `librosa`, etc.) are deliberately **not** declared as
runtime Depends. Per APT.md's heavyweight-extras carve-out, callers
who need them install via `pip install diffusers[torch]` etc. into a
user-controlled venv on top of the system install.

## What is not built

`override_dh_auto_test` short-circuits the upstream test suite.
Tests need torch + a CUDA or MPS device and several hundred MB of
model fixtures fetched at runtime. Correctness for the rebuild is
covered by upstream CI plus Avalan's autopkgtest smoke import.
