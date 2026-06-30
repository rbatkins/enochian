"""Static checker for Enochian.

This pass is where Enochian earns its "minimize bugs" claim. Before a single
line runs it proves, statically:

  * every name is bound and every type resolves (no undefined references);
  * every expression is well-typed (no implicit coercion, no `null`);
  * every `match` is exhaustive and has no unreachable arms;
  * every `set` targets a variable explicitly declared `mut`;
  * every function performs only the effects it declares (`!io`, ...);
  * `requires`/`ensures` contracts are pure and boolean.

Light bidirectional inference lets context resolve otherwise-ambiguous values
such as `None` or `[]`.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import ast
from .errors import CompileError
from .types import (
    BOOL, FLOAT, INT, PRIMS, TEXT, UNIT,
    ListType, NamedType, OptionType, Prim, ResultType, Type, TypeVar,
    unify_equal,
)


@dataclass
class VarInfo:
    type: Type
    mutable: bool


@dataclass
class FnSig:
    params: list[tuple[str, Type]]
    ret: Type
    effects: set[str]


class Checker:
    def __init__(self, program: ast.Program):
        self.program = program
        self.records: dict[str, dict[str, Type]] = {}
        self.sumtypes: dict[str, dict[str, list[Type]]] = {}
        self.variant_owner: dict[str, str] = {}
        self.functions: dict[str, FnSig] = {}
        self._fresh = 0

    def fresh_var(self, hint: str = "?") -> TypeVar:
        self._fresh += 1
        return TypeVar(f"{hint}{self._fresh}")

    # -- public entry -------------------------------------------------------
    def check(self) -> None:
        self._collect_types()
        self._collect_functions()
        for fn in self.program.fn_decls:
            self._check_fn(fn)

    # -- collection passes --------------------------------------------------
    def _collect_types(self) -> None:
        # Pass 1: register every type *name* (as an empty placeholder) so that
        # field and variant types may reference any declared type regardless of
        # declaration order (forward references are allowed).
        names = set(PRIMS) | {"List", "Option", "Result"}
        for rec in self.program.record_decls:
            if rec.name in names:
                raise CompileError(f"type name {rec.name!r} is already in use", rec.line, rec.col)
            if not rec.name[0].isupper():
                raise CompileError(f"type name {rec.name!r} must start uppercase", rec.line, rec.col)
            names.add(rec.name)
            self.records[rec.name] = {}
        for sm in self.program.type_decls:
            if sm.name in names:
                raise CompileError(f"type name {sm.name!r} is already in use", sm.line, sm.col)
            if not sm.name[0].isupper():
                raise CompileError(f"type name {sm.name!r} must start uppercase", sm.line, sm.col)
            names.add(sm.name)
            self.sumtypes[sm.name] = {}

        # Pass 2: resolve field/variant types now that all names are known.
        for rec in self.program.record_decls:
            fields: dict[str, Type] = {}
            for f in rec.fields:
                if f.name in fields:
                    raise CompileError(f"duplicate field {f.name!r} in record {rec.name}", rec.line, rec.col)
                fields[f.name] = self.resolve_type(f.type)
            self.records[rec.name] = fields

        reserved_variants = {"Some", "None", "Ok", "Err"}
        for sm in self.program.type_decls:
            variants: dict[str, list[Type]] = {}
            for v in sm.variants:
                if not v.name[0].isupper():
                    raise CompileError(f"variant {v.name!r} must start uppercase", sm.line, sm.col)
                if v.name in reserved_variants:
                    raise CompileError(f"variant name {v.name!r} is reserved", sm.line, sm.col)
                if v.name in self.variant_owner:
                    raise CompileError(f"variant {v.name!r} is declared in more than one type", sm.line, sm.col)
                variants[v.name] = [self.resolve_type(t) for t in v.arg_types]
                self.variant_owner[v.name] = sm.name
            self.sumtypes[sm.name] = variants

    def _collect_functions(self) -> None:
        for fn in self.program.fn_decls:
            if not fn.name[0].islower():
                raise CompileError(f"function {fn.name!r} must start lowercase", fn.line, fn.col)
            if fn.name in self.functions or fn.name in BUILTINS:
                raise CompileError(f"function {fn.name!r} is already defined", fn.line, fn.col)
            seen = set()
            params = []
            for p in fn.params:
                if p.name in seen:
                    raise CompileError(f"duplicate parameter {p.name!r} in {fn.name}", fn.line, fn.col)
                seen.add(p.name)
                params.append((p.name, self.resolve_type(p.type)))
            self.functions[fn.name] = FnSig(params, self.resolve_type(fn.return_type), set(fn.effects))

    # -- type resolution ----------------------------------------------------
    def resolve_type(self, ref: ast.TypeRef) -> Type:
        name = ref.name
        if name in PRIMS:
            self._expect_args(ref, 0)
            return PRIMS[name]
        if name == "List":
            self._expect_args(ref, 1)
            return ListType(self.resolve_type(ref.args[0]))
        if name == "Option":
            self._expect_args(ref, 1)
            return OptionType(self.resolve_type(ref.args[0]))
        if name == "Result":
            self._expect_args(ref, 2)
            return ResultType(self.resolve_type(ref.args[0]), self.resolve_type(ref.args[1]))
        if name in self.records or name in self.sumtypes:
            self._expect_args(ref, 0)
            return NamedType(name)
        raise CompileError(f"unknown type {name!r}", ref.line, ref.col)

    def _expect_args(self, ref: ast.TypeRef, n: int) -> None:
        if len(ref.args) != n:
            raise CompileError(
                f"type {ref.name!r} expects {n} type argument(s), got {len(ref.args)}",
                ref.line, ref.col,
            )

    # -- function checking --------------------------------------------------
    def _check_fn(self, fn: ast.FnDecl) -> None:
        sig = self.functions[fn.name]
        env: dict[str, VarInfo] = {n: VarInfo(t, False) for n, t in sig.params}

        # Contracts must be pure booleans.
        for c in fn.contracts:
            cenv = dict(env)
            if c.kind == "ensures":
                cenv["__result__"] = VarInfo(sig.ret, False)
            ceff: set[str] = set()
            ctype = self.infer(c.expr, cenv, ceff, BOOL)
            if not unify_equal(ctype, BOOL):
                raise CompileError(
                    f"{c.kind} contract must be Bool, got {ctype}", c.line, c.col)
            if ceff:
                raise CompileError(
                    f"{c.kind} contract must be pure but performs effects {sorted(ceff)}",
                    c.line, c.col)

        effects: set[str] = set()
        body_type = self.infer(fn.body, env, effects, sig.ret)
        if not unify_equal(body_type, sig.ret):
            raise CompileError(
                f"function {fn.name!r} declares return type {sig.ret} but body has type {body_type}",
                fn.line, fn.col)
        undeclared = effects - sig.effects
        if undeclared:
            raise CompileError(
                f"function {fn.name!r} performs effect(s) {sorted(undeclared)} "
                f"that are not declared (add {' '.join('!' + e for e in sorted(undeclared))})",
                fn.line, fn.col)

    # -- expression inference ----------------------------------------------
    def infer(self, expr: ast.Expr, env: dict[str, VarInfo], effects: set[str],
              expected: Type | None) -> Type:
        method = getattr(self, "_infer_" + type(expr).__name__, None)
        if method is None:  # pragma: no cover - defensive
            raise CompileError(f"cannot type-check node {type(expr).__name__}", expr.line, expr.col)
        return method(expr, env, effects, expected)

    def _infer_IntLit(self, e, env, effects, expected) -> Type:
        return INT

    def _infer_FloatLit(self, e, env, effects, expected) -> Type:
        return FLOAT

    def _infer_TextLit(self, e, env, effects, expected) -> Type:
        return TEXT

    def _infer_BoolLit(self, e, env, effects, expected) -> Type:
        return BOOL

    def _infer_Var(self, e, env, effects, expected) -> Type:
        info = env.get(e.name)
        if info is None:
            raise CompileError(f"undefined variable {e.name!r}", e.line, e.col)
        return info.type

    def _infer_ResultVar(self, e, env, effects, expected) -> Type:
        info = env.get("__result__")
        if info is None:
            raise CompileError("`result` may only be used inside an `ensures` contract", e.line, e.col)
        return info.type

    def _infer_ListLit(self, e, env, effects, expected) -> Type:
        elem_expected = expected.elem if isinstance(expected, ListType) else None
        if not e.elements:
            if isinstance(expected, ListType):
                return expected
            return ListType(self.fresh_var("elem"))
        first = self.infer(e.elements[0], env, effects, elem_expected)
        for el in e.elements[1:]:
            t = self.infer(el, env, effects, first)
            if not unify_equal(t, first):
                raise CompileError(
                    f"list elements must share a type: {first} vs {t}", el.line, el.col)
        return ListType(first)

    def _infer_Unary(self, e, env, effects, expected) -> Type:
        if e.op == "not":
            t = self.infer(e.operand, env, effects, BOOL)
            if not unify_equal(t, BOOL):
                raise CompileError(f"`not` requires Bool, got {t}", e.line, e.col)
            return BOOL
        # numeric negation
        t = self.infer(e.operand, env, effects, expected)
        if not (unify_equal(t, INT) or unify_equal(t, FLOAT)):
            raise CompileError(f"unary `-` requires Int or Float, got {t}", e.line, e.col)
        return t

    def _infer_Binary(self, e, env, effects, expected) -> Type:
        op = e.op
        if op in ("and", "or"):
            lt = self.infer(e.left, env, effects, BOOL)
            rt = self.infer(e.right, env, effects, BOOL)
            if not (unify_equal(lt, BOOL) and unify_equal(rt, BOOL)):
                raise CompileError(f"`{op}` requires Bool operands, got {lt} and {rt}", e.line, e.col)
            return BOOL
        if op in ("==", "!="):
            lt = self.infer(e.left, env, effects, None)
            rt = self.infer(e.right, env, effects, lt)
            if not unify_equal(lt, rt):
                raise CompileError(f"cannot compare {lt} with {rt}", e.line, e.col)
            return BOOL
        if op in ("<", "<=", ">", ">="):
            lt = self.infer(e.left, env, effects, None)
            rt = self.infer(e.right, env, effects, lt)
            if not unify_equal(lt, rt) or not isinstance(lt, Prim) or lt == BOOL or lt == UNIT:
                raise CompileError(
                    f"`{op}` requires two Int, Float, or Text operands, got {lt} and {rt}",
                    e.line, e.col)
            return BOOL
        if op == "::":
            elem_expected = expected.elem if isinstance(expected, ListType) else None
            head = self.infer(e.left, env, effects, elem_expected)
            tail = self.infer(e.right, env, effects, ListType(head))
            if not unify_equal(tail, ListType(head)):
                raise CompileError(f"`::` requires List[{head}] on the right, got {tail}", e.line, e.col)
            return ListType(head)
        # arithmetic: + - * / %
        lt = self.infer(e.left, env, effects, expected)
        rt = self.infer(e.right, env, effects, lt)
        if op == "+" and unify_equal(lt, TEXT) and unify_equal(rt, TEXT):
            return TEXT
        if not unify_equal(lt, rt):
            raise CompileError(f"`{op}` requires matching numeric operands, got {lt} and {rt}", e.line, e.col)
        if op == "%":
            if not unify_equal(lt, INT):
                raise CompileError(f"`%` requires Int operands, got {lt}", e.line, e.col)
            return INT
        if not (unify_equal(lt, INT) or unify_equal(lt, FLOAT)):
            raise CompileError(f"`{op}` requires Int or Float operands, got {lt}", e.line, e.col)
        return lt

    def _infer_If(self, e, env, effects, expected) -> Type:
        ct = self.infer(e.cond, env, effects, BOOL)
        if not unify_equal(ct, BOOL):
            raise CompileError(f"`if` condition must be Bool, got {ct}", e.line, e.col)
        tt = self.infer(e.then_branch, env, effects, expected)
        et = self.infer(e.else_branch, env, effects, expected if expected is not None else tt)
        if not unify_equal(tt, et):
            raise CompileError(f"`if` branches have different types: {tt} vs {et}", e.line, e.col)
        return tt if not isinstance(tt, TypeVar) else et

    def _infer_Block(self, e, env, effects, expected) -> Type:
        scope = dict(env)
        for stmt in e.statements:
            if isinstance(stmt, ast.LetStmt):
                declared = self.resolve_type(stmt.declared_type) if stmt.declared_type else None
                vt = self.infer(stmt.value, scope, effects, declared)
                if declared is not None and not unify_equal(vt, declared):
                    raise CompileError(
                        f"let {stmt.name!r} declared as {declared} but value is {vt}",
                        stmt.line, stmt.col)
                bound = declared if declared is not None else vt
                scope[stmt.name] = VarInfo(bound, stmt.mutable)
            elif isinstance(stmt, ast.SetStmt):
                info = scope.get(stmt.name)
                if info is None:
                    raise CompileError(f"cannot set undefined variable {stmt.name!r}", stmt.line, stmt.col)
                if not info.mutable:
                    raise CompileError(
                        f"cannot set {stmt.name!r}: it is immutable (declare it with `let mut`)",
                        stmt.line, stmt.col)
                vt = self.infer(stmt.value, scope, effects, info.type)
                if not unify_equal(vt, info.type):
                    raise CompileError(
                        f"cannot assign {vt} to {stmt.name!r} of type {info.type}",
                        stmt.line, stmt.col)
            elif isinstance(stmt, ast.ExprStmt):
                st = self.infer(stmt.expr, scope, effects, UNIT)
                if not unify_equal(st, UNIT):
                    raise CompileError(
                        f"a discarded statement must have type Unit, but this is {st}; "
                        f"bind it with `let` if you need the value",
                        stmt.line, stmt.col)
        return self.infer(e.result, scope, effects, expected)

    def _infer_Call(self, e, env, effects, expected) -> Type:
        if e.callee in BUILTINS:
            return self._check_builtin(e, env, effects, expected)
        sig = self.functions.get(e.callee)
        if sig is None:
            raise CompileError(f"call to undefined function {e.callee!r}", e.line, e.col)
        if len(e.args) != len(sig.params):
            raise CompileError(
                f"function {e.callee!r} expects {len(sig.params)} argument(s), got {len(e.args)}",
                e.line, e.col)
        for arg, (pname, ptype) in zip(e.args, sig.params):
            at = self.infer(arg, env, effects, ptype)
            if not unify_equal(at, ptype):
                raise CompileError(
                    f"argument {pname!r} of {e.callee!r} expects {ptype}, got {at}",
                    arg.line, arg.col)
        effects |= sig.effects
        return sig.ret

    def _check_builtin(self, e, env, effects, expected) -> Type:
        name = e.callee
        spec = BUILTINS[name]
        if len(e.args) != spec["arity"]:
            raise CompileError(
                f"builtin {name!r} expects {spec['arity']} argument(s), got {len(e.args)}",
                e.line, e.col)
        effects |= spec["effects"]
        argtypes = [self.infer(a, env, effects, None) for a in e.args]
        return spec["check"](self, e, argtypes)

    def _infer_Construct(self, e, env, effects, expected) -> Type:
        name = e.variant
        if name == "Some":
            self._arity(e, 1)
            inner_exp = expected.inner if isinstance(expected, OptionType) else None
            inner = self.infer(e.args[0], env, effects, inner_exp)
            return OptionType(inner)
        if name == "None":
            self._arity(e, 0)
            if isinstance(expected, OptionType):
                return expected
            return OptionType(self.fresh_var("opt"))
        if name == "Ok":
            self._arity(e, 1)
            ok_exp = expected.ok if isinstance(expected, ResultType) else None
            ok = self.infer(e.args[0], env, effects, ok_exp)
            err = expected.err if isinstance(expected, ResultType) else self.fresh_var("err")
            return ResultType(ok, err)
        if name == "Err":
            self._arity(e, 1)
            err_exp = expected.err if isinstance(expected, ResultType) else None
            err = self.infer(e.args[0], env, effects, err_exp)
            ok = expected.ok if isinstance(expected, ResultType) else self.fresh_var("ok")
            return ResultType(ok, err)
        owner = self.variant_owner.get(name)
        if owner is None:
            raise CompileError(f"unknown variant or constructor {name!r}", e.line, e.col)
        arg_types = self.sumtypes[owner][name]
        if len(e.args) != len(arg_types):
            raise CompileError(
                f"variant {name!r} expects {len(arg_types)} argument(s), got {len(e.args)}",
                e.line, e.col)
        for arg, at in zip(e.args, arg_types):
            t = self.infer(arg, env, effects, at)
            if not unify_equal(t, at):
                raise CompileError(f"variant {name!r} argument expects {at}, got {t}", arg.line, arg.col)
        return NamedType(owner)

    def _arity(self, e, n: int) -> None:
        if len(e.args) != n:
            raise CompileError(f"{e.variant!r} expects {n} argument(s), got {len(e.args)}", e.line, e.col)

    def _infer_RecordLit(self, e, env, effects, expected) -> Type:
        if e.type_name not in self.records:
            raise CompileError(f"unknown record type {e.type_name!r}", e.line, e.col)
        declared = self.records[e.type_name]
        missing = set(declared) - set(e.fields)
        extra = set(e.fields) - set(declared)
        if missing:
            raise CompileError(f"record {e.type_name} missing field(s) {sorted(missing)}", e.line, e.col)
        if extra:
            raise CompileError(f"record {e.type_name} has no field(s) {sorted(extra)}", e.line, e.col)
        for fname, fexpr in e.fields.items():
            ft = self.infer(fexpr, env, effects, declared[fname])
            if not unify_equal(ft, declared[fname]):
                raise CompileError(
                    f"field {fname!r} of {e.type_name} expects {declared[fname]}, got {ft}",
                    fexpr.line, fexpr.col)
        return NamedType(e.type_name)

    def _infer_FieldAccess(self, e, env, effects, expected) -> Type:
        target = self.infer(e.target, env, effects, None)
        if not isinstance(target, NamedType) or target.name not in self.records:
            raise CompileError(f"cannot access field {e.field_name!r} on non-record type {target}", e.line, e.col)
        fields = self.records[target.name]
        if e.field_name not in fields:
            raise CompileError(f"record {target.name} has no field {e.field_name!r}", e.line, e.col)
        return fields[e.field_name]

    # -- match --------------------------------------------------------------
    def _infer_Match(self, e, env, effects, expected) -> Type:
        scrut = self.infer(e.scrutinee, env, effects, None)
        result_type: Type | None = expected
        seen_catch_all = False
        covered_variants: set[str] = set()
        covered_bools: set[bool] = set()
        covered_empty = False
        covered_cons = False

        for i, case in enumerate(e.cases):
            if seen_catch_all:
                raise CompileError("unreachable match arm after a catch-all pattern",
                                   case.pattern.line, case.pattern.col)
            bindings: dict[str, VarInfo] = {}
            self._check_pattern(case.pattern, scrut, bindings)

            p = case.pattern
            if p.kind in ("wildcard", "binding"):
                seen_catch_all = True
            elif p.kind == "variant":
                covered_variants.add(p.name)
            elif p.kind == "literal" and isinstance(p.value, bool):
                covered_bools.add(p.value)
            elif p.kind == "empty_list":
                covered_empty = True
            elif p.kind == "cons":
                covered_cons = True

            case_env = dict(env)
            case_env.update(bindings)
            bt = self.infer(case.body, case_env, effects, result_type)
            if result_type is None or isinstance(result_type, TypeVar):
                result_type = bt
            elif not unify_equal(bt, result_type):
                raise CompileError(
                    f"match arms have different types: {result_type} vs {bt}",
                    case.pattern.line, case.pattern.col)

        if not seen_catch_all:
            self._check_exhaustive(e, scrut, covered_variants, covered_bools, covered_empty, covered_cons)
        if result_type is None:  # pragma: no cover - a match always has >=1 arm
            raise CompileError("match with no arms", e.line, e.col)
        return result_type

    def _check_pattern(self, p: ast.Pattern, scrut: Type, bindings: dict[str, VarInfo]) -> None:
        if p.kind == "wildcard":
            return
        if p.kind == "binding":
            if p.name in bindings:
                raise CompileError(f"duplicate binding {p.name!r} in pattern", p.line, p.col)
            bindings[p.name] = VarInfo(scrut, False)
            return
        if p.kind == "literal":
            lit_type = self._literal_type(p.value)
            if not unify_equal(lit_type, scrut):
                raise CompileError(f"literal pattern of type {lit_type} cannot match {scrut}", p.line, p.col)
            return
        if p.kind == "empty_list":
            if not isinstance(scrut, ListType):
                raise CompileError(f"`[]` pattern requires a List, got {scrut}", p.line, p.col)
            return
        if p.kind == "cons":
            if not isinstance(scrut, ListType):
                raise CompileError(f"`::` pattern requires a List, got {scrut}", p.line, p.col)
            self._check_pattern(p.subpatterns[0], scrut.elem, bindings)
            self._check_pattern(p.subpatterns[1], scrut, bindings)
            return
        if p.kind == "variant":
            arg_types = self._variant_arg_types(p.name, scrut, p)
            if len(p.subpatterns) != len(arg_types):
                raise CompileError(
                    f"variant pattern {p.name!r} expects {len(arg_types)} sub-pattern(s), got {len(p.subpatterns)}",
                    p.line, p.col)
            for sub, at in zip(p.subpatterns, arg_types):
                self._check_pattern(sub, at, bindings)
            return
        raise CompileError(f"unknown pattern kind {p.kind!r}", p.line, p.col)  # pragma: no cover

    def _variant_arg_types(self, name: str, scrut: Type, p: ast.Pattern) -> list[Type]:
        if isinstance(scrut, OptionType):
            if name == "Some":
                return [scrut.inner]
            if name == "None":
                return []
            raise CompileError(f"Option has no variant {name!r}", p.line, p.col)
        if isinstance(scrut, ResultType):
            if name == "Ok":
                return [scrut.ok]
            if name == "Err":
                return [scrut.err]
            raise CompileError(f"Result has no variant {name!r}", p.line, p.col)
        if isinstance(scrut, NamedType) and scrut.name in self.sumtypes:
            variants = self.sumtypes[scrut.name]
            if name not in variants:
                raise CompileError(f"type {scrut.name} has no variant {name!r}", p.line, p.col)
            return variants[name]
        raise CompileError(f"cannot match variant {name!r} against type {scrut}", p.line, p.col)

    def _check_exhaustive(self, e, scrut, variants, bools, empty, cons) -> None:
        if isinstance(scrut, OptionType):
            need = {"Some", "None"} - variants
            if need:
                raise CompileError(f"non-exhaustive match: missing {sorted(need)}", e.line, e.col)
            return
        if isinstance(scrut, ResultType):
            need = {"Ok", "Err"} - variants
            if need:
                raise CompileError(f"non-exhaustive match: missing {sorted(need)}", e.line, e.col)
            return
        if isinstance(scrut, NamedType) and scrut.name in self.sumtypes:
            need = set(self.sumtypes[scrut.name]) - variants
            if need:
                raise CompileError(f"non-exhaustive match: missing variant(s) {sorted(need)}", e.line, e.col)
            return
        if isinstance(scrut, ListType):
            if not (empty and cons):
                raise CompileError(
                    "non-exhaustive match on List: cover both `[]` and `head :: tail`",
                    e.line, e.col)
            return
        if scrut == BOOL:
            if {True, False} - bools:
                raise CompileError("non-exhaustive match on Bool: cover both true and false", e.line, e.col)
            return
        raise CompileError(
            f"match on {scrut} needs a catch-all (`_` or a binding) arm", e.line, e.col)

    def _literal_type(self, value) -> Type:
        if isinstance(value, bool):
            return BOOL
        if isinstance(value, int):
            return INT
        if isinstance(value, float):
            return FLOAT
        if isinstance(value, str):
            return TEXT
        raise CompileError(f"unsupported literal {value!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Builtin function signatures. Polymorphic ones are checked with small ad-hoc
# rules rather than a general type system (sufficient for the standard helpers).
# ---------------------------------------------------------------------------
def _chk_print(c, e, argtypes):
    if not unify_equal(argtypes[0], TEXT):
        raise CompileError(f"print expects Text, got {argtypes[0]}", e.line, e.col)
    return UNIT


def _chk_len(c, e, argtypes):
    if not isinstance(argtypes[0], ListType):
        raise CompileError(f"len expects a List, got {argtypes[0]}", e.line, e.col)
    return INT


def _chk_get(c, e, argtypes):
    lst, idx = argtypes
    if not isinstance(lst, ListType):
        raise CompileError(f"get expects a List as its first argument, got {lst}", e.line, e.col)
    if not unify_equal(idx, INT):
        raise CompileError(f"get expects an Int index, got {idx}", e.line, e.col)
    return OptionType(lst.elem)


def _chk_push(c, e, argtypes):
    lst, item = argtypes
    if not isinstance(lst, ListType):
        raise CompileError(f"push expects a List as its first argument, got {lst}", e.line, e.col)
    if not unify_equal(lst.elem, item):
        raise CompileError(f"push expects {lst.elem} to match list element, got {item}", e.line, e.col)
    return lst


def _chk_concat(c, e, argtypes):
    a, b = argtypes
    if not isinstance(a, ListType) or not isinstance(b, ListType):
        raise CompileError(f"concat expects two Lists, got {a} and {b}", e.line, e.col)
    if not unify_equal(a.elem, b.elem):
        raise CompileError(f"concat expects matching element types, got {a} and {b}", e.line, e.col)
    return a


def _chk_int_to_text(c, e, argtypes):
    if not unify_equal(argtypes[0], INT):
        raise CompileError(f"int_to_text expects Int, got {argtypes[0]}", e.line, e.col)
    return TEXT


def _chk_float_to_text(c, e, argtypes):
    if not unify_equal(argtypes[0], FLOAT):
        raise CompileError(f"float_to_text expects Float, got {argtypes[0]}", e.line, e.col)
    return TEXT


def _chk_bool_to_text(c, e, argtypes):
    if not unify_equal(argtypes[0], BOOL):
        raise CompileError(f"bool_to_text expects Bool, got {argtypes[0]}", e.line, e.col)
    return TEXT


def _chk_text_len(c, e, argtypes):
    if not unify_equal(argtypes[0], TEXT):
        raise CompileError(f"text_len expects Text, got {argtypes[0]}", e.line, e.col)
    return INT


BUILTINS = {
    "print": {"arity": 1, "effects": {"io"}, "check": _chk_print},
    "len": {"arity": 1, "effects": set(), "check": _chk_len},
    "get": {"arity": 2, "effects": set(), "check": _chk_get},
    "push": {"arity": 2, "effects": set(), "check": _chk_push},
    "concat": {"arity": 2, "effects": set(), "check": _chk_concat},
    "int_to_text": {"arity": 1, "effects": set(), "check": _chk_int_to_text},
    "float_to_text": {"arity": 1, "effects": set(), "check": _chk_float_to_text},
    "bool_to_text": {"arity": 1, "effects": set(), "check": _chk_bool_to_text},
    "text_len": {"arity": 1, "effects": set(), "check": _chk_text_len},
}


def check_program(program: ast.Program) -> Checker:
    checker = Checker(program)
    checker.check()
    return checker
