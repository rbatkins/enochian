# Cross-model review packet — Treaty

You are one of several independent models asked to **critique**, not praise, a
newly-designed programming language called **Treaty**. Be adversarial and
specific. The author has explicitly asked you to try to *defeat* its claims.

## What Treaty is (one paragraph)

Treaty is a language whose organizing principle is that **the world starts
empty, and so does its vocabulary**. There is no global `read`, `open`, `now`,
or `send` — those names do not exist. To touch the filesystem, network, clock,
or randomness, a program must (1) construct a **claim** (pure data describing a
desired verb over a domain, plus a refinement like `path under "/data"`),
(2) call the sole boundary primitive `negotiate(claim)`, which returns
`Granted(lease)`, `Countered(narrower_claim)`, or `Refused(reason)`, and
(3) exercise the power only as a **method on the returned lease**
(`lease.read(path)`). Leases are region-scoped (cannot escape) and carry an
affine byte budget. The set of powers a program can request is a
statically-derived **manifest** the environment co-signs before anything runs.

## The novelty claim you are asked to judge

The author does **not** claim invention from nothing. Treaty's stated
antecedents:

- **Object-capability languages** (E + Powerbox, Pony, Joe-E): ~70% of the
  frame. Empty world, no ambient authority, power = unforgeable token. A Treaty
  lease *is* an ocap reference.
- **WASI p2 / WebAssembly Component Model** ("worlds"): ~60%. A statically
  declared, host-co-signed capability manifest checked before instantiation.
- **Macaroons / SPKI caveats**: refinement narrowing + refusal, at runtime.
- **Region/affine types** (Rust, Linear Haskell) and **refinement/liquid
  types** (F*, LiquidHaskell): reused for lease lifetime and claim predicates.

The author claims the **genuine residue** beyond all of these is exactly three
things:
1. the *vocabulary itself* is non-ambient (ocap removes ambient authority but
   keeps the ambient name `open`; Treaty has no verb name except as a lease
   method);
2. **typed counter-offers** (`Countered(narrower)`) that make capability
   acquisition a fixpoint the program drives, not a yes/no check;
3. a **soundly-derived, diffable manifest** (from the program's own types),
   rather than a hand-declared side file.

## The seven guarantees (each has passing tests + adversarial probes)

1. **Empty world** — an effect verb is only reachable as a lease method;
   `read("/x")` does not compile (the name does not exist).
2. **Refinement-typed verb** — a lease call with a *literal* argument outside
   the lease's refinement is a compile error naming the clause.
3. **Typed counter-offer** — a broad claim is countered, re-presented, granted.
4. **No lease escape** — a lease cannot be returned, stored, or passed;
   compile error via every route tried (match arm, list, `Ok(...)`, aliasing).
5. **Affine budget / revocation** — cumulative bytes capped by `total_le`
   (runtime `LeaseError`); leases revoked at region end.
6. **Co-sign before run** — a program whose manifest the policy won't grant
   fails to *launch*, by name, with no effect executed (sandbox verified clean).
7. **Honest soundness bound** — a data-dependent refinement widens its manifest
   clause to `TOP` and is flagged, rather than faking a precise static bound.

## A concrete example (real, runs)

```
policy {
  grant read  over fs  where path under "/data/today"
  grant send  over net where host eq "backup.internal" and total_le 100
  refuse write over fs
}
fn main() -> Result[Unit, Text] =
  region session {
    match negotiate(claim read over fs where path under "/data") {   # asks broad
      Refused(why)        => Err(why),
      Granted(_)          => Err("unexpected"),
      Countered(narrower) =>                                          # env offers /data/today
        match negotiate(narrower) {
          Refused(why) => Err(why),
          Countered(_) => Err("still countered"),
          Granted(rl)  =>
            match negotiate(claim send over net where host eq "backup.internal" and total_le 100) {
              Refused(why) => Err(why),
              Countered(_) => Err("send countered"),
              Granted(sl)  => Ok(sl.send("backup.internal", rl.read("/data/today/report.txt"))),
            },
        },
    }
  }
```

## Questions — please answer each directly

1. **Is the novelty claim honest, or overstated?** Is the "genuine residue"
   (non-ambient vocabulary, typed counter-offer, derived manifest) *also* fully
   anticipated by prior art? If so, name the closest system that already does
   the combination.
2. **Manifest soundness:** Is there a way to make a program *exercise* a power
   (domain+verb) that does **not** appear as a manifest clause — i.e. defeat the
   co-sign guarantee? Sketch the attack.
3. **Lease escape:** Is the "no escape" story actually watertight, or is there a
   route (higher-order use, capture, data-structure round-trip) that the
   described checks miss?
4. **Is the empty-*vocabulary* distinction from object-capability real and
   load-bearing, or cosmetic?** ocap folks would say "just don't put `open` in
   scope." Is Treaty doing more than that?
5. **Does this genuinely help an AI author** (fewer bugs / better regeneration
   signal via `Countered`/`Refused` / auditability), or is it merely different?
6. **Strongest steelman that Treaty is still derivative** — make the best case
   that this is a repackaging, and name what it repackages.
7. If you had to keep **one** of the three residue claims as the real
   contribution and discard the other two as derivative, which survives?

Full design + honest antecedents: `docs/TREATY.md`. Implementation:
`src/treaty/` (checker.py, interpreter.py, refinements.py). Tests:
`tests/run_treaty_tests.py`, `tests/run_treaty_attacks.py`.
