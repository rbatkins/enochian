"""Self-contained test runner for Enochian (no external dependencies).

Run with:  python tests/run_tests.py
Exit code is non-zero if any test fails.
"""

from __future__ import annotations

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from enochian import (  # noqa: E402
    CompileError, ContractError, Interpreter, ParseError, compile_source, run_source,
)
from enochian.errors import LexError, PanicError  # noqa: E402

PASSED = 0
FAILED = 0
FAILURES: list[str] = []


def ok(name: str) -> None:
    global PASSED
    PASSED += 1
    print(f"  ok   {name}")


def fail(name: str, detail: str) -> None:
    global FAILED
    FAILED += 1
    FAILURES.append(f"{name}: {detail}")
    print(f"  FAIL {name}: {detail}")


def expect_run(name: str, source: str, expected, entry="main", args=None):
    try:
        result = run_source(source, entry=entry, args=args)
    except Exception as exc:  # noqa: BLE001
        fail(name, f"unexpected {type(exc).__name__}: {exc}")
        return
    if result == expected and type(result) is type(expected):
        ok(name)
    else:
        fail(name, f"expected {expected!r} got {result!r}")


def expect_output(name: str, source: str, expected_out: str, entry="main"):
    buf = io.StringIO()
    try:
        program, _ = compile_source(source)
        Interpreter(program, out=buf.write).run(entry)
    except Exception as exc:  # noqa: BLE001
        fail(name, f"unexpected {type(exc).__name__}: {exc}")
        return
    if buf.getvalue() == expected_out:
        ok(name)
    else:
        fail(name, f"expected output {expected_out!r} got {buf.getvalue()!r}")


def expect_error(name: str, source: str, error_type, run=False, entry="main"):
    try:
        if run:
            run_source(source, entry=entry)
        else:
            compile_source(source)
    except error_type:
        ok(name)
        return
    except Exception as exc:  # noqa: BLE001
        fail(name, f"expected {error_type.__name__} but got {type(exc).__name__}: {exc}")
        return
    fail(name, f"expected {error_type.__name__} but no error was raised")


# ===========================================================================
# 1. Core evaluation
# ===========================================================================
print("== core evaluation ==")

expect_run("int arithmetic", "fn main() -> Int = 2 + 3 * 4", 14)
expect_run("int truncating division", "fn main() -> Int = 7 / 2", 3)
expect_run("negative truncating division", "fn main() -> Int = (0 - 7) / 2", -3)
expect_run("modulo", "fn main() -> Int = 7 % 3", 1)
expect_run("float arithmetic", "fn main() -> Float = 1.5 + 2.5", 4.0)
expect_run("bool and/or", "fn main() -> Bool = true and (false or true)", True)
expect_run("not", "fn main() -> Bool = not false", True)
expect_run("comparison", "fn main() -> Bool = 3 <= 3", True)
expect_run("text concat with +", 'fn main() -> Text = "ab" + "cd"', "abcd")
expect_run("text comparison", 'fn main() -> Bool = "apple" < "banana"', True)
expect_run("precedence", "fn main() -> Bool = 1 + 2 == 3 and 2 * 2 == 4", True)

expect_run(
    "if expression",
    "fn main() -> Text = if 2 > 1 then \"yes\" else \"no\"",
    "yes",
)

expect_run(
    "let block and shadowing",
    """
    fn main() -> Int = {
        let x = 10;
        let y = x * 2;
        x + y
    }
    """,
    30,
)

expect_run(
    "mutable local with set",
    """
    fn main() -> Int = {
        let mut total = 0;
        set total = total + 5;
        set total = total + 10;
        total
    }
    """,
    15,
)

expect_run(
    "recursion (factorial)",
    """
    fn fact(n: Int) -> Int requires n >= 0 =
        if n == 0 then 1 else n * fact(n - 1)
    fn main() -> Int = fact(5)
    """,
    120,
)

# ===========================================================================
# 2. Options, Results, pattern matching
# ===========================================================================
print("== options / results / match ==")

