#!/bin/bash
# scripts/upload_deps_container.sh -- container side of upload-deps.
#
# Runs inside the avalan-apt-builder container that scripts/upload-deps
# spawns. Reads passphrase + ASCII-armored secret subkeys from stdin
# (line 1 = passphrase, rest = subkeys block), imports them into the
# container's GPG keyring, caches the signing-subkey passphrase via
# gpg-preset-passphrase, then iterates the deps named in DEP_NAMES:
# prepare-dep-source + build-dep-package --mode source + debsign +
# dput.
#
# Required env (set by upload-deps host runner):
#   AVALAN_GPG_KEY_ID   -- 40-char primary fingerprint
#   AVALAN_PPA          -- dput target (e.g. ppa:avalan-ai/avalan-staging)
#   DEP_NAMES           -- space-separated PyPI names to upload
#
# Optional env:
#   DRY_RUN             -- if non-empty, skip the dput step
#   DEBUG               -- if non-empty, set -x

set -euo pipefail

if [ -z "${AVALAN_GPG_KEY_ID:-}" ]; then
    echo "FATAL: AVALAN_GPG_KEY_ID is unset." >&2
    exit 2
fi
if [ -z "${AVALAN_PPA:-}" ]; then
    echo "FATAL: AVALAN_PPA is unset." >&2
    exit 2
fi
if [ -z "${DEP_NAMES:-}" ]; then
    echo "FATAL: DEP_NAMES is unset (no deps to upload)." >&2
    exit 2
fi

if [ -n "${DEBUG:-}" ]; then
    set -x
fi

# stdin protocol: line 1 = passphrase, remainder = ASCII-armored
# secret subkeys (-----BEGIN PGP PRIVATE KEY BLOCK-----).
IFS= read -r PASSPHRASE
SUBKEYS=$(cat)

if [ -z "$PASSPHRASE" ] || [ -z "$SUBKEYS" ]; then
    echo "FATAL: stdin missing passphrase or subkeys." >&2
    exit 2
fi

# Configure the container's gpg-agent up front so the import + sign
# operations route through a single agent that accepts preset
# passphrases.
mkdir -p ~/.gnupg
chmod 700 ~/.gnupg
cat > ~/.gnupg/gpg-agent.conf <<EOF
allow-preset-passphrase
default-cache-ttl 14400
max-cache-ttl 86400
EOF
gpg-connect-agent reloadagent /bye >/dev/null

# Import the subkeys. --pinentry-mode loopback + --passphrase keeps
# everything in the foreground process; no pinentry dialog spawn
# attempts (which would fail in the headless container anyway).
printf '%s' "$SUBKEYS" \
    | gpg --batch --pinentry-mode loopback \
          --passphrase "$PASSPHRASE" --import

# Verify the import landed.
if ! gpg --list-secret-keys "$AVALAN_GPG_KEY_ID" >/dev/null 2>&1; then
    echo "FATAL: subkey import did not produce a secret key for $AVALAN_GPG_KEY_ID." >&2
    exit 2
fi

# Find the signing subkey's keygrip. The signing operation uses the
# subkey with [S] capability; debsign passes the primary fingerprint
# to gpg via -k, gpg picks the appropriate subkey itself. To preset
# the passphrase we need the *subkey's* keygrip from --with-keygrip.
KEYGRIP=$(gpg --list-secret-keys --with-keygrip --with-colons "$AVALAN_GPG_KEY_ID" \
    | awk -F: '
        /^ssb:/ { seen_ssb = 1; next }
        /^grp:/ {
            if (seen_ssb) { print $10; exit }
        }
    ')

if [ -z "$KEYGRIP" ]; then
    echo "FATAL: could not derive keygrip for the signing subkey of $AVALAN_GPG_KEY_ID." >&2
    exit 2
fi

# Preset the passphrase into the agent for the signing subkey so
# debsign signs silently.
/usr/lib/gnupg/gpg-preset-passphrase --preset --passphrase "$PASSPHRASE" "$KEYGRIP"

# debsign defaults to looking up the key by the Maintainer email in
# the .changes. -k pins the fingerprint explicitly; debsign also
# needs to know which gpg to invoke -- the default is fine inside
# the container.

mkdir -p build/deps

failed=()
uploaded=()

for dep in $DEP_NAMES; do
    echo
    echo "==== $dep ===="

    # Use the mtime of build/deps as a reference point so we can
    # identify the freshly produced _source.changes for this dep
    # even if older files from previous deps linger in the directory.
    touch -d "now" build/deps/.dep-marker
    marker=build/deps/.dep-marker

    if ! scripts/prepare-dep-source "$dep"; then
        echo "FAIL prepare-dep-source: $dep" >&2
        failed+=("$dep")
        continue
    fi

    # debian-rebuild rows pull sid build-deps that the builder image
    # does not always carry; --allow-unmet-build-deps tells
    # dpkg-buildpackage to skip the local Build-Depends check
    # (Launchpad will install build-deps from its own profile on the
    # buildds, so an unsigned .dsc with sid's Build-Depends works
    # there even if it doesn't build locally).
    build_args=("$dep" --mode source --allow-unmet-build-deps)
    if [ -n "${BUMP_REVISION:-}" ]; then
        build_args+=(--bump-revision "$BUMP_REVISION")
    fi
    if ! scripts/build-dep-package "${build_args[@]}"; then
        echo "FAIL build-dep-package: $dep" >&2
        failed+=("$dep")
        continue
    fi

    # Pick the source.changes produced by this iteration. The most
    # robust way to identify "the one we just built" is via mtime
    # against the marker we touched before the build.
    changes=$(find build/deps -maxdepth 1 -name '*_source.changes' \
                  -newer "$marker" -print 2>/dev/null | head -n1 || true)
    if [ -z "$changes" ] || [ ! -f "$changes" ]; then
        echo "FAIL no _source.changes produced for $dep" >&2
        failed+=("$dep")
        continue
    fi

    echo "Signing $changes"
    if ! debsign -k"$AVALAN_GPG_KEY_ID" "$changes"; then
        echo "FAIL debsign $changes" >&2
        failed+=("$dep")
        continue
    fi

    if [ -n "${DRY_RUN:-}" ]; then
        echo "DRY_RUN: skipping dput for $changes"
        uploaded+=("$dep (dry-run)")
        continue
    fi

    echo "Uploading $changes -> $AVALAN_PPA"
    # -f tells dput to ignore the .ppa.upload cache file and actually
    # transfer the .changes. Without it, a retry after a Launchpad-side
    # rejection silently no-ops because dput sees the prior upload's
    # cache file and assumes the work is done.
    if ! dput -f "$AVALAN_PPA" "$changes"; then
        echo "FAIL dput $changes" >&2
        failed+=("$dep")
        continue
    fi
    uploaded+=("$dep")
done

rm -f build/deps/.dep-marker

echo
echo "==== summary ===="
echo "uploaded: ${#uploaded[@]}"
for dep in "${uploaded[@]}"; do echo "  $dep"; done
echo "failed:   ${#failed[@]}"
for dep in "${failed[@]}"; do echo "  $dep"; done

if [ ${#failed[@]} -ne 0 ]; then
    exit 1
fi
