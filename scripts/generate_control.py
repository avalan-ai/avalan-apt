"""Generate Avalan's debian/control Depends block from the dep map.

Reads ``debian/dependency-map.toml`` and emits the per-dependency
``Depends:`` rows in alphabetic order, one per line, formatted to
land in ``debian/control`` between the
``# BEGIN generated-depends`` / ``# END generated-depends`` sentinel
comments. Lower-bound only (``(>= <min_version>)``); upper bounds
are pinned at the PPA-version level rather than declared inline, so
re-pinning to a newer release does not require a control rewrite.

Two modes:

* default: print the lines to stdout. Useful for ``diff`` against
  the in-tree control file to confirm no drift.
* ``--update``: rewrite ``debian/control`` in place, replacing only
  the content between the sentinels. Idempotent.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


BEGIN_MARKER = "# BEGIN generated-depends"
END_MARKER = "# END generated-depends"


@dataclass(frozen=True)
class DepLine:
    debian_name: str
    min_version: str

    def format(self) -> str:
        return f" {self.debian_name} (>= {self.min_version}),"


def parse_map(text: str) -> list[DepLine]:
    data = tomllib.loads(text)
    deps = data.get("dep", ())
    # Skip transitive rows -- they get pulled into the install set
    # via their parent's wheel `Requires-Dist` through
    # ${python3:Depends}, so emitting them again would just clutter
    # debian/control.
    rows = [
        DepLine(
            debian_name=entry["debian_name"],
            min_version=entry["min_version"],
        )
        for entry in deps
        if not entry.get("transitive_of")
    ]
    rows.sort(key=lambda r: r.debian_name)
    return rows


def render(rows: Sequence[DepLine]) -> str:
    return "\n".join(r.format() for r in rows)


def replace_block(
    control_text: str,
    new_block: str,
    *,
    begin: str = BEGIN_MARKER,
    end: str = END_MARKER,
) -> str:
    """Replace the content between ``begin`` and ``end`` in
    ``control_text``. Both markers must already be present; the new
    block does not include the markers themselves.
    """
    try:
        begin_idx = control_text.index(begin)
        end_idx = control_text.index(end, begin_idx)
    except ValueError as exc:
        raise ValueError(
            f"control file missing {begin!r}/{end!r} sentinels; "
            f"add them around the auto-generated Depends rows first"
        ) from exc
    head = control_text[: begin_idx + len(begin)]
    tail = control_text[end_idx:]
    body = new_block.rstrip("\n")
    if body:
        return f"{head}\n{body}\n{tail}"
    return f"{head}\n{tail}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--map",
        default="debian/dependency-map.toml",
        help="path to the dependency map (default: debian/...)",
    )
    parser.add_argument(
        "--control",
        default="debian/control",
        help="path to debian/control (default: debian/control)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help=(
            "rewrite the control file in place between the sentinel "
            "comments. Without this, prints to stdout."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    script_repo_root = Path(__file__).resolve().parent.parent
    map_path = Path(args.map)
    if map_path.is_absolute():
        repo_root = map_path.parent.parent
    else:
        repo_root = script_repo_root
        map_path = repo_root / map_path
    control_path = Path(args.control)
    if not control_path.is_absolute():
        control_path = repo_root / control_path

    rows = parse_map(map_path.read_text())
    block = render(rows)

    if args.update:
        text = control_path.read_text()
        new_text = replace_block(text, block)
        if new_text != text:
            control_path.write_text(new_text)
            print(f"updated {control_path}", file=sys.stderr)
        else:
            print(f"{control_path}: no change", file=sys.stderr)
    else:
        print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
