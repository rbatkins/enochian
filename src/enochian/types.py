"""The Enochian type model.

Types are nominal and explicit. There is deliberately no `null`/`nil`: absence
is expressed with `Option[T]`, and recoverable failure with `Result[T, E]`.
This is the single most effective bug-prevention decision a language can make.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class Type:
    pass


@dataclass(frozen=True)
class Prim(Type):
    name: str  # "Int" | "Float" | "Bool" | "Text" | "Unit"

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class ListType(Type):
    elem: Type

    def __str__(self) -> str:
        return f"List[{self.elem}]"


@dataclass(frozen=True)
class OptionType(Type):
    inner: Type

    def __str__(self) -> str:
        return f"Option[{self.inner}]"


@dataclass(frozen=True)
class ResultType(Type):
    ok: Type
    err: Type

    def __str__(self) -> str:
        return f"Result[{self.ok}, {self.err}]"


@dataclass(frozen=True)
class NamedType(Type):
    """A user-declared record or sum type, referenced by name."""
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class TypeVar(Type):
    """A generic parameter, e.g. the `T` in a polymorphic builtin. Used only
    for builtin signatures in this reference implementation."""
    name: str

    def __str__(self) -> str:
        return self.name


INT = Prim("Int")
FLOAT = Prim("Float")
BOOL = Prim("Bool")
TEXT = Prim("Text")
UNIT = Prim("Unit")

PRIMS = {"Int": INT, "Float": FLOAT, "Bool": BOOL, "Text": TEXT, "Unit": UNIT}


def unify_equal(a: Type, b: Type) -> bool:
    """Structural equality with TypeVar acting as a wildcard. This is *not* a
    full unifier; it is just enough to type-check calls to the polymorphic
    builtins (List/Option/Result helpers)."""
    if isinstance(a, TypeVar) or isinstance(b, TypeVar):
        return True
    if type(a) is not type(b):
        return False
    if isinstance(a, Prim):
        return a.name == b.name
    if isinstance(a, NamedType):
        return a.name == b.name
    if isinstance(a, ListType):
        return unify_equal(a.elem, b.elem)
    if isinstance(a, OptionType):
        return unify_equal(a.inner, b.inner)
    if isinstance(a, ResultType):
        return unify_equal(a.ok, b.ok) and unify_equal(a.err, b.err)
    return False
