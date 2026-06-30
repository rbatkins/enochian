# Enochian

A small programming language designed from first principles for one purpose:
**to be written by AI, run efficiently, and produce as few bugs as possible.**

Most languages were designed for humans typing at a terminal, and then patched
for decades to paper over the mistakes in their foundations — `null`,
exceptions, implicit coercion, undefined behavior, "there's more than one way
to do it." Enochian starts over. It asks a different question: *if the author is
a model that can read a type checker's feedback and regenerate code instantly,
what should the language make impossible?*

The answer drives every decision below. This repository contains the design,
a full reference implementation (lexer → parser → static checker → interpreter),
runnable examples, and a test suite.

```
$ python -m enochian run examples/bank.en
Grace now has 70
declined: insufficient funds
declined: amount must be positive
```

---

## The ten principles

1. **No `null`.** Absence is `Option[T]`; recoverable failure is
   `Result[T, E]`. The most expensive bug class in software history is removed
   at the root.
2. **No exceptions for ordinary failure.** Fallible operations return their
   failure in the *type*. A caller cannot forget to handle it — the `match`
   is exhaustive or the program does not compile.
3. **Everything is checked before anything runs.** Types, name resolution,
   exhaustiveness, effects, and mutability are all proven statically. Runtime
   surprises are designed out, not debugged out.
4. **One canonical form.** No synonyms, no optional punctuation, no two ways to
   write the same thing. This makes generated code uniform and diffs minimal —
   the single biggest lever for an AI author and for review.
5. **Immutable by default.** Bindings don't change unless declared `mut`, and
   mutation is a visible, local `set`. No spooky action at a distance.
6. **Effects are in the signature.** A function that does I/O must say `!io`.
   Side effects can't hide; purity is the default and is verified.
7. **Contracts are executable specifications.** `requires`/`ensures` state
   pre/postconditions in code. They are checked at runtime and separate
   *programmer bugs* (which abort loudly) from *expected failure* (which is a
   value).
8. **Exhaustiveness everywhere.** Every `match` must cover every case; adding a
   variant turns every incomplete match into a compile error — a to-do list,
   not a landmine.
9. **No undefined behavior.** Division by zero aborts with a clear error;
   indexing returns `Option`. There is no "it depends on the platform."
10. **Locality.** Everything needed to understand a function — its types, its
    effects, its contracts — is in its signature. This suits a bounded context
    window and a human reviewer equally.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the reasoning behind each one and the
specific historical bug it removes.

---

## A taste

```
# Errors are values. The signature shows both outcomes, so the caller
# cannot ignore failure.
record Account { owner: Text, balance: Int }

fn withdraw(acct: Account, amount: Int) -> Result[Account, Text] =
    if amount <= 0 then
        Err("amount must be positive")
    else if amount > acct.balance then
        Err("insufficient funds")
    else
        Ok(Account { owner: acct.owner, balance: acct.balance - amount })

# Contracts document and enforce intent.
fn fact(n: Int) -> Int
    requires n >= 0
    ensures result >= 1 =
    if n == 0 then 1 else n * fact(n - 1)

# Effects are visible. This function must declare `!io` to call `print`.
fn main() -> Unit !io =
    print("6! = " + int_to_text(fact(6)))
```

---

## Quickstart

Enochian's reference toolchain is pure Python 3.8+ with **no dependencies**.

```bash
# Run a program (parses, type-checks, then executes)
python -m enochian run examples/lists.en

# Type-check only — proves well-formedness without running
python -m enochian check examples/shapes.en

# Inspect the parsed AST
python -m enochian ast examples/hello.en
```

From the project root you may need `PYTHONPATH=src`, or install it:

```bash
pip install -e .        # provides the `enochian` command
enochian run examples/bank.en
```

Run the test suite (52 cases, no external dependencies):

```bash
python tests/run_tests.py
```

---

## Project layout

```
src/enochian/
  lexer.py        # source text -> tokens
  ast.py          # node definitions
  parser.py       # tokens -> AST (recursive descent + precedence climbing)
  types.py        # the type model (no null; Option/Result built in)
  checker.py      # static analysis: types, effects, mutability, exhaustiveness
  interpreter.py  # tree-walking evaluator + runtime contract enforcement
  cli.py          # `run` / `check` / `ast` commands
examples/         # runnable .en programs
tests/            # self-contained test runner
docs/
  DESIGN.md       # first-principles rationale, decision by decision
  SPEC.md         # language reference and grammar
```

---

## Status

This is a complete, working reference implementation of the language core:
primitives, `Option`/`Result`, lists, records, sum types, exhaustive pattern
matching, immutability with explicit `mut`, an effect system, runtime contracts,
and a CLI. It is a tree-walking interpreter intended to define and demonstrate
the semantics clearly. A native/bytecode backend, a module system, generics for
user-defined types, and static contract verification are the natural next
steps — see [`docs/DESIGN.md`](docs/DESIGN.md#roadmap).
