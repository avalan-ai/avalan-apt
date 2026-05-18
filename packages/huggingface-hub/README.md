# huggingface-hub (Avalan PPA transitive dep)

Hand-packaged for the Avalan PPA because `diffusers` (Avalan's
`vendors` extra) requires `huggingface-hub >= 0.34.0, < 2.0` and
Noble's archive only carries 0.20.3. Pinned at 0.34.0 -- the minimum
that satisfies diffusers and the last release line before
huggingface-hub started leaning on a larger Rust dependency surface
in its 1.x series.

## Transitive row, not a direct Avalan dep

The dep-map row carries `transitive_of = "diffusers"`. The
parity check in `scripts/check-dependencies` skips the
"must-be-in-pyproject" gate for transitive rows, and
`scripts/generate-control` skips them when rendering Avalan's
`Depends` (the install comes through `${python3:Depends}` from
diffusers' wheel metadata at install time).

## Build backend notes

setuptools-only -- upstream ships a `setup.py` and an empty
`setup.cfg` (the pyproject.toml in the sdist only carries linter
config). pybuild's `--system=pyproject` plugin falls through to
`setuptools.build_meta` for `[build-system]`-less projects, which is
fine.

## Quilt patch: drop-hf-xet-requirement

Upstream's `setup.py` lists `hf-xet >= 1.1.3` as an install
requirement on x86_64 / amd64 / arm64 / aarch64. `hf-xet` is a
Rust-based accelerator for the Hugging Face Xet protocol and is not
in Noble. Every reference inside `huggingface_hub` to `hf_xet` is
guarded:

* `file_download.py:585` uses `try: from hf_xet import ... except
  ImportError: raise ValueError("install hf_xet to use Xet
  downloads")` and only inside the Xet code path.
* `_commit_api.py:533` imports `from hf_xet import upload_bytes,
  upload_files` only after an explicit `# at this point, we know
  that hf_xet is installed` precondition check earlier in the same
  function.
* `utils/_xet_progress_reporting.py` is imported lazily from inside
  the same protected `_commit_api.py` block.

Stripping the install requirement therefore breaks nothing for the
HTTP-only paths Avalan uses (`from_pretrained`, `snapshot_download`,
plain file gets). Callers that genuinely need Xet acceleration can
`pip install hf_xet` into a venv.

## What is not built

`override_dh_auto_test` skips the upstream test suite. The tests
need a live Hugging Face Hub backend plus `pytest-httpserver` /
`pytest-asyncio` at floors that don't match Noble's archive.
Correctness for the rebuild is covered by upstream CI plus Avalan's
autopkgtest smoke import.
