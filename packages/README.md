# Per-dependency Debian packaging

Each subdirectory here owns the Debian packaging for one of Avalan's
runtime dependencies that ships from the Avalan PPA instead of from
Ubuntu Noble's archive. The companion source of truth is
[`../debian/dependency-map.toml`](../debian/dependency-map.toml), which
records every dep's upstream constraint, provenance, and pin.

## Layout

```
packages/
  <debian-source-name>/
    debian/
      control
      changelog
      copyright
      rules
      source/format
      watch
      ...
    README.md           # what this package is, why it's hand-packaged
```

`<debian-source-name>` follows Debian conventions (lowercase, dashes
preserved). For most rows it is the PyPI distribution name lowercased
(`humanize`, `sqlalchemy`, `restrictedpython`); for the handful with
explicit Debian binary remaps recorded in `debian/py3dist-overrides`
(notably `pillow` → `python3-pil`), the source name still follows
upstream Debian's `python-<name>` / `<name>` convention.

## When to add a subdirectory here

Only `provenance = "pypi-sdist"` rows in `dependency-map.toml` need a
subdirectory under `packages/`. Those are deps that don't have a
suitable Debian source package and have to be hand-packaged from the
upstream sdist.

`provenance = "debian-rebuild"` rows source their `debian/` tree from
the Debian archive at build time (`apt-get source <debian_source_pkg>
-t <debian_suite>`); they do not live here.

## Building one of these

Per-dep builds use the same shape as Avalan's own packaging:

1. `scripts/prepare-dep-source <pypi-name>` fetches and verifies the
   upstream sdist for the named dep, unpacks it under
   `build/deps/<source>-<version>/`, and overlays the matching
   `packages/<source>/debian/` tree onto it.
2. From the unpacked tree, run the same `dpkg-buildpackage` /
   `sbuild` flow as the top-level Avalan package. Source-only and
   binary builds both work; the rules file enforces no-network just
   like Avalan's.
3. `lintian --pedantic` against the resulting `.changes`; install in
   a Noble chroot; spot-check the Python import.

Each subdirectory's `README.md` records anything dep-specific that
doesn't follow from the above (e.g. a build backend's quirks, a test
suite skipped at build time, a license-file rename).

## Patching an upstream sdist

When upstream's sdist needs a small adjustment to build against Noble
(over-constrained build-system requires, a removed-in-Noble build
plugin, a hard-coded path that breaks under pybuild), use the standard
quilt layout:

```
packages/<source>/debian/
  patches/
    series                            # one patch filename per line
    NNNN-short-description.patch      # DEP-3 headers + unified diff
```

Patches must carry DEP-3 metadata (`Description:`, `Author:`,
`Forwarded:`, `Last-Update:`) so a future maintainer can tell at a
glance whether the patch is permanent or candidate-for-upstream. Add
`quilt` to `Build-Depends`. Mention each patch by name in the
changelog so the audit trail doesn't live only inside `debian/patches/`.

`packages/aiomysql/` is the worked example.
