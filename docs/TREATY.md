# Treaty — a language in which the world starts empty

Treaty is the second language in this repository, and it exists because of a
specific criticism of the first. Enochian (see `DESIGN.md`) is a competent
recombination of known-good safety features — and *recombination is derivative*.
Treaty is an attempt at a genuinely new **organizing principle**, chosen and
stress-tested by an adversarial design process rather than asserted.

> **Honesty first.** Treaty is *not* invented from nothing, and this document
> will not pretend it is. Its frame is heavily anticipated by object-capability
> languages and by WebAssembly's component model. What is genuinely
> under-occupied is a specific *combination*, described precisely in
> [§5, Honest antecedents](#5-honest-antecedents). Read that section before
> deciding how novel you think this is.

---

## 1. The rejected assumption

Every mainstream language — and even the safety-focused ones — assumes the
**world is ambiently available**. `print`, the clock, the filesystem, the
network simply *exist* in scope; a function need only reach for them, or at most
confess `!io`. Object-capability languages remove ambient *authority* (you must
hold a token), but they keep the ambient *vocabulary*: a global `open` still
exists as a name; you merely lack a capability to use it.

Treaty rejects both. **The world starts empty, and so does its vocabulary.**
There is no global `read`, no `open`, no `now`. These names do not exist. The
only way a power comes into being is to negotiate it.

## 2. The organizing principle

> A program is not a sequence of instructions acting on an ambient world.
> It is a **treaty**: a negotiation between the program and its environment in
> which every power is requested as data, granted (possibly narrowed) or
> refused, and then held only as a scoped, budgeted lease.

Running the program *is* the act of negotiating powers into existence with a
counterpart that can narrow or refuse them. Control flow and capability
acquisition are the same artifact.

## 3. The three artifacts

1. **Claim** — a pure, first-class value describing a desired power: a verb over
   a domain, plus a refinement.
   `claim read over fs where path under "/data/today"`.
   A claim confers no ability; it can be built, narrowed, and compared, but it
   performs nothing.

2. **`negotiate(claim)`** — the *sole* primitive that crosses the
   program/world boundary. It returns one of three typed outcomes:
   - `Granted(lease)` — the environment agreed; you get a lease.
   - `Countered(narrower)` — the environment offers *less*; you must inspect the
     narrower claim and re-present it. This is what makes it a negotiation and
     not a yes/no check.
   - `Refused(reason)` — no deal.

3. **Lease** — an unforgeable, region-scoped token. Effect verbs exist **only**
   as methods on a lease: `lease.read(path)`. The call is typed against the
   lease's refinement, so an out-of-bounds *literal* argument is a compile
   error. Leases are region-scoped (cannot escape) and carry an affine
   `total_le` byte budget (metered at runtime; exhaustion revokes the power).

## 4. Execution: two phases with a hard wall

**Phase 1 — static (`treaty check` / `treaty manifest`).** The checker proves
the world is empty (no verb is called except on a lease), that leases never
escape their region, and derives the **treaty manifest**: the set of all clauses
the program could ever negotiate. When a refinement is data-dependent, the
clause widens to `TOP` and is flagged `[data-dependent]` — the manifest never
over-claims precision.

**Phase boundary — co-sign.** The environment reads the derived manifest and
either co-signs it or **refuses to launch**, naming the offending clause. This
happens before any effect runs.

**Phase 2 — execution.** `negotiate` consults the policy; lease methods re-check
the refinement against the *actual* arguments, meter the budget, and reject a
revoked lease.

```
$ python -m treaty manifest examples/treaty/backup.treaty
treaty manifest (derived, sound over-approximation):
  read   over fs     where <data-dependent>   [data-dependent]
  read   over fs     where path under "/data"
  send   over net    where host eq "backup.internal" and total_le 100

$ python -m treaty run examples/treaty/refused.treaty
LaunchRefused: environment refuses to co-sign the treaty; unsatisfiable
  clause: send   over net    where host eq "anywhere.example"
```

## 5. Honest antecedents

This is the section the whole exercise turns on. Treaty's adversarial critic was
asked to *destroy* the novelty claim; here is what it found, unedited in spirit.

| Prior art | How much of Treaty it already is | What remains |
|---|---|---|
| **Object-capability languages** (E + Powerbox, Pony, Joe-E, Caja) | ~70%. Empty world, no ambient authority, power = unforgeable token, attenuable by a Powerbox. A Treaty lease *is* an ocap reference. | ocap removes ambient *authority* but keeps ambient *names* (a global `open` exists). Treaty makes the verb itself exist only as a refinement-typed lease method, and acquires authority through a request/grant/**counter**/refuse protocol rather than reference-passing. |
| **WASI p2 / WebAssembly Component Model** (WIT "worlds") | ~60% and the closest match. A component's declared imports are its "world," which the host must satisfy before instantiation — a static, host-readable, co-signed manifest. | WIT worlds are hand-declared and coarse (imported or not), with no per-call refinements or budgets. Treaty's manifest is *derived* from source by abstract interpretation over refinement-bearing, budgeted claims, and is diffable at clause granularity. |
| **Macaroons / SPKI-SDSI caveats** | Caveated tokens you narrow by appending predicates; a verifier refuses on caveat failure — exactly Treaty's refinement narrowing and Refused. | Treaty lifts caveat-checking into the static type system (out-of-refinement call = compile error, not runtime verify) and adds the typed **Countered** counter-offer, which macaroons (one-directional narrowing) lack. |
| **Region / affine types** (Rust, Linear Haskell, Cyclone) | The lease lifetime/budget mechanism is reused verbatim. | Applied to negotiated *world-powers* rather than to memory. |
| **Refinement / liquid types & session types** | Refinement predicates and the negotiate→Granted/Countered/Refused protocol are borrowed. | Refinements attached to *capabilities*; the session peer is the *world*, whose counter-offer feeds back as data to re-narrow. |
| **Permission-manifest models** (Android, iOS entitlements, `deno --allow-*`, Nix) | Deny-by-default declared manifest the platform approves, diffable across versions. | These are hand-maintained side files that can drift from code. Treaty's manifest is a sound static *derivation* from the program's own types, so it cannot drift. |

**The genuine residue,** stated plainly: (a) the *vocabulary itself* is
non-ambient — no verb name exists except as a lease method; (b) **typed
counter-offers** turn capability acquisition into a program-driven fixpoint;
(c) a **soundly-derived, diffable manifest** rather than a hand-declared one.
Whether that residue clears your bar for "novel" is a fair thing to debate — but
it is stated honestly, which was the point.

## 6. Why this suits an AI author

An AI author's most reliable failure is the unstated ambient assumption: it
calls `open(path)` on a half-inferred path, hits a network it assumed existed,
reads a clock inside a "pure" routine. Treaty makes that *syntactically
impossible*: you cannot emit `lease.write(...)` without, in the same text,
having constructed the claim, negotiated it, and bound the lease. A silent
assumption becomes an obligation the checker enforces at the call site.

Second, `Refused(reason)` and especially `Countered(narrower)` are a
machine-consumable regeneration signal — they tell the model *which clause to
weaken and to what*, the inverse of an opaque `PermissionError at line 412`.

Third, because the manifest is soundly derived, a supervising agent can bound
and audit exactly what AI-generated code is *capable* of doing to the world
before trusting it. That is audit-by-construction, not audit-by-review — a
property humans rarely need but untrusted AI-authored code urgently does.

## 7. What the prototype demonstrates

Each is exercised by `tests/run_treaty_tests.py`:

1. **Empty world** — `read("/x")` does not compile; the name does not exist.
2. **Refinement-typed verb** — a literal path outside a lease's refinement is a
   *compile* error naming the clause.
3. **Typed counter-offer** — a broad claim is countered, re-presented, and
   granted; the run succeeds against the narrowed lease.
4. **No escape / revocation** — returning a lease from its region is a compile
   error; exceeding `total_le` is a runtime `LeaseError`.
5. **Derived, diffable manifest** — printed from source; adding a negotiated
   domain adds exactly one clause.
6. **Co-sign before run** — a program whose manifest the policy won't grant
   fails to *launch*, by name, with nothing executed.
7. **Honest soundness bound** — a data-dependent claim widens its manifest
   clause to `TOP` and is flagged, rather than pretending to a precise bound.

## 8. Honest limitations (this is a prototype)

- **No interprocedural claims.** Leases cannot cross function boundaries and a
  negotiated claim's power must be statically known at its `negotiate` site, so
  the whole negotiation lives in one function. Threading capabilities through
  calls (soundly) is real work left undone.
- **Fixed domains/verbs and a four-predicate refinement grammar.** Enough to
  demonstrate the principle; not a general capability algebra.
- **Effects run against an in-memory sandbox**, not a real OS. The point is the
  discipline, not the I/O.
- **The manifest over-approximates conservatively.** Data-dependent refinements
  widen to `TOP`; a richer analysis would keep more precision.

None of these change the organizing principle; they bound the demo.