expect_run(
    "option match Some",
    """
    fn main() -> Int = match Some(7) {
        Some(x) => x,
        None => 0,
    }
    """,
    7,
)

expect_run(
    "safe indexing returns None",
    """
    fn main() -> Int = match get([1, 2, 3], 9) {
        Some(v) => v,
        None => 0 - 1,
    }
    """,
    -1,
)

expect_run(
    "result Ok path",
    """
    fn safe_div(a: Int, b: Int) -> Result[Int, Text] =
        if b == 0 then Err("divide by zero") else Ok(a / b)
    fn main() -> Int = match safe_div(10, 2) {
        Ok(v) => v,
        Err(_) => 0 - 1,
    }
    """,
    5,
)

expect_run(
    "result Err path",
    """
    fn safe_div(a: Int, b: Int) -> Result[Int, Text] =
        if b == 0 then Err("divide by zero") else Ok(a / b)
    fn main() -> Text = match safe_div(10, 0) {
        Ok(_) => "ok",
        Err(msg) => msg,
    }
    """,
    "divide by zero",
)

expect_run(
    "list cons pattern (sum)",
    """
    fn sum(xs: List[Int]) -> Int = match xs {
        [] => 0,
        h :: t => h + sum(t),
    }
    fn main() -> Int = sum([1, 2, 3, 4])
    """,
    10,
)

expect_run(
    "nested pattern",
    """
    fn first_or_zero(xs: List[Int]) -> Int = match xs {
        [] => 0,
        h :: _ => h,
    }
    fn main() -> Int = first_or_zero([42, 1, 2])
    """,
    42,
)

# ===========================================================================
# 3. User-defined sum types and records
# ===========================================================================
print("== sum types / records ==")

expect_run(
    "sum type matching",
    """
    type Shape = Circle(Float) | Rect(Float, Float)
    fn area(s: Shape) -> Float = match s {
        Circle(r) => 3.0 * r * r,
        Rect(w, h) => w * h,
    }
    fn main() -> Float = area(Rect(2.0, 3.0))
    """,
    6.0,
)

expect_run(
    "record literal and field access",
    """
    record Point { x: Int, y: Int }
    fn main() -> Int = {
        let p = Point { x: 3, y: 4 };
        p.x + p.y
    }
    """,
    7,
)

expect_run(
    "list of records",
    """
    record User { name: Text, age: Int }
    fn oldest(a: User, b: User) -> User =
        if a.age >= b.age then a else b
    fn main() -> Text = oldest(User { name: "Ada", age: 36 }, User { name: "Al", age: 24 }).name
    """,
    "Ada",
)

# ===========================================================================
# 4. Effects and IO
# ===========================================================================
print("== effects / io ==")

expect_output(
    "print produces output",
    """
    fn main() -> Unit !io = print("hello")
    """,
    "hello\n",
)

expect_output(
    "effect propagation through call",
    """
    fn greet(name: Text) -> Unit !io = print("hi " + name)
    fn main() -> Unit !io = greet("ada")
    """,
    "hi ada\n",
)

# ===========================================================================
# 5. Static rejections (bug prevention)
# ===========================================================================
print("== static rejections ==")

expect_error("type mismatch return", "fn main() -> Int = \"text\"", CompileError)
expect_error("undefined variable", "fn main() -> Int = x", CompileError)
expect_error("undefined function call", "fn main() -> Int = foo(1)", CompileError)
expect_error("wrong arg count", "fn f(a: Int) -> Int = a\nfn main() -> Int = f(1, 2)", CompileError)
expect_error("if branch mismatch", "fn main() -> Int = if true then 1 else \"x\"", CompileError)
expect_error("add bool to int", "fn main() -> Int = 1 + true", CompileError)
expect_error("compare different types", "fn main() -> Bool = 1 == \"x\"", CompileError)

expect_error(
    "set immutable variable",
    """
    fn main() -> Int = {
        let x = 1;
        set x = 2;
        x
    }
    """,
    CompileError,
)

