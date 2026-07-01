# Languages from first principles, for AI authorship

This repository contains **two** programming languages, designed for one
purpose — *to be written by AI, run efficiently, and produce as few bugs as
possible* — and a candid argument about what "from first principles" can and
cannot mean. Both come with full reference implementations (lexer → parser →
static checker → interpreter), runnable examples, and passing test suites.

They exist as a pair on purpose:

| | What it is | Honest status |
|---|---|---|
| **Enochian** (`src/enochian`) | A statically-checked language that removes the largest historical bug classes: no null, errors as values, immutable by default, effects in the signature, exhaustive matching, executable contracts. | **Derivative, and says so.** A tasteful recombination of known-good ideas from the ML/Rust/Eiffel lineage. Good engineering; not invention. |
| **Treaty** (`src/treaty`) | A language in which *the world starts empty*: every power (fs, net, clock) must be negotiated as data into a scoped, budgeted lease, and the set of powers is a statically-derived manifest the environment co-signs before anything runs. | **An attempt at a genuinely new organizing principle**, chosen by an adversarial design process — with its prior art (object-capability languages, WASI worlds, macaroons) disclosed in full. |

The second language was built because a reviewer rightly pointed out that the
first was derivative. That whole argument — including why *ex nihilo* novelty is
a myth but a new *organizing principle* is not — is written up in
[`docs/DESIGN.md §0`](docs/DESIGN.md#0-what-first-principles-means-here-and-what-it-does-not)
and [`docs/TREATY.md`](docs/TREATY.md).

```
$ python -m treaty run examples/treaty/backup.treaty
result: Ok(unit)
net.send log:
  -> backup.internal: 'sales up 4pct'

$ python -m treaty run examples/treaty/refused.treaty
LaunchRefused: environment refuses to co-sign the treaty; unsatisfiable
  clause: send   over net    where host eq "anywhere.example"
```

---

# Enochian — the safety language

A small language that asks: *if the author is a model that can read a type
checker's feedback and regenerate code instantly, what should the language make
impossible?*

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
src/treaty/       # the Treaty implementation (see below)
examples/         # runnable .en programs
examples/treaty/  # runnable .treaty programs
tests/            # self-contained test runners (run_tests.py, run_treaty_tests.py)
docs/
  DESIGN.md       # Enochian: first-principles rationale + the "myth" argument
  SPEC.md         # Enochian: language reference and grammar
  TREATY.md       # Treaty: organizing principle + HONEST antecedents
```

---

# Treaty — the empty-world language

Treaty is the answer to *"that's derivative — do something genuinely new."*
Its organizing principle: **the world starts empty, and so does its
vocabulary.** There is no global `read`, `open`, or `now`. Every power must be
requested as data, negotiated with the environment (which can narrow or refuse
it), and held only as a scoped, budgeted **lease**. Effect verbs exist *only* as
methods on a lease.

```bash
python -m treaty manifest examples/treaty/backup.treaty  # the derived capability manifest
python -m treaty run      examples/treaty/backup.treaty  # co-sign, then execute
python -m treaty check    examples/treaty/refused.treaty
python tests/run_treaty_tests.py                          # 19 cases
```

What makes it more than a permission check is the **typed counter-offer**: when
you ask for more than the policy allows, `negotiate` returns `Countered(narrower)`
and you re-present the narrower claim — negotiation as a fixpoint the program
drives. And the set of powers a program *can* request is a statically-derived,
diffable **manifest** the environment co-signs before anything runs.

Treaty does not claim to be invented from nothing. Its frame is ~70% object-
capability languages and ~60% WebAssembly's WIT "worlds"; the genuine residue is
the non-ambient vocabulary, the typed counter-offer, and the sound manifest
derivation. The full, unflattering prior-art accounting is in
[`docs/TREATY.md §5`](docs/TREATY.md#5-honest-antecedents).

```
src/treaty/
  refinements.py  # the claim/lease refinement algebra (entail / meet / compatible)
  world.py        # the fixed, non-ambient vocabulary of verbs
  lexer.py parser.py ast.py
  checker.py      # empty-world + refinement-typed verbs + no-escape + manifest
  interpreter.py  # negotiate, lease dispatch, budgets, region revocation, co-sign
  cli.py          # `run` / `check` / `manifest`
```

---

## Status

Both languages are complete, working tree-walking reference implementations
intended to define and demonstrate their semantics clearly.

- **Enochian**: primitives, `Option`/`Result`, lists, records, sum types,
  exhaustive matching, immutability with explicit `mut`, an effect system,
  runtime contracts. Roadmap in [`docs/DESIGN.md`](docs/DESIGN.md#roadmap).
- **Treaty**: claims, `negotiate` with typed counter-offers, refinement-typed
  lease verbs, region-scoped affine leases, derived+co-signed manifests. Known
  limitations (no interprocedural claims, fixed domains, sandboxed I/O) are
  listed honestly in [`docs/TREATY.md §8`](docs/TREATY.md#8-honest-limitations-this-is-a-prototype).
