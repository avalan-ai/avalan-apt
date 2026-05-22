"""Build, sign, and upload every ppa-sourced dep to the staging PPA.

Runs the whole loop inside an avalan-apt-builder container. The host
side reads the Avalan Packaging key passphrase via getpass, exports
the secret subkeys via the host's gpg-agent (which has pinentry-mac
attached), and hands both to the container over stdin. Inside the
container the subkeys land in a private GPG keyring whose agent is
preconfigured with allow-preset-passphrase, so debsign signs without
re-prompting. Container memory holds the passphrase for the duration
of the run; the container is destroyed afterward, so nothing
persists.

The container side is ``scripts/upload_deps_container.sh``.

Usage::

    scripts/upload-deps              # walk every ppa-sourced dep
    scripts/upload-deps --list       # show the list, do not upload
    scripts/upload-deps --only mcp   # subset
    scripts/upload-deps --dry-run    # build + debsign, no dput
"""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import tomllib
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
DEFAULT_KEY = "49473F5F32A0BF8EEE5674F9DBF58F55A0D02605"
DEFAULT_PPA = "ppa:avalan-ai/avalan-staging"
DEFAULT_IMAGE = "avalan-apt-builder:noble"


def load_ppa_deps(map_path: Path) -> list[dict]:
    with map_path.open("rb") as fh:
        data = tomllib.load(fh)
    return [d for d in data.get("dep", []) if d.get("source") == "ppa"]


def export_subkeys(key_id: str, passphrase: str | None = None) -> bytes:
    print(
        f"Exporting secret subkeys for {key_id} via host gpg-agent ...",
        file=sys.stderr,
    )
    cmd = ["gpg", "--armor"]
    stdin_input: bytes | None = None
    if passphrase is not None:
        # Loopback feeds the passphrase via stdin so pinentry-mac is
        # not involved. The host already gave us the passphrase (via
        # --passphrase-file); reusing it here avoids a second prompt
        # that the user might accidentally dismiss.
        cmd += [
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase-fd",
            "0",
        ]
        stdin_input = passphrase.encode() + b"\n"
    cmd += ["--export-secret-subkeys", key_id]
    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        input=stdin_input,
    )
    if not result.stdout.strip():
        raise SystemExit(
            f"FATAL: no secret subkeys exported for {key_id}. "
            "Is the key imported on this host?"
        )
    return result.stdout


def build_image(image: str, recipes_dir: Path) -> None:
    # Check first; if the image already exists locally, skip the
    # rebuild. Docker Desktop on Apple Silicon hangs trying to refresh
    # the linux/amd64 ubuntu:24.04 manifest from Docker Hub when the
    # host is arm64 -- skipping the build avoids that path entirely
    # and is correct when nothing about the Dockerfile changed.
    have = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    )
    if have.returncode == 0:
        print(
            f"Builder image {image} already present; skipping rebuild.",
            file=sys.stderr,
        )
        return
    print(f"Building builder image {image} ...", file=sys.stderr)
    subprocess.run(
        [
            "docker",
            "build",
            # Pin to amd64 because the builder image targets Noble
            # archives that publish amd64 binaries; on Apple Silicon
            # this also avoids a Docker Hub manifest-refresh hang
            # against the cached ubuntu:24.04 amd64 image.
            "--platform=linux/amd64",
            "--pull=false",
            "--tag",
            image,
            "--file",
            str(recipes_dir / "Dockerfile.builder"),
            str(recipes_dir),
        ],
        check=True,
    )


def run_in_container(
    image: str,
    payload: bytes,
    deps: list[dict],
    key_id: str,
    ppa: str,
    *,
    dry_run: bool,
    debug: bool,
) -> int:
    cmd = [
        "docker",
        "run",
        "--rm",
        "--interactive",
        "--platform=linux/amd64",
        "--volume",
        f"{REPO}:/work",
        "--workdir",
        "/work",
        "--env",
        f"AVALAN_GPG_KEY_ID={key_id}",
        "--env",
        f"AVALAN_PPA={ppa}",
        "--env",
        "DEP_NAMES=" + " ".join(d["pypi_name"] for d in deps),
        "--env",
        "DRY_RUN=" + ("1" if dry_run else ""),
        "--env",
        "DEBUG=" + ("1" if debug else ""),
        image,
        "scripts/upload_deps_container.sh",
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    proc.communicate(input=payload)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", default=DEFAULT_KEY)
    parser.add_argument("--ppa", default=DEFAULT_PPA)
    parser.add_argument(
        "--map",
        default="debian/dependency-map.toml",
        help="path to the dependency map (default: debian/...)",
    )
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument(
        "--only",
        action="append",
        help="only upload these pypi_name(s); repeatable",
    )
    parser.add_argument(
        "--skip",
        action="append",
        help="skip these pypi_name(s); repeatable",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the matched deps and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build + debsign but do not invoke dput",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="set -x inside the container",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the host-side confirmation prompt",
    )
    parser.add_argument(
        "--passphrase-file",
        help=(
            "read the Avalan Packaging passphrase from this file "
            "instead of prompting via getpass. The file is treated "
            "as the entire passphrase (with a single trailing "
            "newline stripped if present). The caller is responsible "
            "for shredding the file afterward."
        ),
    )
    args = parser.parse_args(argv)

    deps = load_ppa_deps(REPO / args.map)
    if args.only:
        keep = set(args.only)
        deps = [d for d in deps if d["pypi_name"] in keep]
    if args.skip:
        drop = set(args.skip)
        deps = [d for d in deps if d["pypi_name"] not in drop]

    if args.list:
        for d in deps:
            print(
                f"  {d['pypi_name']:25s}  {d.get('provenance', '?'):16s}  "
                f"{d.get('constraint', '')}"
            )
        return 0

    if not deps:
        print("FATAL: no deps matched.", file=sys.stderr)
        return 1

    print(f"Will upload {len(deps)} sources to {args.ppa}:")
    for d in deps:
        print(
            f"  {d['pypi_name']:25s}  {d.get('provenance', '?'):16s}  "
            f"{d.get('constraint', '')}"
        )
    print()
    print(
        "Launchpad uploads are NOT undoable -- a bad version eats that "
        "version slot in the PPA forever."
    )

    if not args.yes:
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            return 1

    if args.passphrase_file:
        passphrase = Path(args.passphrase_file).read_text()
        if passphrase.endswith("\n"):
            passphrase = passphrase[:-1]
    else:
        passphrase = getpass.getpass("Avalan Packaging key passphrase: ")
    if not passphrase:
        print("FATAL: empty passphrase.", file=sys.stderr)
        return 1

    subkeys = export_subkeys(args.key, passphrase=passphrase)
    payload = passphrase.encode() + b"\n" + subkeys

    build_image(args.image, REPO / "recipes")

    return run_in_container(
        args.image,
        payload,
        deps,
        args.key,
        args.ppa,
        dry_run=args.dry_run,
        debug=args.debug,
    )


if __name__ == "__main__":
    raise SystemExit(main())
