"""Enochian: a small, statically-checked language designed for AI authorship.

Public helpers wire the pipeline together:

    parse(source) -> Program
    check_program(program) -> Checker          # raises CompileError on any fault
    Interpreter(program).run("main")           # executes, enforcing contracts
"""

from __future__ import annotations

from .checker import check_program
from .errors import (
    CompileError, ContractError, EnochianError, LexError, ParseError, PanicError,
)
from .interpreter import Interpreter
from .parser import parse

__all__ = [
    "parse", "check_program", "Interpreter", "compile_source", "run_source",
    "EnochianError", "LexError", "ParseError", "CompileError", "ContractError",
    "PanicError",
]

__version__ = "0.1.0"


def compile_source(source: str):
    """Parse and statically check `source`. Returns (program, checker).
    Raises an EnochianError subclass on any lex/parse/compile fault."""
    program = parse(source)
    checker = check_program(program)
    return program, checker


def run_source(source: str, entry: str = "main", args=None, out=None):
    """Compile and run `source`, returning the entry function's value."""
    program, _ = compile_source(source)
    return Interpreter(program, out=out).run(entry, args or [])
