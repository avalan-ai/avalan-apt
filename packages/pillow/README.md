# pillow (Avalan PPA pin)

Hand-packaged from the upstream PyPI sdist pinned in
[`../../debian/dependency-map.toml`](../../debian/dependency-map.toml)
(currently `pillow 11.3.0`). Noble ships python3-pil 10.2.0 (below
Avalan's floor) and Debian sid ships 12.2.0 (above the ceiling), so
the rebuild pins the 11.3.0 sdist. Avalan tracks `>= 11.3, < 12`.

## First arch-dependent dep

Every prior `packages/<name>/` was `Architecture: all`. Pillow is the
first arch-dependent rebuild in the tree: it ships compiled C
extensions (`_imaging.so`, `_imagingft.so`, `_webp.so`,
`_imagingcms.so`, `_imagingmath.so`, `_imagingmorph.so`, plus the
optional `_avif.so` when libavif is available). Launchpad will build
once per supported arch (`amd64`, `arm64`); both must complete before
the binaries land in the PPA.

## Build backend notes

Pillow ships its own PEP 517 backend at `_custom_build/backend.py` —
a thin subclass of `setuptools.build_meta` that forwards
`--pillow-configuration` flags to `setup.py` when the build invocation
passes them via `config_settings`. The default invocation passes no
flags and the subclass is transparent; `pybuild-plugin-pyproject`
follows the `[build-system].backend-path` declaration and finds it.

Build-Depends carries the standard codec/library development headers
that `setup.py` looks for at compile time:

- `zlib1g-dev`        — PNG, GIF, TIFF compression
- `libjpeg-dev`       — JPEG codec
- `libtiff-dev`       — TIFF codec (built on top of jpeg + zlib)
- `libwebp-dev`       — WebP codec
- `libfreetype-dev`   — TrueType / OpenType font rendering
- `liblcms2-dev`      — colour management
- `libopenjp2-7-dev`  — JPEG 2000 codec

Optional development headers Pillow can also link against
(`libimagequant-dev`, `libraqm-dev`, `libavif-dev`,
`libxcb1-dev` for `ImageGrab` screen capture, `tk-dev` for
`ImageTk`) are **not** in Build-Depends for this rebuild. Add the
ones a downstream feature actually needs; don't pull them all in
speculatively. The resulting binary `python3-pil` will simply not
support those file formats until the headers are present at build
time.

## What is not built

- `override_dh_auto_test` skips the upstream test suite. The
  `Tests/` tree depends on optional codecs at versions we
  deliberately don't ship and on ~50 MB of image fixtures fetched
  from the python-pillow image repository at runtime (see
  `depends/install_extra_test_images.sh`). Correctness for the
  rebuild is covered by upstream CI plus Avalan's autopkgtest
  smoke import.
- The `python3-pil.imagetk` binary (Tk display widget support) is
  not split out from `python3-pil`. Noble's archive ships them as
  separate binaries; this rebuild keeps everything under
  `python3-pil` to avoid an additional split-package gymnastics
  round on the PPA. Re-split if a Avalan feature needs `ImageTk`.
