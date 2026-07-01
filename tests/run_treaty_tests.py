"""Self-contained tests for Treaty. Run: python tests/run_treaty_tests.py

Each of the seven "prototype must demonstrate" points from the design has at
least one test here, plus core evaluation.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from treaty import (  # noqa: E402
    CompileError, Interpreter, LaunchRefused, LeaseError, ParseError, Sandbox,
    compile_source, run_source,
)
from treaty.errors import LexError  # noqa: E402
from treaty.interpreter import UNIT, VariantVal  # noqa: E402

PASSED = 0
FAILED = 0
FAILURES: list[str] = []


def ok(name):
    global PASSED
    PASSED += 1
    print(f"  ok   {name}")


def fail(name, detail):
    global FAILED
    FAILED += 1
    FAILURES.append(f"{name}: {detail}")
    print(f"  FAIL {name}: {detail}")


def expect_run(name, source, expected, sandbox=None):
    try:
        result, _ = run_source(source, sandbox=sandbox)
    except Exception as exc:  # noqa: BLE001
        fail(name, f"unexpected {type(exc).__name__}: {exc}")
        return
    if result == expected:
        ok(name)
    else:
        fail(name, f"expected {expected!r} got {result!r}")


def expect_error(name, source, error_type, run=False, sandbox=None):
    try:
        if run:
            run_source(source, sandbox=sandbox)
        else:
            compile_source(source)
    except error_type:
        ok(name)
        return
    except Exception as exc:  # noqa: BLE001
        fail(name, f"expected {error_type.__name__} but got {type(exc).__name__}: {exc}")
        return
    fail(name, f"expected {error_type.__name__} but nothing was raised")


def demo_vfs():
    return Sandbox(vfs={
        "/data/today/a.txt": "alpha",
        "/data/today/b.txt": "beta",
        "/etc/passwd": "secret",
    })


# ===========================================================================
print("== core: negotiate / grant / lease ==")

# Direct grant: claim entails grant -> Granted -> read within refinement.
DIRECT = """
policy {
  grant read over fs where path under "/data/today"
}
fn main() -> Text =
  match negotiate(claim read over fs where path under "/data/today") {
    Granted(rl)  => rl.read("/data/today/a.txt"),
    Countered(_) => "countered",
    Refused(why) => why,
  }
"""
expect_run("direct grant then read", DIRECT, "alpha", sandbox=demo_vfs())

# ---------------------------------------------------------------------------
print("== point 1: empty world ==")

expect_error(
    "no global verb (read is not a name)",
    """
    fn main() -> Text = read("/data/today/a.txt")
    """,
    CompileError,
)

expect_error(
    "method on a non-lease is rejected",
    """
    fn main() -> Text = "hello".read("/x")
    """,
    CompileError,
)

# ---------------------------------------------------------------------------
print("== point 2: refinement-typed verb (compile-time) ==")

expect_error(
    "literal path outside lease refinement is a compile error",
    """
    policy { grant read over fs where path under "/data/today" }
    fn main() -> Text =
      match negotiate(claim read over fs where path under "/data/today") {
        Granted(rl)  => rl.read("/etc/passwd"),
        Countered(_) => "c",
        Refused(w)   => w,
      }
    """,
    CompileError,
)

expect_error(
    "verb the lease does not grant is a compile error",
    """
    policy { grant read over fs where path under "/data" }
    fn main() -> Unit =
      match negotiate(claim read over fs where path under "/data") {
        Granted(rl)  => rl.write("/data/x", "y"),
        Countered(_) => rl_none(),
        Refused(_)   => rl_none(),
      }
    fn rl_none() -> Unit = write_nothing()
    fn write_nothing() -> Unit = report()
    fn report() -> Unit = loopy()
    fn loopy() -> Unit = report()
    """,
    CompileError,
)

# ---------------------------------------------------------------------------
print("== point 3: typed counter-offer drives a fixpoint ==")

COUNTER = """
policy {
  grant read over fs where path under "/data/today"
}
fn main() -> Text =
  match negotiate(claim read over fs where path under "/data") {
    Refused(why)        => why,
    Granted(_)          => "granted-unexpectedly",
    Countered(narrower) =>
      match negotiate(narrower) {
        Granted(rl)  => rl.read("/data/today/b.txt"),
        Countered(_) => "still-countered",
        Refused(w)   => w,
      },
  }
"""
expect_run("broad claim countered, re-presented, then granted", COUNTER, "beta", sandbox=demo_vfs())

# ---------------------------------------------------------------------------
print("== point 4: no lease escape / budget revocation ==")

expect_error(
    "a lease may not escape its region (returned from arm)",
    """
    policy { grant read over fs where path under "/data" }
    fn main() -> Unit =
      region r {
        match negotiate(claim read over fs where path under "/data") {
          Granted(rl)  => rl,
          Countered(_) => nope(),
          Refused(_)   => nope(),
        }
      }
    fn nope() -> Unit = nope()
    """,
    CompileError,
)

BUDGET = """
policy {
  grant send over net where host eq "h.internal" and total_le 6
}
fn main() -> Unit =
  region session {
    match negotiate(claim send over net where host eq "h.internal" and total_le 6) {
      Granted(sl)  => sl.send("h.internal", "toolongpayload"),
      Countered(_) => boom(),
      Refused(_)   => boom(),
    }
  }
