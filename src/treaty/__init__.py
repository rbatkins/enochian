"""Treaty: a language in which the world starts empty.

Every power a program uses (filesystem, network, clock, randomness) must be
requested as data, negotiated with the environment, and held only as a scoped,
budgeted lease. Effect verbs are not ambient names -- they exist only as methods
on a lease. The set of powers a program can request is a statically-derived,
diffable *manifest* the environment co-signs before anything runs.

Pipeline:
    parse(src) -> Program
    check_program(program) -> Checker         # static checks + manifest
    Interpreter(program).cosign(manifest)      # environment co-signs, or refuses
    Interpreter(program).run("main")           # execute against leases
"""

from __future__ import annotations

from .checker import check_program
from .errors import (
    CompileError, LaunchRefused, LeaseError, LexError, ParseError, PanicError, TreatyError,
)
from .interpreter import Interpreter, Sandbox
from .parser import parse

__all__ = [
    "parse", "check_program", "Interpreter", "Sandbox",
    "compile_source", "run_source",
    "TreatyError", "LexError", "ParseError", "CompileError",
    "LaunchRefused", "LeaseError", "PanicError",
]

__version__ = "0.1.0"


def compile_source(source: str):
    program = parse(source)
    checker = check_program(program)
    return program, checker


def run_source(source: str, entry: str = "main", sandbox: Sandbox | None = None):
    """Full pipeline: parse, check, co-sign the derived manifest, then run.
    Returns (result_value, interpreter) so callers can inspect side effects."""
    program, checker = compile_source(source)
    interp = Interpreter(program, sandbox=sandbox)
    interp.cosign(checker.manifest_clauses())
    result = interp.run(entry)
    return result, interp
