"""Interpreter for Treaty (the phase boundary + PHASE 2).

Before any effect runs, `cosign` checks the statically-derived manifest against
the policy: a clause the environment will not grant makes the program fail to
launch, by name, with nothing executed. Then the body runs on an ordinary
tree-walker whose only unusual jobs are:

  * `negotiate`, the sole boundary primitive, returning Granted/Countered/Refused
  * lease method dispatch, which re-checks the refinement against the *actual*
    arguments, meters the affine `total_le` budget, and refuses a revoked lease.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ast
from .errors import LaunchRefused, LeaseError, PanicError
from .refinements import Refinement
from .world import VERBS


# ---------------------------------------------------------------------------
# Runtime values
# ---------------------------------------------------------------------------
class Unit:
    _i = None

    def __new__(cls):
        if cls._i is None:
            cls._i = super().__new__(cls)
        return cls._i

    def __repr__(self):
        return "unit"


UNIT = Unit()


@dataclass(frozen=True)
class ClaimVal:
    domain: str
    verb: str
    refinement: Refinement

    def __repr__(self):
        return f"claim {self.verb} over {self.domain} where {self.refinement.render()}"


@dataclass
class LeaseVal:
    domain: str
    verb: str
    refinement: Refinement
    budget: int | None
    region: str | None
    revoked: bool = False

    def __repr__(self):
        return f"<lease {self.verb} over {self.domain}>"


@dataclass
class VariantVal:
    tag: str
    fields: tuple

    def __repr__(self):
        if not self.fields:
            return self.tag
        return f"{self.tag}({', '.join(map(_show, self.fields))})"

    def __eq__(self, other):
        return isinstance(other, VariantVal) and self.tag == other.tag and self.fields == other.fields


def _show(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    return repr(v)


@dataclass
class RuntimeGrant:
    refuse: bool
    domain: str
    verb: str
    refinement: Refinement


def _refinement_from_preds(preds: list[ast.Pred]) -> Refinement:
    path = host = bytes_le = total_le = None
    for p in preds:
        if p.kind == "path":
            path = p.value
        elif p.kind == "host":
            host = p.value
        elif p.kind == "bytes_le":
            bytes_le = p.value
        elif p.kind == "total_le":
            total_le = p.value
    return Refinement(path, host, bytes_le, total_le)


# ---------------------------------------------------------------------------
# The sandbox environment (the counterparty's actual resources)
# ---------------------------------------------------------------------------
@dataclass
class Sandbox:
    vfs: dict = field(default_factory=dict)      # path -> Text contents
    sent: list = field(default_factory=list)     # (host, data) log of net.send
    clock: int = 1000
    rand_state: int = 12345

    def next_rand(self) -> int:
        self.rand_state = (self.rand_state * 1103515245 + 12345) % (2 ** 31)
        return self.rand_state


class Interpreter:
    def __init__(self, program: ast.Program, sandbox: Sandbox | None = None):
        self.functions = {fn.name: fn for fn in program.fns}
        self.grants = self._build_grants(program.policy)
        self.sandbox = sandbox if sandbox is not None else Sandbox()
        self.region_stack: list[list[LeaseVal]] = []

    def _build_grants(self, policy) -> list[RuntimeGrant]:
        if policy is None:
            return []
        return [RuntimeGrant(g.refuse, g.domain, g.verb, _refinement_from_preds(g.preds))
                for g in policy.grants]

    # -- phase boundary: co-sign the manifest -------------------------------
    def cosign(self, manifest) -> None:
        for clause in manifest:
            matching = [g for g in self.grants if g.domain == clause.domain and g.verb == clause.verb]
            if any(g.refuse for g in matching) or not any(not g.refuse for g in matching):
                raise LaunchRefused(
                    f"environment refuses to co-sign the treaty; unsatisfiable clause: "
                    f"{clause.render()}")

    # -- run ----------------------------------------------------------------
    def run(self, entry: str = "main"):
        if entry not in self.functions:
            raise PanicError(f"no function named {entry!r} to run")
        fn = self.functions[entry]
        if fn.params:
            raise PanicError(f"entry function {entry!r} must take no arguments")
        return self.eval(fn.body, {})

    # -- negotiation --------------------------------------------------------
    def negotiate(self, claim: ClaimVal):
        matching = [g for g in self.grants if g.domain == claim.domain and g.verb == claim.verb]
        if any(g.refuse for g in matching):
            return VariantVal("Refused", (f"policy refuses {claim.verb} over {claim.domain}",))
        offers = [g for g in matching if not g.refuse]
        if not offers:
            return VariantVal("Refused", (f"no grant for {claim.verb} over {claim.domain}",))
        g = offers[0]
        c, gr = claim.refinement, g.refinement
        if not c.compatible(gr):
            return VariantVal("Refused", (
                f"{claim.verb} over {claim.domain}: request conflicts with policy "
                f"({c.render()} vs {gr.render()})",))
        if c.entails(gr):
            lease = LeaseVal(claim.domain, claim.verb, c, budget=c.total_le,
                             region=(None if not self.region_stack else "region"))
            if self.region_stack:
                self.region_stack[-1].append(lease)
            return VariantVal("Granted", (lease,))
        narrower = c.meet(gr)
        return VariantVal("Countered", (ClaimVal(claim.domain, claim.verb, narrower),))

    # -- lease method dispatch ----------------------------------------------
    def do_method(self, lease: LeaseVal, verb: str, args: list, node):
        if not isinstance(lease, LeaseVal):  # pragma: no cover - checker prevents
            raise PanicError("method call on a non-lease value", node.line, node.col)
        if lease.revoked:
            raise LeaseError(f"lease for {verb} over {lease.domain} was revoked at its region's end",
                             node.line, node.col)
        spec = VERBS[verb]
        r = lease.refinement
        if spec["path_arg"] is not None and r.path_prefix is not None:
            path = args[spec["path_arg"]]
            if not path.startswith(r.path_prefix):
                raise LeaseError(
                    f'refinement violation at runtime: path "{path}" is not under "{r.path_prefix}"',
                    node.line, node.col)
        if spec["host_arg"] is not None and r.host is not None:
            host = args[spec["host_arg"]]
            if host != r.host:
                raise LeaseError(
                    f'refinement violation at runtime: host "{host}" is not "{r.host}"',
                    node.line, node.col)
        if spec["data_arg"] is not None:
            n = len(args[spec["data_arg"]])
            if r.bytes_le is not None and n > r.bytes_le:
                raise LeaseError(
                    f"refinement violation at runtime: {n} bytes exceeds bytes_le {r.bytes_le}",
                    node.line, node.col)
            if lease.budget is not None:
                if n > lease.budget:
                    raise LeaseError(
                        f"lease budget exhausted: this call needs {n} bytes but only "
                        f"{lease.budget} remain under total_le",
                        node.line, node.col)
                lease.budget -= n
        return self._perform(verb, args)

    def _perform(self, verb: str, args: list):
        sb = self.sandbox
        if verb == "read":
            return sb.vfs.get(args[0], "")
        if verb == "write":
            sb.vfs[args[0]] = args[1]
            return UNIT
        if verb == "list":
            prefix = args[0]
            return sorted(p for p in sb.vfs if p.startswith(prefix))
        if verb == "send":
            sb.sent.append((args[0], args[1]))
            return UNIT
        if verb == "now":
            sb.clock += 1
            return sb.clock
        if verb == "gen":
            return sb.next_rand()
        raise PanicError(f"unknown verb {verb!r}")  # pragma: no cover

    # -- evaluation ---------------------------------------------------------
    def eval(self, expr, env):
        return getattr(self, "_eval_" + type(expr).__name__)(expr, env)

    def _eval_IntLit(self, e, env):
        return e.value

    def _eval_TextLit(self, e, env):
        return e.value

    def _eval_BoolLit(self, e, env):
        return e.value

    def _eval_ListLit(self, e, env):
        return [self.eval(el, env) for el in e.elements]

    def _eval_Var(self, e, env):
        return env[e.name]

    def _eval_ClaimExpr(self, e, env):
        return ClaimVal(e.domain, e.verb, _refinement_from_preds(e.preds))

    def _eval_Negotiate(self, e, env):
        return self.negotiate(self.eval(e.claim, env))

    def _eval_MethodCall(self, e, env):
        recv = self.eval(e.receiver, env)
        args = [self.eval(a, env) for a in e.args]
        return self.do_method(recv, e.verb, args, e)

    def _eval_Call(self, e, env):
        args = [self.eval(a, env) for a in e.args]
        if e.callee == "concat":
            return args[0] + args[1]
        if e.callee == "int_to_text":
            return str(args[0])
        if e.callee == "len":
            return len(args[0])
        fn = self.functions[e.callee]
        call_env = {p.name: v for p, v in zip(fn.params, args)}
        return self.eval(fn.body, call_env)

    def _eval_Construct(self, e, env):
        return VariantVal(e.tag, tuple(self.eval(a, env) for a in e.args))

    def _eval_If(self, e, env):
        if self.eval(e.cond, env):
            return self.eval(e.then_branch, env)
        return self.eval(e.else_branch, env)

    def _eval_Block(self, e, env):
        scope = dict(env)
        for stmt in e.statements:
            if isinstance(stmt, ast.LetStmt):
                scope[stmt.name] = self.eval(stmt.value, scope)
            elif isinstance(stmt, ast.ExprStmt):
                self.eval(stmt.expr, scope)
        return self.eval(e.result, scope)

    def _eval_Region(self, e, env):
        frame: list[LeaseVal] = []
        self.region_stack.append(frame)
        try:
            result = self.eval(e.body, env)
        finally:
            self.region_stack.pop()
            for lease in frame:
                lease.revoked = True
        return result

    def _eval_Match(self, e, env):
        value = self.eval(e.scrutinee, env)
        for case in e.cases:
            bindings: dict = {}
            if self._match(case.pattern, value, bindings):
                scope = dict(env)
                scope.update(bindings)
                return self.eval(case.body, scope)
        raise PanicError("no match arm fired (internal invariant violated)", e.line, e.col)

    def _match(self, p, value, bindings) -> bool:
        if p.kind == "wildcard":
            return True
        if p.kind == "binding":
            bindings[p.name] = value
            return True
        if p.kind == "literal":
            return value == p.value and type(value) is type(p.value)
        if p.kind == "variant":
            if not isinstance(value, VariantVal) or value.tag != p.name:
                return False
            for sub, fld in zip(p.subpatterns, value.fields):
                if not self._match(sub, fld, bindings):
                    return False
            return True
        raise PanicError(f"unknown pattern kind {p.kind!r}")  # pragma: no cover
