"""Abstract syntax tree for Enochian.

Everything is an expression (uniformity reduces special cases). Declarations
at the top level are functions, records, and sum types. A block is a sequence
of `let`/`set` statements followed by a single result expression.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Type expressions (the surface syntax for types, e.g. `List[Int]`)
# ---------------------------------------------------------------------------
@dataclass
class TypeRef:
    name: str
    args: list["TypeRef"] = field(default_factory=list)
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
class FloatLit(Expr):
    value: float
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
class ResultVar(Expr):
    """The special `result` binding usable only inside `ensures`."""
    line: int = 0
    col: int = 0


@dataclass
class Unary(Expr):
    op: str
    operand: Expr
    line: int = 0
    col: int = 0


@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr
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
    """Construct a sum-type variant, e.g. `Some(3)`, `None`, `Ok(x)`."""
    variant: str
    args: list[Expr]
    line: int = 0
    col: int = 0


@dataclass
class RecordLit(Expr):
    type_name: str
    fields: dict[str, Expr]
    line: int = 0
    col: int = 0


@dataclass
class FieldAccess(Expr):
    target: Expr
    field_name: str
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
    """A match pattern.

    kind == "wildcard"  -> `_`
    kind == "binding"   -> bind whole value to `name`
    kind == "variant"   -> match variant `name` with sub-patterns `subpatterns`
    kind == "literal"   -> match a literal `value`
    """
    kind: str
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
    mutable: bool
    declared_type: TypeRef | None
    value: Expr
    line: int = 0
    col: int = 0


@dataclass
class SetStmt:
    name: str
    value: Expr
    line: int = 0
    col: int = 0


@dataclass
class ExprStmt:
    """A statement whose value is discarded. Only `Unit`-typed expressions may
    appear here (enforced by the checker), so meaningful results are never
    dropped by accident -- a common, hard-to-spot bug in other languages."""
    expr: Expr
    line: int = 0
    col: int = 0


@dataclass
class Block(Expr):
    statements: list[object]  # LetStmt | SetStmt
    result: Expr
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
class Contract:
    kind: str  # "requires" | "ensures"
    expr: Expr
    line: int = 0
    col: int = 0


@dataclass
class FnDecl:
    name: str
    params: list[Param]
    return_type: TypeRef
    effects: set[str]
    contracts: list[Contract]
    body: Expr
    line: int = 0
    col: int = 0


@dataclass
class VariantDef:
    name: str
    arg_types: list[TypeRef]


@dataclass
class TypeDecl:
    name: str
    variants: list[VariantDef]
    line: int = 0
    col: int = 0


@dataclass
class FieldDef:
    name: str
    type: TypeRef


@dataclass
class RecordDecl:
    name: str
    fields: list[FieldDef]
    line: int = 0
    col: int = 0


@dataclass
class Program:
    type_decls: list[TypeDecl]
    record_decls: list[RecordDecl]
    fn_decls: list[FnDecl]
