"""The refinement algebra at the heart of Treaty.

A CLAIM asks for a power (a verb over a domain) constrained by a REFINEMENT.
A GRANT (from the environment's policy) offers a power up to some refinement.
`negotiate` compares the two and returns Granted / Countered / Refused.

The whole point is that this comparison is *decidable* and *syntactic*, so the
checker can reason about it statically (for the manifest and for compile-time
argument checks) and the runtime can reason about it identically. A refinement
is a conjunction of at most four independent predicates:

    path under "P"     the path argument must have prefix P
    host eq "H"        the host argument must equal H
    bytes_le N         a single call's data length must be <= N
    total_le N         the lease's *cumulative* data length must stay <= N

`None` on a field means "unconstrained" (top) for that dimension.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Refinement:
    path_prefix: str | None = None
    host: str | None = None
    bytes_le: int | None = None
    total_le: int | None = None

    # -- lattice-ish operations --------------------------------------------
    def is_top(self) -> bool:
        return (self.path_prefix is None and self.host is None
                and self.bytes_le is None and self.total_le is None)

    def entails(self, other: "Refinement") -> bool:
        """True if holding `self` implies holding `other` (self <= other):
        self is at least as restrictive as other on every dimension other
        constrains."""
        if other.path_prefix is not None:
            if self.path_prefix is None or not self.path_prefix.startswith(other.path_prefix):
                return False
        if other.host is not None:
            if self.host != other.host:
                return False
        if other.bytes_le is not None:
            if self.bytes_le is None or self.bytes_le > other.bytes_le:
                return False
        if other.total_le is not None:
            if self.total_le is None or self.total_le > other.total_le:
                return False
        return True

    def compatible(self, other: "Refinement") -> bool:
        """False only on a hard conflict that no narrowing can reconcile:
        different required hosts, or path prefixes where neither contains the
        other."""
        if self.host is not None and other.host is not None and self.host != other.host:
            return False
        if self.path_prefix is not None and other.path_prefix is not None:
            if not (self.path_prefix.startswith(other.path_prefix)
                    or other.path_prefix.startswith(self.path_prefix)):
                return False
        return True

    def meet(self, other: "Refinement") -> "Refinement":
        """The tightest refinement that entails both (assumes compatible)."""
        # path: the more specific (longer) prefix wins.
        if self.path_prefix is None:
            path = other.path_prefix
        elif other.path_prefix is None:
            path = self.path_prefix
        else:
            path = self.path_prefix if len(self.path_prefix) >= len(other.path_prefix) else other.path_prefix
        host = self.host if self.host is not None else other.host
        bytes_le = _min_opt(self.bytes_le, other.bytes_le)
        total_le = _min_opt(self.total_le, other.total_le)
        return Refinement(path, host, bytes_le, total_le)

    def render(self) -> str:
        parts = []
        if self.path_prefix is not None:
            parts.append(f'path under "{self.path_prefix}"')
        if self.host is not None:
            parts.append(f'host eq "{self.host}"')
        if self.bytes_le is not None:
            parts.append(f"bytes_le {self.bytes_le}")
        if self.total_le is not None:
            parts.append(f"total_le {self.total_le}")
        return " and ".join(parts) if parts else "(unconstrained)"


def _min_opt(a: int | None, b: int | None) -> int | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


# Sentinel used by the checker when a claim's refinement cannot be resolved
# statically (it depends on runtime data). It over-approximates to TOP and is
# flagged so the manifest can report it honestly rather than pretend precision.
TOP = Refinement()


@dataclass(frozen=True)
class StaticClaim:
    """What the checker knows about a claim value at compile time."""
    domain: str
    verb: str
    refinement: Refinement
    data_dependent: bool = False