expect_error(
    "undeclared effect",
    """
    fn main() -> Unit = print("oops")
    """,
    CompileError,
)

expect_error(
    "non-exhaustive match (missing None)",
    """
    fn main() -> Int = match Some(1) {
        Some(x) => x,
    }
    """,
    CompileError,
)

expect_error(
    "non-exhaustive match (missing sum variant)",
    """
    type Color = Red | Green | Blue
    fn name(c: Color) -> Text = match c {
        Red => "r",
        Green => "g",
    }
    fn main() -> Text = name(Blue)
    """,
    CompileError,
)

expect_error(
    "unreachable arm after catch-all",
    """
    fn main() -> Int = match 5 {
        x => x,
        0 => 1,
    }
    """,
    CompileError,
)

expect_error(
    "impure contract rejected",
    """
    fn f(n: Int) -> Int requires print("x") == print("y") = n
    fn main() -> Int = f(1)
    """,
    CompileError,
)

expect_error(
    "missing record field",
    """
    record Point { x: Int, y: Int }
    fn main() -> Int = { let p = Point { x: 1 }; p.x }
    """,
    CompileError,
)

expect_error(
    "match on Int without catch-all",
    """
    fn main() -> Int = match 5 {
        0 => 0,
        1 => 1,
    }
    """,
    CompileError,
)

expect_error(
    "discarding a non-Unit value is rejected",
    """
    fn val() -> Int = 5
    fn main() -> Unit !io = {
        val();
        print("done")
    }
    """,
    CompileError,
)

expect_error("parse error", "fn main() -> Int = (1 + ", ParseError)
expect_error("lex error", "fn main() -> Int = 1 $ 2", LexError)

# ===========================================================================
# 5b. Ordering / scoping niceties
# ===========================================================================
print("== ordering / scoping ==")

expect_run(
    "forward reference to later-declared type",
    """
    record Named { shape: Shape }
    type Shape = Dot | Line(Int)
    fn size(n: Named) -> Int = match n.shape {
        Dot => 0,
        Line(k) => k,
    }
    fn main() -> Int = size(Named { shape: Line(9) })
    """,
    9,
)

expect_run(
    "mutually recursive functions",
    """
    fn is_even(n: Int) -> Bool = if n == 0 then true else is_odd(n - 1)
    fn is_odd(n: Int) -> Bool = if n == 0 then false else is_even(n - 1)
    fn main() -> Bool = is_even(10)
    """,
    True,
)

expect_output(
    "unit statements sequence with side effects",
    """
    fn main() -> Unit !io = {
        print("a");
        print("b");
        print("c")
    }
    """,
    "a\nb\nc\n",
)

expect_run(
    "set on outer mut from inner block",
    """
    fn main() -> Int = {
        let mut acc = 0;
        let bump = {
            set acc = acc + 100;
            acc
        };
        acc + bump
    }
    """,
    200,
)

# ===========================================================================
# 6. Runtime contract enforcement
# ===========================================================================
print("== contracts (runtime) ==")

expect_error(
    "precondition violation",
    """
    fn fact(n: Int) -> Int requires n >= 0 =
        if n == 0 then 1 else n * fact(n - 1)
    fn main() -> Int = fact(0 - 1)
    """,
    ContractError,
    run=True,
)

expect_run(
    "postcondition satisfied",
    """
    fn abs(n: Int) -> Int ensures result >= 0 =
        if n < 0 then 0 - n else n
    fn main() -> Int = abs(0 - 9)
    """,
    9,
)

expect_error(
    "postcondition violation",
    """
    fn bad_abs(n: Int) -> Int ensures result >= 0 = n
    fn main() -> Int = bad_abs(0 - 5)
    """,
    ContractError,
    run=True,
)

expect_error(
    "division by zero aborts (no UB)",
    "fn main() -> Int = 1 / 0",
    ContractError,
    run=True,
)

# ===========================================================================
# Summary
# ===========================================================================
print()
print(f"{PASSED} passed, {FAILED} failed")
if FAILED:
    print("\nFailures:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
sys.exit(0)
