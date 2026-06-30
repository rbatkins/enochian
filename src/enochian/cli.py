"""Command-line driver for Enochian.

Usage:
    python -m enochian run   <file.en> [--entry NAME]
    python -m enochian check <file.en>
    python -m enochian ast   <file.en>
"""

from __future__ import annotations

import sys

from .checker import check_program
from .errors import EnochianError
from .interpreter import Interpreter
from .parser import parse


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0

    command = argv[0]
    rest = argv[1:]
    entry = "main"
    if "--entry" in rest:
        i = rest.index("--entry")
        try:
            entry = rest[i + 1]
        except IndexError:
            print("error: --entry requires a name", file=sys.stderr)
            return 2
        rest = rest[:i] + rest[i + 2:]

    if not rest:
        print(f"error: command {command!r} requires a file path", file=sys.stderr)
        return 2
    path = rest[0]

    try:
        source = _read(path)
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    try:
        if command == "check":
            program = parse(source)
            check_program(program)
            print(f"ok: {path} is well-formed and well-typed")
            return 0
        if command == "ast":
            program = parse(source)
            import pprint
            pprint.pp(program)
            return 0
        if command == "run":
            program = parse(source)
            check_program(program)
            Interpreter(program).run(entry)
            return 0
        print(f"error: unknown command {command!r}", file=sys.stderr)
        return 2
    except EnochianError as exc:
        kind = type(exc).__name__
        print(f"{kind}: {exc.message}" + (f" (at {exc.line}:{exc.col})" if exc.line else ""),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
