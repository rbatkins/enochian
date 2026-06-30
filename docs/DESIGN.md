# Enochian — Design from First Principles

This document explains *why* Enochian is the way it is. Each decision is traced
back to a specific, well-documented cause of bugs or friction, and to the three
goals that motivated the language:

1. **Authored by AI** — a model that can read checker feedback and regenerate.
2. **Efficient** — cheap to generate, cheap to read, cheap to verify.
3. **Minimal bugs** — make the largest, costliest bug classes impossible.

---

## 0. What "first principles" means here (and what it does not)

A fair objection: *the reference implementation is written in Python and this
document is in English — how is that "first principles"?*

Two distinctions resolve it.

**Host language ≠ language design.** Every language is implemented in another
language: CPython is written in C, Rust bootstrapped from OCaml, TypeScript's
compiler is written in TypeScript. The host is scaffolding that makes a design
executable; it does not define the design's semantics. Enochian's Python
toolchain could be replaced by a Rust or C one with no change to how Enochian
programs behave. English, likewise, is the medium this rationale is written in —
not a source the grammar was copied from.

**Deriving from a goal ≠ inventing from a vacuum.** "First principles" here does
not claim the *ideas* are novel — `Option`/`Result`, exhaustiveness, contracts,
and effect tracking all exist in prior languages (ML, Haskell, Rust, Eiffel,
Koka). It claims the *justification* runs `goal → cause-of-bug → feature`, rather
than `existing language → tweak`. Section 1 is that derivation.

**Proof the design is not inherited from the host.** The clearest evidence is
where Enochian *overrides* Python's semantics precisely because they are
bug-prone:

| Python (host) behavior | Enochian decision |
|---|---|
| `1 == "x"` evaluates to `False` | compile error: cannot compare `Int` with `Text` |
| truthiness: `if []:` is valid | `if` requires a real `Bool` |
| `1 / 0` raises a catchable exception | aborts as a non-recoverable `ContractError` |
| `/` is float division, `//` floors | `Int` `/` truncates toward zero, deterministically |
| `None`, dynamic typing, free mutation | no null; static checking; immutable by default |

Where the host *was* kept (Enochian `Int` is arbitrary-precision, like Python's
`int`, eliminating overflow UB), it was a deliberate choice aligned with the
goal — not an inheritance.

---

## 1. The derivation: bug cause → design response

Software's most expensive defects are not exotic. They cluster. Enochian targets
the clusters directly.

### 1.1 Null references → there is no null

Tony Hoare called null his "billion-dollar mistake." Null-dereference defects
remain among the most common crashes in every null-bearing language. The root
cause: a type like `User` silently also means "or nothing," and the compiler
lets you use the "nothing" as if it were a `User`.

**Response:** Enochian has no null. A value that may be absent has type
`Option[T]`, with variants `Some(T)` and `None`. You cannot reach the inner
value without a `match`, and the `match` must handle `None`. The "nothing" case
is a value the type system forces you to confront.

```
fn at(xs: List[Int], i: Int) -> Text = match get(xs, i) {
    Some(v) => int_to_text(v),
    None    => "<out of range>",     # cannot be omitted
}
```

### 1.2 Exceptions for ordinary failure → failure is a value

Thrown exceptions are invisible control flow: nothing in `parse(s: Text) -> Int`
tells you it can fail, and nothing forces the caller to handle it. Errors get
swallowed, or crash three call-frames away from their cause.

**Response:** ordinary, expected failure is modelled with `Result[T, E]`. Both
outcomes are in the signature, and the caller must `match` both. Enochian has no
`throw`/`catch` for recoverable errors at all.

```
fn withdraw(acct: Account, amount: Int) -> Result[Account, Text] = ...
# Caller sees Result in the type and cannot ignore the Err branch.
```

This also draws the crucial line between *expected failure* (a value) and a
*programmer bug* (§1.7) — two things most languages conflate under "exception."

### 1.3 Implicit coercion → static types, no coercion

`"5" + 3`, `if (x)` on a non-boolean, `0 == ""` — implicit conversions produce
plausible-looking wrong answers that survive testing.

**Response:** Enochian is statically typed with no implicit coercion. `+`
requires two `Int`, two `Float`, or two `Text`. `if`/`and`/`or`/`not` require
`Bool`. `==` requires both sides to have the same type — `1 == "x"` is a compile
error, not `false`. Conversions are explicit (`int_to_text`).

### 1.4 Hidden side effects → effects in the signature

In most languages any function can perform I/O, mutate globals, or read the
clock, with no signal in its type. This makes code hard to reason about, test,
and parallelize, and it hides the difference between pure and impure code.

**Response:** effects are part of the signature. A function that performs I/O
declares `!io`. The checker computes the effects a body actually performs (via
the builtins and functions it calls) and rejects any that are not declared.
Purity is the default and is *verified*, not assumed.

```
fn greet(name: Text) -> Unit !io = print("hi " + name)   # !io required
fn double(n: Int) -> Int = n * 2                          # pure, provably
```

Contracts (§1.7) must be pure, so they can never themselves change behavior.

### 1.5 Forgotten cases → exhaustiveness everywhere

A `switch` missing a case, or not updated when a new enum variant is added, is a
classic silent bug. Default-case fall-throughs hide it further.

