"""Treaty error hierarchy.

The categories mirror the two-phase execution model:

  * ParseError / CompileError happen in PHASE 1 (static). CompileError covers
    type errors AND the treaty-specific faults: touching the world outside a
    lease, calling a verb outside its lease's refinement, letting a lease
    escape its region.
  * LaunchRefused happens at the phase boundary: the environment read the
    derived manifest and refused to co-sign a clause. Nothing has run yet.
  * LeaseError / PanicError happen in PHASE 2 (runtime): a lease's cumulative
    budget was exhausted, or an explicit abort. These are the only faults that
    can occur once effects begin.
"""

from __future__ import annotations


class TreatyError(Exception):
    def __init__(self, message: str, line: int | None = None, col: int | None = None):
        self.message = message
        self.line = line
        self.col = col
        loc = f" at {line}:{col}" if line is not None else ""
        super().__init__(f"{message}{loc}")


class LexError(TreatyError):
    pass


class ParseError(TreatyError):
    pass


class CompileError(TreatyError):
    pass


class LaunchRefused(TreatyError):
    """The environment refused to co-sign the treaty manifest before launch."""


class LeaseError(TreatyError):
    """A runtime lease violation (budget exhausted, lease revoked)."""


class PanicError(TreatyError):
    pass
