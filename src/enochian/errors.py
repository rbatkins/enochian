"""Error types for the Enochian language.

Enochian draws a hard line between three categories of failure, because
conflating them is a major historical source of bugs:

  1. CompileError  -- the program is not well-formed or not well-typed.
                      Caught before anything runs. The AI/author must fix it.
  2. ContractError -- a `requires`/`ensures` contract was violated at runtime.
                      This is always a *programmer* bug, never recoverable
                      control flow. It aborts loudly.
  3. (no exceptions for ordinary failure) -- expected, recoverable failure is
                      modelled in the type system with Result/Option, never
                      with thrown exceptions.

This separation means: control flow you can *see* in the types, and bugs that
abort instead of hiding.
"""

from __future__ import annotations


class EnochianError(Exception):
    """Base class for every Enochian-level error."""

    def __init__(self, message: str, line: int | None = None, col: int | None = None):
        self.message = message
        self.line = line
        self.col = col
        loc = f" at {line}:{col}" if line is not None else ""
        super().__init__(f"{message}{loc}")


class LexError(EnochianError):
    """Raised when source text cannot be tokenized."""


class ParseError(EnochianError):
    """Raised when tokens cannot be parsed into an AST."""


class CompileError(EnochianError):
    """Raised by the static checker: type errors, unbound names,
    non-exhaustive matches, effect violations, mutability violations."""


class ContractError(EnochianError):
    """Raised at runtime when a `requires` or `ensures` clause fails.
    This always indicates a programmer bug and is never catchable from
    within Enochian code."""


class PanicError(EnochianError):
    """Raised by the builtin `panic` -- an explicit, acknowledged abort."""