**Response:** every `match` must be exhaustive. The checker knows the full set of
variants for sum types, `Option`, `Result`, `Bool`, and lists (`[]` and
`h :: t`), and rejects any match that omits one — unless you add an explicit
catch-all. It also rejects unreachable arms after a catch-all. Adding a variant
to a type turns every incomplete match into a compile error: the checker hands
you a to-do list instead of letting a case silently fall through.

### 1.6 Aliasing and spooky mutation → immutable by default

Shared mutable state is the source of aliasing bugs and data races. When any
reference can mutate any value at any time, local reasoning collapses.

**Response:** bindings are immutable unless declared `mut`, and mutation happens
only through an explicit `set`. Records are immutable values; "updating" one
produces a new record. Mutation is visible and local; there is no hidden
aliasing channel.

```
let x = 1;        # immutable
let mut y = 0;    # opt in to mutability
set y = y + x;    # the only way to change y, and it is visible
```

### 1.7 Conflating bugs with failures → contracts

Many "errors" are not recoverable conditions; they are *the program being
wrong*: a negative argument to `factorial`, an index that should always be in
range. Treating these like ordinary failures (returning `Result` everywhere)
adds noise; treating them like exceptions makes them catchable and easy to
ignore.

**Response:** `requires` (preconditions) and `ensures` (postconditions) state
intent as pure boolean expressions. `ensures` may refer to `result`. They are
checked at runtime; a violation raises a `ContractError` that is **not catchable
from Enochian code** — it aborts loudly, because it means the program has a bug.
This cleanly separates the two categories §1.2 began.

```
fn fact(n: Int) -> Int
    requires n >= 0       # caller's obligation
    ensures result >= 1 = # function's guarantee
    if n == 0 then 1 else n * fact(n - 1)
```

### 1.8 Undefined behavior → totality and determinism

"Undefined behavior" and platform-dependent results are a category of bug that
cannot even be reproduced reliably.

**Response:** Enochian operations are total and deterministic. Division and
modulo by zero abort with a clear `ContractError` rather than crashing or
producing garbage. Integer division truncates toward zero on every platform.
List access is `get(...) -> Option[T]`, so there is no out-of-bounds crash.
Integers are arbitrary precision, so there is no silent overflow.

### 1.9 "More than one way to do it" → one canonical form

When a language offers five syntaxes for the same thing, generated code is
inconsistent, reviews are noisier, and an AI author wastes capacity choosing
between equivalent forms. Variance is itself a defect vector.

**Response:** Enochian is intentionally minimal and uniform. One comment syntax.
One loop mechanism (recursion). No optional parentheses or semicolons "for
style." Statements in a block are `;`-terminated; the final expression is the
result. A single naming law — types and variants are `Uppercase`, functions and
variables are `lowercase` — removes parsing ambiguity *and* enforces a uniform
look. The grammar fits on one page (see `SPEC.md`).

### 1.10 Non-locality → everything is in the signature

To understand a function you should not need to read the whole program. When
types are inferred globally, effects are invisible, and contracts live in
external docs, understanding requires unbounded context — bad for a reviewer and
worse for a model with a finite window.

**Response:** a function's signature is complete. Parameter and return types are
always written (never inferred across function boundaries), effects are listed,
and contracts are attached. The body of a function can be understood from its
signature plus the signatures of what it calls — nothing more.

---

## 2. Why these choices serve an *AI* author specifically

- **Fast, local feedback loops.** Almost every mistake is a `CompileError` with
  a line, a column, and a precise message ("function `f` performs effect `io`
  that is not declared"). That is exactly the signal a model needs to regenerate
  a correct version — far more useful than a stack trace after a crash.
- **Low generation variance.** One canonical form means the "distribution" of
  correct programs is narrow. Two correct solutions to the same problem look
  almost identical, which makes generation more reliable and review trivial.
- **Specifications are machine-checkable.** Contracts let an author state intent
  in a form the runtime checks, so "did I implement what I meant?" has a
  mechanical answer.
- **The type checker is a proof assistant.** Exhaustiveness, effects, and
  no-null mean that a program that compiles has already had whole categories of
  bug ruled out — before any test runs.

---

## 3. Efficiency

"Efficiency" here is primarily *efficiency of authorship and verification*, the
dominant cost when the author is a model:

- Minimal syntax → fewer tokens to emit and fewer ways to get them wrong.
- Static guarantees → fewer test-debug-regenerate cycles.
- Uniform structure → cheaper diffs and reviews.

Runtime efficiency is not the focus of this reference interpreter, but the design
is friendly to it: immutability and explicit effects enable aggressive
optimization and parallelization, and the absence of null/exceptions removes
pervasive runtime checks. A compiling backend is future work (§4).

---

## 4. Roadmap

The current implementation is a complete, executable definition of the language
core. Natural next steps, roughly in order:

1. **Generics for user types** — user-defined `List`-like containers; today only
   the builtin `List`/`Option`/`Result` are parametric.
2. **A module/import system** — `import` is reserved but not yet implemented.
3. **Static contract verification** — discharge `requires`/`ensures` with an SMT
   solver where possible, leaving runtime checks only for the rest.
4. **A compiling backend** — to bytecode or native, exploiting immutability and
   declared effects for optimization.
5. **Totality/termination checking** — to make `ensures` provably reliable.

None of these change the principles above; they deepen them.