fn boom() -> Unit = boom()
"""
expect_error("runtime budget/bytes exhaustion is a LeaseError", BUDGET, LeaseError,
             run=True, sandbox=demo_vfs())

# ---------------------------------------------------------------------------
print("== point 5+6: derived manifest + co-sign before run ==")

# Manifest is derived from the source.
_, checker = compile_source(DIRECT)
clauses = checker.manifest_clauses()
if len(clauses) == 1 and clauses[0].domain == "fs" and clauses[0].verb == "read" \
        and clauses[0].refinement.path_prefix == "/data/today":
    ok("manifest derived from source (read/fs, path /data/today)")
else:
    fail("manifest derivation", f"got {[c.render() for c in clauses]}")

# Co-sign refuses to launch a program whose manifest the policy will not grant.
NOSIGN = """
policy {
  grant read over fs where path under "/data"
}
fn main() -> Unit =
  match negotiate(claim send over net where host eq "evil.com") {
    Granted(sl)  => sl.send("evil.com", "x"),
    Countered(_) => stop(),
    Refused(_)   => stop(),
  }
fn stop() -> Unit = stop()
"""
expect_error("co-sign refuses unsatisfiable clause before running", NOSIGN, LaunchRefused,
             run=True, sandbox=demo_vfs())

# An explicit `refuse` clause also blocks launch by name.
REFUSED = """
policy {
  grant read  over fs where path under "/data"
  refuse write over fs
}
fn main() -> Unit =
  match negotiate(claim write over fs where path under "/data") {
    Granted(wl)  => wl.write("/data/x", "y"),
    Countered(_) => stop(),
    Refused(_)   => stop(),
  }
fn stop() -> Unit = stop()
"""
expect_error("explicit refuse blocks launch", REFUSED, LaunchRefused, run=True, sandbox=demo_vfs())

# ---------------------------------------------------------------------------
print("== point 7: honest bound on soundness (data-dependent widening) ==")

# The re-presented Countered claim is a runtime value -> its manifest clause
# widens to data-dependent.
_, checker = compile_source(COUNTER)
dd = [c for c in checker.manifest_clauses() if c.data_dependent]
if dd and any(c.verb == "read" and c.domain == "fs" for c in dd):
    ok("re-negotiated (countered) claim yields a data-dependent manifest clause")
else:
    fail("data-dependent widening", f"clauses: {[(c.render()) for c in checker.manifest_clauses()]}")

# ---------------------------------------------------------------------------
print("== end-to-end: the backup example ==")

BACKUP = """
policy {
  grant read over fs  where path under "/data/today"
  grant send over net where host eq "backup.internal" and total_le 100
  refuse write over fs
}
fn main() -> Result[Unit, Text] =
  region session {
    match negotiate(claim read over fs where path under "/data") {
      Refused(why)        => Err(why),
      Granted(_)          => Err("unexpected direct grant"),
      Countered(narrower) =>
        match negotiate(narrower) {
          Refused(why) => Err(why),
          Countered(_) => Err("still countered"),
          Granted(rl)  =>
            match negotiate(claim send over net where host eq "backup.internal" and total_le 100) {
              Refused(why) => Err(why),
              Countered(_) => Err("send countered"),
              Granted(sl)  => Ok(sl.send("backup.internal", rl.read("/data/today/a.txt"))),
            },
        },
    }
  }
"""
def _run_backup():
    sb = demo_vfs()
    result, interp = run_source(BACKUP, sandbox=sb)
    if result == VariantVal("Ok", (UNIT,)) and interp.sandbox.sent == [("backup.internal", "alpha")]:
        ok("backup: countered-then-granted read, budgeted send, region revocation")
    else:
        fail("backup", f"result={result!r} sent={interp.sandbox.sent!r}")
_run_backup()

# ---------------------------------------------------------------------------
print("== misc static rejections ==")

expect_error("unknown domain", 'fn main() -> Unit = { let c = claim read over disk; boom() }\nfn boom() -> Unit = boom()', CompileError)
expect_error("verb/domain mismatch in claim", 'fn main() -> Unit = { let c = claim send over fs; boom() }\nfn boom() -> Unit = boom()', CompileError)
expect_error("non-exhaustive Outcome match",
             'policy { grant read over fs }\nfn main() -> Text = match negotiate(claim read over fs) { Granted(rl) => rl.read("/x") }',
             CompileError)
expect_error("lease as function parameter is rejected",
             "fn use(l: Lease) -> Unit = use(l)", CompileError)
expect_error("parse error", "fn main() -> = 1", ParseError)
expect_error("lex error", "fn main() -> Int = 1 @ 2", LexError)

# ===========================================================================
print()
print(f"{PASSED} passed, {FAILED} failed")
if FAILED:
    print("\nFailures:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
sys.exit(0)
