"""Command-line driver for Treaty.

    python -m treaty run      <file.treaty> [--entry NAME]
    python -m treaty check    <file.treaty>
    python -m treaty manifest <file.treaty>   # print the derived treaty manifest
"""

from __future__ import annotations

import sys

from .checker import check_program
from .errors import TreatyError
from .interpreter import Interpreter, Sandbox
from .parser import parse


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _print_manifest(clauses) -> None:
    print("treaty manifest (derived, sound over-approximation):")
    if not clauses:
        print("  (empty -- this program requests no world powers)")
        return
    for c in clauses:
        print("  " + c.render())


def _demo_sandbox() -> Sandbox:
    return Sandbox(vfs={
        "/data/today/report.txt": "sales up 4pct",
        "/data/today/notes.txt": "ship friday",
        "/data/archive/old.txt": "stale",
        "/etc/passwd": "root:x:0:0",
    })


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
        program = parse(source)
        if command == "check":
            checker = check_program(program)
            print(f"ok: {path} is well-formed and well-typed")
            _print_manifest(checker.manifest_clauses())
            return 0
        if command == "manifest":
            checker = check_program(program)
            _print_manifest(checker.manifest_clauses())
            return 0
        if command == "run":
            checker = check_program(program)
            interp = Interpreter(program, sandbox=_demo_sandbox())
            interp.cosign(checker.manifest_clauses())
            result = interp.run(entry)
            print(f"result: {result!r}")
            if interp.sandbox.sent:
                print("net.send log:")
                for host, data in interp.sandbox.sent:
                    print(f"  -> {host}: {data!r}")
            return 0
        print(f"error: unknown command {command!r}", file=sys.stderr)
        return 2
    except TreatyError as exc:
        kind = type(exc).__name__
        loc = f" (at {exc.line}:{exc.col})" if exc.line else ""
        print(f"{kind}: {exc.message}{loc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
