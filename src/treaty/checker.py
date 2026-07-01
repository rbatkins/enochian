"""Static checker for Treaty (PHASE 1).

Beyond ordinary type checking, this pass enforces the treaty discipline:

  * EMPTY WORLD: verb names (read/write/send/...) are not callable; an effect
    verb is only reachable as a method on a lease obtained from `negotiate`.
  * REFINEMENT-TYPED VERBS: a lease method call whose *literal* argument falls
    outside the lease's granted refinement is a compile error naming the clause.
  * NO LEASE ESCAPE: a lease may not cross a function or region boundary, be
    passed as an argument, or be stored -- so "used after revoke" is
    unrepresentable rather than merely caught.
  * MANIFEST DERIVATION: every `negotiate` site is resolved to a treaty clause;
    when a claim's refinement is data-dependent, the clause widens to TOP and is
    flagged, so the derived manifest never over-claims precision.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import ast
from .errors import CompileError
from .refinements import TOP, Refinement, StaticClaim
from .world import DOMAINS, VERBS, pred_applies_to_verb


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
class Type:
    pass


@dataclass(frozen=True)
class TPrim(Type):
    name: str  # Int | Text | Bool | Unit

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class TList(Type):
    elem: Type

    def __str__(self):
        return f"List[{self.elem}]"


@dataclass(frozen=True)
class TResult(Type):
    ok: Type
    err: Type

    def __str__(self):
        return f"Result[{self.ok}, {self.err}]"


@dataclass(frozen=True)
class TUnknown(Type):
    def __str__(self):
        return "?"


@dataclass
class TClaim(Type):
    static: StaticClaim | None = None

    def __str__(self):
        return "Claim"


@dataclass
class TOutcome(Type):
    static: StaticClaim | None = None

    def __str__(self):
        return "Outcome"


@dataclass
class TLease(Type):
    static: StaticClaim | None = None

    def __str__(self):
        return "Lease"


TINT = TPrim("Int")
TTEXT = TPrim("Text")
TBOOL = TPrim("Bool")
TUNIT = TPrim("Unit")
PRIMS = {"Int": TINT, "Text": TTEXT, "Bool": TBOOL, "Unit": TUNIT}


def same_type(a: Type, b: Type) -> bool:
    if isinstance(a, TUnknown) or isinstance(b, TUnknown):
        return True
    if isinstance(a, TPrim) and isinstance(b, TPrim):
        return a.name == b.name
    if isinstance(a, TList) and isinstance(b, TList):
        return same_type(a.elem, b.elem)
    if isinstance(a, TResult) and isinstance(b, TResult):
        return same_type(a.ok, b.ok) and same_type(a.err, b.err)
    if isinstance(a, TClaim) and isinstance(b, TClaim):
        return True
    if isinstance(a, TOutcome) and isinstance(b, TOutcome):
        return True
    if isinstance(a, TLease) and isinstance(b, TLease):
        return True
    return False


def is_lease(t: Type) -> bool:
    return isinstance(t, TLease)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ManifestClause:
    domain: str
    verb: str
    refinement: Refinement
    data_dependent: bool

    def render(self) -> str:
        body = "<data-dependent>" if self.data_dependent else self.refinement.render()
        tag = "   [data-dependent]" if self.data_dependent else ""
        return f"{self.verb:<6} over {self.domain:<6} where {body}{tag}"


@dataclass
class FnSig:
    params: list[tuple[str, Type]]
    ret: Type


BUILTINS = {
    "concat": ([TTEXT, TTEXT], TTEXT),
    "int_to_text": ([TINT], TTEXT),
    "len": ([TTEXT], TINT),
}


class Checker:
    def __init__(self, program: ast.Program):
        self.program = program
        self.functions: dict[str, FnSig] = {}
        self.manifest: list[ManifestClause] = []

    # -- entry --------------------------------------------------------------
    def check(self) -> None:
        self._collect_functions()
        for fn in self.program.fns:
            self._check_fn(fn)
        self._validate_policy()

    def manifest_clauses(self) -> list[ManifestClause]:
        seen = []
        for c in self.manifest:
            if c not in seen:
                seen.append(c)
        seen.sort(key=lambda c: (c.domain, c.verb, c.refinement.render(), c.data_dependent))
        return seen

    # -- collection ---------------------------------------------------------
    def _collect_functions(self) -> None:
        for fn in self.program.fns:
            if fn.name in self.functions or fn.name in BUILTINS or fn.name in VERBS:
                raise CompileError(f"function {fn.name!r} is already defined", fn.line, fn.col)
            params = []
            seen = set()
            for p in fn.params:
                if p.name in seen:
                    raise CompileError(f"duplicate parameter {p.name!r} in {fn.name}", fn.line, fn.col)
                seen.add(p.name)
                params.append((p.name, self.resolve_type(p.type, "parameter")))
            ret = self.resolve_type(fn.return_type, "return type")
            self.functions[fn.name] = FnSig(params, ret)

    def resolve_type(self, ref: ast.TypeRef, ctx: str) -> Type:
        name = ref.name
        if name in PRIMS:
            self._expect_args(ref, 0)
            return PRIMS[name]
        if name == "List":
            self._expect_args(ref, 1)
            return TList(self.resolve_type(ref.args[0], ctx))
        if name == "Result":
            self._expect_args(ref, 2)
            return TResult(self.resolve_type(ref.args[0], ctx), self.resolve_type(ref.args[1], ctx))
        if name == "Outcome":
            self._expect_args(ref, 0)
            return TOutcome()
        if name == "Claim":
            self._expect_args(ref, 0)
            return TClaim(None)
        if name == "Lease":
            raise CompileError(
                f"`Lease` may not appear in a {ctx}: a lease cannot cross a function "
                f"or region boundary (it would outlive its negotiated scope)",
                ref.line, ref.col)
        raise CompileError(f"unknown type {name!r}", ref.line, ref.col)

    def _expect_args(self, ref, n):
        if len(ref.args) != n:
            raise CompileError(f"type {ref.name!r} expects {n} argument(s), got {len(ref.args)}", ref.line, ref.col)

    # -- function body ------------------------------------------------------
    def _check_fn(self, fn: ast.FnDecl) -> None:
        sig = self.functions[fn.name]
        env: dict[str, Type] = {n: t for n, t in sig.params}
        body_t = self.infer(fn.body, env, sig.ret)
        self._forbid_lease(body_t, fn.body, f"returned from function {fn.name!r}")
        if not same_type(body_t, sig.ret):
            raise CompileError(
                f"function {fn.name!r} declares return type {sig.ret} but body has type {body_t}",
                fn.line, fn.col)

    def _forbid_lease(self, t: Type, node, ctx: str) -> None:
        if is_lease(t):
            raise CompileError(f"a lease may not be {ctx}; it cannot escape its region",
                               getattr(node, "line", 0), getattr(node, "col", 0))

    # -- inference ----------------------------------------------------------
    def infer(self, expr, env, expected=None) -> Type:
        return getattr(self, "_infer_" + type(expr).__name__)(expr, env, expected)

    def _infer_IntLit(self, e, env, expected):
        return TINT

    def _infer_TextLit(self, e, env, expected):
        return TTEXT

    def _infer_BoolLit(self, e, env, expected):
        return TBOOL

    def _infer_Var(self, e, env, expected):
        if e.name not in env:
            raise CompileError(f"undefined variable {e.name!r}", e.line, e.col)
        return env[e.name]

    def _infer_ListLit(self, e, env, expected):
        elem_exp = expected.elem if isinstance(expected, TList) else None
        if not e.elements:
            return expected if isinstance(expected, TList) else TList(TUnknown())
        first = self.infer(e.elements[0], env, elem_exp)
        self._forbid_lease(first, e, "stored in a list")
        for el in e.elements[1:]:
            t = self.infer(el, env, first)
            if not same_type(t, first):
                raise CompileError(f"list elements must share a type: {first} vs {t}", el.line, el.col)
        return TList(first)

    def _infer_ClaimExpr(self, e, env, expected):
        sc = self._static_claim_of(e, env)
        return TClaim(sc)

    def _infer_Negotiate(self, e, env, expected):
        sc = self._static_claim_of(e.claim, env)
        if sc is None:
            raise CompileError(
                "cannot determine this claim's domain/verb statically; `negotiate` "
                "requires a claim whose power is known at compile time",
                e.line, e.col)
        self.manifest.append(ManifestClause(sc.domain, sc.verb, sc.refinement, sc.data_dependent))
        return TOutcome(sc)

    def _infer_MethodCall(self, e, env, expected):
        recv_t = self.infer(e.receiver, env)
        if not isinstance(recv_t, TLease):
            raise CompileError(
                f"the world is empty: {e.verb!r} can only be invoked on a lease obtained "
                f"from `negotiate`, but the receiver has type {recv_t}",
                e.line, e.col)
        if e.verb not in VERBS:
            raise CompileError(f"unknown verb {e.verb!r}", e.line, e.col)
        sc = recv_t.static
        if sc is not None and e.verb != sc.verb:
            raise CompileError(
                f"this lease grants {sc.verb!r} over {sc.domain}, not {e.verb!r}",
                e.line, e.col)
        spec = VERBS[e.verb]
        if len(e.args) != len(spec["params"]):
            raise CompileError(
                f"verb {e.verb!r} expects {len(spec['params'])} argument(s), got {len(e.args)}",
                e.line, e.col)
        arg_types = []
        for arg, (pname, ptype_name) in zip(e.args, spec["params"]):
            at = self.infer(arg, env, PRIMS[ptype_name])
            self._forbid_lease(at, arg, "passed as an argument")
            if not same_type(at, PRIMS[ptype_name]):
                raise CompileError(f"verb {e.verb!r} argument {pname!r} expects {ptype_name}, got {at}", arg.line, arg.col)
            arg_types.append(at)
        # Static refinement checks against literal arguments.
        if sc is not None and not sc.data_dependent:
            self._static_refine_check(e, sc, spec)
        ret_name = spec["ret"]
        if ret_name == "List[Text]":
            return TList(TTEXT)
        return PRIMS[ret_name]

    def _static_refine_check(self, e, sc: StaticClaim, spec) -> None:
        r = sc.refinement
        if spec["path_arg"] is not None and r.path_prefix is not None:
            arg = e.args[spec["path_arg"]]
            if isinstance(arg, ast.TextLit) and not arg.value.startswith(r.path_prefix):
                raise CompileError(
                    f'refinement violation: this lease permits only `path under "{r.path_prefix}"`, '
                    f'but the call uses "{arg.value}"',
                    arg.line, arg.col)
        if spec["host_arg"] is not None and r.host is not None:
            arg = e.args[spec["host_arg"]]
            if isinstance(arg, ast.TextLit) and arg.value != r.host:
                raise CompileError(
                    f'refinement violation: this lease permits only `host eq "{r.host}"`, '
                    f'but the call uses "{arg.value}"',
                    arg.line, arg.col)
        if spec["data_arg"] is not None and r.bytes_le is not None:
            arg = e.args[spec["data_arg"]]
            if isinstance(arg, ast.TextLit) and len(arg.value) > r.bytes_le:
                raise CompileError(
                    f"refinement violation: this lease permits only `bytes_le {r.bytes_le}`, "
                    f"but the call passes {len(arg.value)} bytes",
                    arg.line, arg.col)

    def _infer_Call(self, e, env, expected):
        if e.callee in VERBS:
            raise CompileError(
                f"the world is empty: there is no global {e.callee!r}. Obtain a lease with "
                f"`negotiate(claim {e.callee} over ...)` and call `lease.{e.callee}(...)`",
                e.line, e.col)
        if e.callee in BUILTINS:
            params, ret = BUILTINS[e.callee]
            if len(e.args) != len(params):
                raise CompileError(f"{e.callee!r} expects {len(params)} argument(s), got {len(e.args)}", e.line, e.col)
            for arg, pt in zip(e.args, params):
                at = self.infer(arg, env, pt)
                if not same_type(at, pt):
                    raise CompileError(f"{e.callee!r} expects {pt}, got {at}", arg.line, arg.col)
            return ret
        sig = self.functions.get(e.callee)
        if sig is None:
            raise CompileError(f"call to undefined function {e.callee!r}", e.line, e.col)
        if len(e.args) != len(sig.params):
            raise CompileError(
                f"function {e.callee!r} expects {len(sig.params)} argument(s), got {len(e.args)}", e.line, e.col)
        for arg, (pname, ptype) in zip(e.args, sig.params):
            at = self.infer(arg, env, ptype)
            self._forbid_lease(at, arg, "passed as an argument")
            if not same_type(at, ptype):
                raise CompileError(f"argument {pname!r} of {e.callee!r} expects {ptype}, got {at}", arg.line, arg.col)
        return sig.ret

    def _infer_Construct(self, e, env, expected):
        tag = e.tag
        if tag == "Ok":
            self._arity(e, 1)
            ok = self.infer(e.args[0], env, expected.ok if isinstance(expected, TResult) else None)
            self._forbid_lease(ok, e, "stored in a Result")
            err = expected.err if isinstance(expected, TResult) else TUnknown()
            return TResult(ok, err)
        if tag == "Err":
            self._arity(e, 1)
            err = self.infer(e.args[0], env, expected.err if isinstance(expected, TResult) else None)
            self._forbid_lease(err, e, "stored in a Result")
            ok = expected.ok if isinstance(expected, TResult) else TUnknown()
            return TResult(ok, err)
        raise CompileError(
            f"unknown constructor {tag!r} (Granted/Countered/Refused are produced only by `negotiate`)",
            e.line, e.col)

    def _arity(self, e, n):
        if len(e.args) != n:
            raise CompileError(f"{e.tag!r} expects {n} argument(s), got {len(e.args)}", e.line, e.col)

    def _infer_If(self, e, env, expected):
        ct = self.infer(e.cond, env, TBOOL)
        if not same_type(ct, TBOOL):
            raise CompileError(f"`if` condition must be Bool, got {ct}", e.line, e.col)
        tt = self.infer(e.then_branch, env, expected)
        et = self.infer(e.else_branch, env, expected if expected is not None else tt)
        self._forbid_lease(tt, e, "produced by an `if`")
        if not same_type(tt, et):
            raise CompileError(f"`if` branches differ: {tt} vs {et}", e.line, e.col)
        return tt if not isinstance(tt, TUnknown) else et

    def _infer_Block(self, e, env, expected):
        scope = dict(env)
        for stmt in e.statements:
            if isinstance(stmt, ast.LetStmt):
                scope[stmt.name] = self.infer(stmt.value, scope)
            elif isinstance(stmt, ast.ExprStmt):
                st = self.infer(stmt.expr, scope, TUNIT)
                if not same_type(st, TUNIT):
                    raise CompileError(
                        f"a discarded statement must have type Unit, but this is {st}",
                        stmt.line, stmt.col)
        return self.infer(e.result, scope, expected)

    def _infer_Region(self, e, env, expected):
        # Leases negotiated inside the region live only here. The region's
        # result may not be a lease -- that would let it escape.
        t = self.infer(e.body, env, expected)
        if is_lease(t):
            raise CompileError(
                f"a lease may not escape region {e.name!r}; it is revoked at the region's end",
                e.line, e.col)
        return t

    def _infer_Match(self, e, env, expected):
        scrut = self.infer(e.scrutinee, env)
        result_t = expected
        seen_catch_all = False
        covered = set()
        for case in e.cases:
            if seen_catch_all:
                raise CompileError("unreachable match arm after a catch-all", case.pattern.line, case.pattern.col)
            bindings: dict[str, Type] = {}
            self._check_pattern(case.pattern, scrut, bindings)
            p = case.pattern
            if p.kind in ("wildcard", "binding"):
                seen_catch_all = True
            elif p.kind == "variant":
                covered.add(p.name)
            elif p.kind == "literal" and isinstance(p.value, bool):
                covered.add(p.value)
            case_env = dict(env)
            case_env.update(bindings)
            bt = self.infer(case.body, case_env, result_t)
            self._forbid_lease(bt, case.body, "produced by a match arm")
            if result_t is None or isinstance(result_t, TUnknown):
                result_t = bt
            elif not same_type(bt, result_t):
                raise CompileError(f"match arms differ: {result_t} vs {bt}", case.pattern.line, case.pattern.col)
        if not seen_catch_all:
            self._check_exhaustive(e, scrut, covered)
        return result_t

    def _check_pattern(self, p, scrut, bindings) -> None:
        if p.kind == "wildcard":
            return
        if p.kind == "binding":
            bindings[p.name] = scrut
            return
        if p.kind == "literal":
            lt = self._lit_type(p.value)
            if not same_type(lt, scrut):
                raise CompileError(f"literal pattern of type {lt} cannot match {scrut}", p.line, p.col)
            return
        if p.kind == "variant":
            arg_types = self._variant_arg_types(p.name, scrut, p)
            if len(p.subpatterns) != len(arg_types):
                raise CompileError(
                    f"variant {p.name!r} expects {len(arg_types)} sub-pattern(s), got {len(p.subpatterns)}",
                    p.line, p.col)
            for sub, at in zip(p.subpatterns, arg_types):
                self._check_pattern(sub, at, bindings)
            return
        raise CompileError(f"unknown pattern kind {p.kind!r}", p.line, p.col)  # pragma: no cover

    def _variant_arg_types(self, name, scrut, p) -> list[Type]:
        if isinstance(scrut, TOutcome):
            sc = scrut.static
            if name == "Granted":
                return [TLease(sc)]
            if name == "Countered":
                # A countered claim is a runtime value: same power, refinement TOP.
                cc = StaticClaim(sc.domain, sc.verb, TOP, data_dependent=True) if sc else None
                return [TClaim(cc)]
            if name == "Refused":
                return [TTEXT]
            raise CompileError(f"Outcome has no variant {name!r}", p.line, p.col)
        if isinstance(scrut, TResult):
            if name == "Ok":
                return [scrut.ok]
            if name == "Err":
                return [scrut.err]
            raise CompileError(f"Result has no variant {name!r}", p.line, p.col)
        raise CompileError(f"cannot match variant {name!r} against {scrut}", p.line, p.col)

    def _check_exhaustive(self, e, scrut, covered) -> None:
        if isinstance(scrut, TOutcome):
            need = {"Granted", "Countered", "Refused"} - covered
            if need:
                raise CompileError(f"non-exhaustive match on Outcome: missing {sorted(need)}", e.line, e.col)
            return
        if isinstance(scrut, TResult):
            need = {"Ok", "Err"} - covered
            if need:
                raise CompileError(f"non-exhaustive match on Result: missing {sorted(need)}", e.line, e.col)
            return
        if scrut == TBOOL:
            if {True, False} - covered:
                raise CompileError("non-exhaustive match on Bool", e.line, e.col)
            return
        raise CompileError(f"match on {scrut} needs a catch-all (`_` or a binding) arm", e.line, e.col)

    def _lit_type(self, value):
        if isinstance(value, bool):
            return TBOOL
        if isinstance(value, int):
            return TINT
        if isinstance(value, str):
            return TTEXT
        raise CompileError(f"unsupported literal {value!r}")  # pragma: no cover

    # -- static claim resolution -------------------------------------------
    def _static_claim_of(self, expr, env) -> StaticClaim | None:
        if isinstance(expr, ast.ClaimExpr):
            return self._build_static_claim(expr)
        if isinstance(expr, ast.Var):
            t = env.get(expr.name)
            if isinstance(t, TClaim):
                return t.static
            return None
        return None

    def _build_static_claim(self, e: ast.ClaimExpr) -> StaticClaim:
        if e.domain not in DOMAINS:
            raise CompileError(f"unknown domain {e.domain!r}", e.line, e.col)
        if e.verb not in VERBS:
            raise CompileError(f"unknown verb {e.verb!r}", e.line, e.col)
        if VERBS[e.verb]["domain"] != e.domain:
            raise CompileError(
                f"verb {e.verb!r} belongs to domain {VERBS[e.verb]['domain']!r}, not {e.domain!r}",
                e.line, e.col)
        r = self._refinement_from_preds(e.preds, e.verb)
        return StaticClaim(e.domain, e.verb, r, data_dependent=False)

    def _refinement_from_preds(self, preds: list[ast.Pred], verb: str) -> Refinement:
        path = host = bytes_le = total_le = None
        for pred in preds:
            if not pred_applies_to_verb(pred.kind, verb):
                raise CompileError(
                    f"refinement {pred.kind!r} does not apply to verb {verb!r}", pred.line, pred.col)
            if pred.kind == "path":
                path = pred.value
            elif pred.kind == "host":
                host = pred.value
            elif pred.kind == "bytes_le":
                bytes_le = pred.value
            elif pred.kind == "total_le":
                total_le = pred.value
        return Refinement(path, host, bytes_le, total_le)

    # -- policy validation --------------------------------------------------
    def _validate_policy(self) -> None:
        if self.program.policy is None:
            return
        for g in self.program.policy.grants:
            if g.domain not in DOMAINS:
                raise CompileError(f"unknown domain {g.domain!r} in policy", g.line, g.col)
            if g.verb not in VERBS:
                raise CompileError(f"unknown verb {g.verb!r} in policy", g.line, g.col)
            if VERBS[g.verb]["domain"] != g.domain:
                raise CompileError(
                    f"verb {g.verb!r} belongs to domain {VERBS[g.verb]['domain']!r}, not {g.domain!r}",
                    g.line, g.col)
            self._refinement_from_preds(g.preds, g.verb)  # validates applicability


def check_program(program: ast.Program) -> Checker:
    checker = Checker(program)
    checker.check()
    return checker
