"""Tree-walking interpreter for Enochian.

The checker has already proven the program well-typed, exhaustive, effect-safe,
and mutation-safe, so the interpreter focuses on evaluation and on enforcing
the two runtime guarantees the type system cannot:

  * `requires`/`ensures` contracts (executable specifications), and
  * total arithmetic (division by zero aborts as a ContractError instead of
    producing undefined or silently-wrong results).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from . import ast
from .errors import ContractError, PanicError


# ---------------------------------------------------------------------------
# Runtime values
# ---------------------------------------------------------------------------
class Unit:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "unit"


UNIT_VALUE = Unit()


@dataclass
class VariantValue:
    tag: str
    fields: tuple

    def __eq__(self, other) -> bool:
        return isinstance(other, VariantValue) and self.tag == other.tag and self.fields == other.fields

    def __hash__(self) -> int:
        return hash((self.tag, self.fields))


@dataclass
class RecordValue:
    type_name: str
    fields: dict

    def __eq__(self, other) -> bool:
        return (isinstance(other, RecordValue) and self.type_name == other.type_name
                and self.fields == other.fields)


class Environment:
    """A lexical scope with a parent link so `set` can reach an outer `mut`."""

    __slots__ = ("vars", "parent")

    def __init__(self, parent: "Environment | None" = None):
        self.vars: dict[str, object] = {}
        self.parent = parent

    def get(self, name: str):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise KeyError(name)  # pragma: no cover - checker prevents this

    def declare(self, name: str, value) -> None:
        self.vars[name] = value

    def assign(self, name: str, value) -> None:
        env = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = value
                return
            env = env.parent
        raise KeyError(name)  # pragma: no cover - checker prevents this


def _trunc_div(a: int, b: int) -> int:
    """Integer division truncated toward zero (consistent across signs)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _trunc_mod(a: int, b: int) -> int:
    return a - b * _trunc_div(a, b)


class Interpreter:
    def __init__(self, program: ast.Program, out=None):
        self.functions = {fn.name: fn for fn in program.fn_decls}
        self.out = out if out is not None else sys.stdout.write

    # -- program entry ------------------------------------------------------
    def run(self, entry: str = "main", args: list | None = None):
        if entry not in self.functions:
            raise PanicError(f"no function named {entry!r} to run")
        return self.call_function(self.functions[entry], args or [])

    # -- function application with contract enforcement ---------------------
    def call_function(self, fn: ast.FnDecl, args: list):
        env = Environment()
        for param, value in zip(fn.params, args):
            env.declare(param.name, value)

        for c in fn.contracts:
            if c.kind == "requires":
                if not self.eval(c.expr, env):
                    raise ContractError(
                        f"precondition failed in {fn.name!r}: requires {_src(c.expr)}",
                        c.line, c.col)

        result = self.eval(fn.body, env)

        for c in fn.contracts:
            if c.kind == "ensures":
                cenv = Environment(env)
                cenv.declare("__result__", result)
                if not self.eval(c.expr, cenv):
                    raise ContractError(
                        f"postcondition failed in {fn.name!r}: ensures {_src(c.expr)}",
                        c.line, c.col)
        return result

    # -- evaluation ---------------------------------------------------------
    def eval(self, expr: ast.Expr, env: Environment):
        return getattr(self, "_eval_" + type(expr).__name__)(expr, env)

    def _eval_IntLit(self, e, env):
        return e.value

    def _eval_FloatLit(self, e, env):
        return e.value

    def _eval_TextLit(self, e, env):
        return e.value

    def _eval_BoolLit(self, e, env):
        return e.value

    def _eval_Var(self, e, env):
        return env.get(e.name)

    def _eval_ResultVar(self, e, env):
        return env.get("__result__")

    def _eval_ListLit(self, e, env):
        return [self.eval(el, env) for el in e.elements]

    def _eval_Unary(self, e, env):
        v = self.eval(e.operand, env)
        if e.op == "not":
            return not v
        return -v

    def _eval_Binary(self, e, env):
        op = e.op
        # Short-circuit logical operators.
        if op == "and":
            return self.eval(e.left, env) and self.eval(e.right, env)
        if op == "or":
            return self.eval(e.left, env) or self.eval(e.right, env)

        left = self.eval(e.left, env)
        right = self.eval(e.right, env)

        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "::":
            return [left] + right
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                raise ContractError("division by zero", e.line, e.col)
            if isinstance(left, int) and isinstance(right, int):
                return _trunc_div(left, right)
            return left / right
        if op == "%":
            if right == 0:
                raise ContractError("modulo by zero", e.line, e.col)
            return _trunc_mod(left, right)
        raise PanicError(f"unknown operator {op!r}", e.line, e.col)  # pragma: no cover

    def _eval_If(self, e, env):
        if self.eval(e.cond, env):
            return self.eval(e.then_branch, env)
        return self.eval(e.else_branch, env)

    def _eval_Block(self, e, env):
        scope = Environment(env)
        for stmt in e.statements:
            if isinstance(stmt, ast.LetStmt):
                scope.declare(stmt.name, self.eval(stmt.value, scope))
            elif isinstance(stmt, ast.SetStmt):
                scope.assign(stmt.name, self.eval(stmt.value, scope))
            elif isinstance(stmt, ast.ExprStmt):
                self.eval(stmt.expr, scope)
        return self.eval(e.result, scope)

    def _eval_Call(self, e, env):
        args = [self.eval(a, env) for a in e.args]
        if e.callee in BUILTIN_IMPLS:
            return BUILTIN_IMPLS[e.callee](self, args)
        return self.call_function(self.functions[e.callee], args)

    def _eval_Construct(self, e, env):
        return VariantValue(e.variant, tuple(self.eval(a, env) for a in e.args))

    def _eval_RecordLit(self, e, env):
        return RecordValue(e.type_name, {k: self.eval(v, env) for k, v in e.fields.items()})

    def _eval_FieldAccess(self, e, env):
        target = self.eval(e.target, env)
        return target.fields[e.field_name]

    def _eval_Match(self, e, env):
        value = self.eval(e.scrutinee, env)
        for case in e.cases:
            bindings: dict[str, object] = {}
            if self._match_pattern(case.pattern, value, bindings):
                scope = Environment(env)
                for name, val in bindings.items():
                    scope.declare(name, val)
                return self.eval(case.body, scope)
        # The checker guarantees exhaustiveness, so this is unreachable.
        raise PanicError("no match arm fired (internal invariant violated)", e.line, e.col)

    def _match_pattern(self, p: ast.Pattern, value, bindings: dict) -> bool:
        if p.kind == "wildcard":
            return True
        if p.kind == "binding":
            bindings[p.name] = value
            return True
        if p.kind == "literal":
            return value == p.value and type(value) is type(p.value)
        if p.kind == "empty_list":
            return isinstance(value, list) and len(value) == 0
        if p.kind == "cons":
            if not isinstance(value, list) or len(value) == 0:
                return False
            if not self._match_pattern(p.subpatterns[0], value[0], bindings):
                return False
            return self._match_pattern(p.subpatterns[1], value[1:], bindings)
        if p.kind == "variant":
            if not isinstance(value, VariantValue) or value.tag != p.name:
                return False
            for sub, fld in zip(p.subpatterns, value.fields):
                if not self._match_pattern(sub, fld, bindings):
                    return False
            return True
        raise PanicError(f"unknown pattern kind {p.kind!r}")  # pragma: no cover


