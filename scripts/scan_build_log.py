"""Fail a build if the captured log contains forbidden network calls.

The Avalan packaging build is supposed to be hermetic: every runtime
and build-time dependency comes from Noble's archive or the Avalan PPA
via ``apt``, never from PyPI or another network source at build time.
This scanner reads a captured build log and exits non-zero if any
forbidden pattern -- ``pip install``, ``easy_install``, ``setup.py
install``, or a direct PyPI fetch -- appears.

Run from the repo root as ``scripts/scan-build-log`` (the POSIX shim)
or ``python3 scripts/scan_build_log.py``. The module is importable so
tests can drive ``main()`` directly against fixture logs.

The script reads from a file (positional argument) or stdin. Lines
matching one of the forbidden patterns are written to stderr with a
``log:lineno: text`` prefix so the offending invocation is easy to
locate. Pass ``--allow <pattern>`` to whitelist a literal substring;
useful when a documented dependency string surfaces in the log without
being executed (e.g. an ``ImportError`` message that quotes
``pip install jiter`` as user-facing advice).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


# Patterns that should never appear in a hermetic build log. Each is a
# regex run against the *trimmed* line, so leading shell-trace prefixes
# (``+ `` from ``set -x``, ``$ `` from prompt echoes) do not hide them.
# Order matters: the first pattern to match wins, so more specific
# patterns (``python -m pip install``) come before broader ones
# (``pip install``).
#
# The optional third tuple element is a per-pattern allow list of
# literal substrings. A line that matches the pattern AND contains one
# of these substrings is permitted. Use this when a forbidden phrase
# legitimately surfaces in a hermetic log as diagnostic output (e.g.
# pybuild's own debug log line for its internal install step on a
# debian-rebuild source we cannot patch).
_FORBIDDEN_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        r"\bpython3?\s+-m\s+pip\s+install\b",
        "python -m pip install (PyPI fetch at build time)",
        (),
    ),
    (
        r"\bpip3?\s+install\b",
        "pip install (PyPI fetch at build time)",
        (),
    ),
    (
        r"\beasy_install\b",
        "easy_install (deprecated PyPI installer)",
        (),
    ),
    (
        r"\bsetup\.py\s+install\b",
        "setup.py install (bypasses dh_python3's wheel install)",
        (
            # pybuild's own diagnostic line describing the install
            # command it ran internally. Some debian-rebuild sources
            # (notably sid's python-google-auth) ship a setup.py-based
            # build with no PEP 517 backend, so pybuild falls back to
            # `setup.py install --root <destdir>`. The work stays
            # offline; the line is just pybuild reporting what it did.
            # APT.md forbids patching debian-rebuild sources, so the
            # legacy install path is out of our hands for those rows.
            "I: pybuild ",
            # setuptools' deprecation warning that always follows the
            # legacy install call. The actual command line is logged
            # separately; if it came from debian/rules instead of
            # pybuild, that line would also match the pattern and
            # would not carry "I: pybuild" -- so exempting the
            # warning text alone does not weaken the gate.
            "SetuptoolsDeprecationWarning: setup.py install is "
            "deprecated",
        ),
    ),
    (
        r"https?://(?:files\.|)pythonhosted\.org/",
        "direct pythonhosted.org fetch",
        (),
    ),
    (
        r"https?://pypi\.org/",
        "direct pypi.org fetch",
        (),
    ),
)


@dataclass(frozen=True)
class Hit:
    lineno: int
    pattern: str
    description: str
    text: str

    def format(self, source: str) -> str:
        return f"{source}:{self.lineno}: [{self.description}] {self.text}"


def _compile_patterns() -> tuple[
    tuple[re.Pattern[str], str, tuple[str, ...]], ...
]:
    return tuple(
        (re.compile(pattern), description, default_allow)
        for pattern, description, default_allow in _FORBIDDEN_PATTERNS
    )


def _line_is_allowed(line: str, allows: Sequence[str]) -> bool:
    return any(allow in line for allow in allows)


def scan_lines(
    lines: Iterable[str],
    *,
    allow: Sequence[str] = (),
) -> list[Hit]:
    """Return a list of forbidden-pattern hits in ``lines``.

    ``allow`` is a sequence of literal substrings that suppress a hit
    when present on the same line, regardless of which pattern matched.
    Use sparingly; the default with no allowlist is the strict mode CI
    runs in. Patterns that ship with their own context-specific
    exception lists (see ``_FORBIDDEN_PATTERNS``) layer below this.
    """
    compiled = _compile_patterns()
    hits: list[Hit] = []
    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if _line_is_allowed(line, allow):
            continue
        for regex, description, default_allow in compiled:
            if not regex.search(line):
                continue
            if _line_is_allowed(line, default_allow):
                # The line matches this forbidden pattern but contains
                # a per-pattern allowed substring. Stop the scan for
                # this line so we don't double-report the same content
                # against a broader pattern.
                break
            hits.append(
                Hit(
                    lineno=lineno,
                    pattern=regex.pattern,
                    description=description,
                    text=line,
                )
            )
            break
    return hits


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail if a captured build log contains forbidden "
            "network calls (pip install, easy_install, direct PyPI "
            "fetches, ...)"
        )
    )
    parser.add_argument(
        "log",
        nargs="?",
        default="-",
        help=(
            "path to the build log, or '-' for stdin (default: stdin)"
        ),
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="SUBSTR",
        help=(
            "literal substring; lines containing it are exempt from "
            "the scan. Repeatable."
        ),
    )
    return parser


def _open_log(path: str):
    if path == "-":
        return sys.stdin
    return Path(path).open(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = "stdin" if args.log == "-" else args.log
    fh = _open_log(args.log)
    try:
        hits = scan_lines(fh, allow=tuple(args.allow))
    finally:
        if fh is not sys.stdin:
            fh.close()

    if not hits:
        print(f"scan-build-log: OK ({source})")
        return 0

    print(
        f"scan-build-log: FAIL ({source}, {len(hits)} forbidden "
        f"call(s) found):",
        file=sys.stderr,
    )
    for hit in hits:
        print(hit.format(source), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
