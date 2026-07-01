"""AST for Treaty."""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Type surface syntax
# ---------------------------------------------------------------------------
@dataclass
class TypeRef:
    name: str
    args: list["TypeRef"] = field(default_factory=list)
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------------------
# Refinement surface syntax (parsed into refinements.Refinement by the checker)
# ---------------------------------------------------------------------------
@dataclass
class Pred:
    kind: str          # "path" | "host" | "bytes_le" | "total_le"
    value: object      # str for path/host, int for the *_le
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------
class Expr:
    line: int = 0
    col: int = 0


@dataclass
class IntLit(Expr):
    value: int
    line: int = 0
    col: int = 0


@dataclass
class TextLit(Expr):
    value: str
    line: int = 0
    col: int = 0


@dataclass
class BoolLit(Expr):
    value: bool
    line: int = 0
    col: int = 0


@dataclass
class ListLit(Expr):
    elements: list[Expr]
    line: int = 0
    col: int = 0


@dataclass
class Var(Expr):
    name: str
    line: int = 0
    col: int = 0


@dataclass
class ClaimExpr(Expr):
    """`claim VERB over DOMAIN [where PRED and ...]`"""
    verb: str
    domain: str
    preds: list[Pred]
    line: int = 0
    col: int = 0


@dataclass
class Negotiate(Expr):
    """`negotiate(claimExpr)` -> Outcome"""
    claim: Expr
    line: int = 0
    col: int = 0


@dataclass
class MethodCall(Expr):
    """`receiver.verb(args)` -- the ONLY way to exercise a world power."""
    receiver: Expr
    verb: str
    args: list[Expr]
    line: int = 0
    col: int = 0


@dataclass
class Call(Expr):
    callee: str
    args: list[Expr]
    line: int = 0
    col: int = 0


@dataclass
class Construct(Expr):
    """Ok/Err/Granted/Countered/Refused constructors."""
    tag: str
    args: list[Expr]
    line: int = 0
    col: int = 0


@dataclass
class If(Expr):
    cond: Expr
    then_branch: Expr
    else_branch: Expr
    line: int = 0
    col: int = 0


@dataclass
class Pattern:
    kind: str                       # "wildcard" | "binding" | "variant" | "literal"
    name: str | None = None
    subpatterns: list["Pattern"] = field(default_factory=list)
    value: object = None
    line: int = 0
    col: int = 0


@dataclass
class MatchCase:
    pattern: Pattern
    body: Expr


@dataclass
class Match(Expr):
    scrutinee: Expr
    cases: list[MatchCase]
    line: int = 0
    col: int = 0


@dataclass
class LetStmt:
    name: str
    value: Expr
    line: int = 0
    col: int = 0


@dataclass
class ExprStmt:
    expr: Expr
    line: int = 0
    col: int = 0


@dataclass
class Block(Expr):
    statements: list[object]        # LetStmt | ExprStmt
    result: Expr
    line: int = 0
    col: int = 0


@dataclass
class Region(Expr):
    """`region NAME { ... }` -- a lexical scope after which every lease
    negotiated inside is revoked. A lease may not escape it."""
    name: str
    body: Block
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------
@dataclass
class Param:
    name: str
    type: TypeRef


@dataclass
class FnDecl:
    name: str
    params: list[Param]
    return_type: TypeRef
    body: Expr
    line: int = 0
    col: int = 0


@dataclass
class Grant:
    """A clause in the environment's policy."""
    refuse: bool
    verb: str
    domain: str
    preds: list[Pred]
    line: int = 0
    col: int = 0


@dataclass
class Policy:
    grants: list[Grant]
    line: int = 0
    col: int = 0


@dataclass
class Program:
    policy: Policy | None
    fns: list[FnDecl]