def _src(expr: ast.Expr) -> str:
    """A best-effort textual rendering of a contract expression for messages."""
    from .ast import Binary, Var, IntLit, FloatLit, BoolLit, TextLit, Call, ResultVar, Unary, FieldAccess
    if isinstance(expr, Binary):
        return f"{_src(expr.left)} {expr.op} {_src(expr.right)}"
    if isinstance(expr, Unary):
        return f"{expr.op} {_src(expr.operand)}"
    if isinstance(expr, Var):
        return expr.name
    if isinstance(expr, ResultVar):
        return "result"
    if isinstance(expr, FieldAccess):
        return f"{_src(expr.target)}.{expr.field_name}"
    if isinstance(expr, (IntLit, FloatLit, BoolLit)):
        return str(expr.value)
    if isinstance(expr, TextLit):
        return repr(expr.value)
    if isinstance(expr, Call):
        return f"{expr.callee}({', '.join(_src(a) for a in expr.args)})"
    return "<expr>"


# ---------------------------------------------------------------------------
# Builtin implementations
# ---------------------------------------------------------------------------
def _impl_print(interp: Interpreter, args):
    interp.out(str(args[0]) + "\n")
    return UNIT_VALUE


def _impl_len(interp, args):
    return len(args[0])


def _impl_get(interp, args):
    lst, idx = args
    if 0 <= idx < len(lst):
        return VariantValue("Some", (lst[idx],))
    return VariantValue("None", ())


def _impl_push(interp, args):
    lst, item = args
    return lst + [item]


def _impl_concat(interp, args):
    return args[0] + args[1]


def _impl_int_to_text(interp, args):
    return str(args[0])


def _impl_float_to_text(interp, args):
    return repr(args[0])


def _impl_bool_to_text(interp, args):
    return "true" if args[0] else "false"


def _impl_text_len(interp, args):
    return len(args[0])


BUILTIN_IMPLS = {
    "print": _impl_print,
    "len": _impl_len,
    "get": _impl_get,
    "push": _impl_push,
    "concat": _impl_concat,
    "int_to_text": _impl_int_to_text,
    "float_to_text": _impl_float_to_text,
    "bool_to_text": _impl_bool_to_text,
    "text_len": _impl_text_len,
}
