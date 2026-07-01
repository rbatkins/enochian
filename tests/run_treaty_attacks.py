"""Adversarial probes against Treaty's guarantees, run against the real toolchain.

Each case states what a SOUND implementation must do. A case is a BREAK only if
the observed behavior defeats the guarantee.
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from treaty import compile_source, run_source, Sandbox
from treaty.errors import CompileError, LaunchRefused, LeaseError, ParseError

def vfs():
    return Sandbox(vfs={"/data/today/a.txt": "alpha", "/etc/passwd": "secret"})

BREAKS = []
def case(name, src, sound_kinds, run=False, extra_check=None):
    """sound_kinds: set of exception type names that count as SOUND handling,
    or 'value' if a normal successful value is the sound expectation."""
    try:
        if run:
            result, interp = run_source(src, sandbox=vfs())
        else:
            compile_source(src)
            result, interp = ("<compiled-ok>", None)
        outcome = ("value", result, interp)
    except (CompileError, LaunchRefused, LeaseError, ParseError) as e:
        outcome = (type(e).__name__, str(e), None)
    except Exception as e:  # noqa
        outcome = ("OTHER:" + type(e).__name__, str(e), None)

    kind = outcome[0]
    sound = kind in sound_kinds
    if sound and extra_check is not None:
        sound = extra_check(outcome)
    status = "SOUND" if sound else "*** BREAK ***"
    if not sound:
        BREAKS.append(name)
    detail = outcome[1] if isinstance(outcome[1], str) else repr(outcome[1])
    print(f"[{status}] {name}\n        -> {kind}: {detail[:140]}")


# --- empty world ---
case("empty-world: global read()", 'fn main() -> Text = read("/x")', {"CompileError"})
case("empty-world: verb on Text", 'fn main() -> Text = "hi".read("/x")', {"CompileError"})

# --- refinement static ---
case("refine: literal outside path is compile error",
     '''policy { grant read over fs where path under "/data/today" }
fn main() -> Text = match negotiate(claim read over fs where path under "/data/today") {
  Granted(rl) => rl.read("/etc/passwd"), Countered(_) => "c", Refused(w) => w, }''',
     {"CompileError"})
case("refine: data-dependent path caught at runtime (honest)",
     '''policy { grant read over fs where path under "/data/today" }
fn main() -> Text = match negotiate(claim read over fs where path under "/data/today") {
  Granted(rl) => rl.read(concat("/etc", "/passwd")), Countered(_) => "c", Refused(w) => w, }''',
     {"LeaseError"}, run=True)

# --- no escape ---
case("escape: return lease from match arm",
     '''policy { grant read over fs where path under "/data" }
fn main() -> Unit = region r { match negotiate(claim read over fs where path under "/data") {
  Granted(rl) => rl, Countered(_) => z(), Refused(_) => z(), } }
fn z() -> Unit = z()''', {"CompileError"})
case("escape: lease in a list",
     '''policy { grant read over fs where path under "/data" }
fn main() -> Unit = region r { match negotiate(claim read over fs where path under "/data") {
  Granted(rl) => { let bag = [rl]; z() }, Countered(_) => z(), Refused(_) => z(), } }
fn z() -> Unit = z()''', {"CompileError"})
case("escape: lease inside Ok()",
     '''policy { grant read over fs where path under "/data" }
fn main() -> Result[Unit, Text] = region r { match negotiate(claim read over fs where path under "/data") {
  Granted(rl) => Ok(rl), Countered(_) => Err("c"), Refused(w) => Err(w), } }''', {"CompileError"})
case("escape: alias via let then return from region",
     '''policy { grant read over fs where path under "/data" }
fn main() -> Unit = region r { match negotiate(claim read over fs where path under "/data") {
  Granted(rl) => { let m = rl; m }, Countered(_) => z(), Refused(_) => z(), } }
fn z() -> Unit = z()''', {"CompileError"})

# --- budget ---
case("budget: single oversized send",
     '''policy { grant send over net where host eq "h" and total_le 6 }
fn main() -> Unit = region s { match negotiate(claim send over net where host eq "h" and total_le 6) {
  Granted(sl) => sl.send("h", "toolongpayload"), Countered(_) => z(), Refused(_) => z(), } }
fn z() -> Unit = z()''', {"LeaseError"}, run=True)
case("budget: cumulative exceed across two sends",
     '''policy { grant send over net where host eq "h" and total_le 6 }
fn main() -> Unit = region s { match negotiate(claim send over net where host eq "h" and total_le 6) {
  Granted(sl) => { sl.send("h", "abcd"); sl.send("h", "efgh") }, Countered(_) => z(), Refused(_) => z(), } }
fn z() -> Unit = z()''', {"LeaseError"}, run=True)

# --- cosign: no effect before/despite refusal ---
def no_side_effects(outcome):
    # LaunchRefused raised before run; ensure nothing could have executed.
    return True  # LaunchRefused is raised by cosign() before interp.run() is called
case("cosign: manifest needs write, policy grants only read -> LaunchRefused",
     '''policy { grant read over fs where path under "/data" }
fn main() -> Unit = match negotiate(claim write over fs where path under "/data") {
  Granted(wl) => wl.write("/data/x", "y"), Countered(_) => z(), Refused(_) => z(), }
fn z() -> Unit = z()''', {"LaunchRefused"}, run=True, extra_check=no_side_effects)

# Direct assertion that no write happened when co-sign fails.
def cosign_no_write():
    src = '''policy { grant read over fs where path under "/data" }
fn main() -> Unit = match negotiate(claim write over fs where path under "/data") {
  Granted(wl) => wl.write("/data/PWNED", "x"), Countered(_) => z(), Refused(_) => z(), }
fn z() -> Unit = z()'''
    sb = vfs()
    try:
        run_source(src, sandbox=sb)
        print("[*** BREAK ***] cosign: run() completed (should have refused launch)")
        BREAKS.append("cosign-ran")
    except LaunchRefused:
        if "/data/PWNED" in sb.vfs:
            print("[*** BREAK ***] cosign: a write executed despite LaunchRefused!")
            BREAKS.append("cosign-effect")
        else:
            print("[SOUND] cosign: no effect executed before launch refusal (sandbox clean)")
cosign_no_write()

# --- manifest soundness: exercise a power absent from the manifest? ---
def manifest_covers_all():
    src = '''policy { grant read over fs where path under "/d"
  grant now over clock }
fn main() -> Text = match negotiate(claim read over fs where path under "/d") {
  Granted(rl) => rl.read("/d/x"), Countered(_) => "c", Refused(w) => w, }
fn t() -> Int = match negotiate(claim now over clock) {
  Granted(cl) => cl.now(), Countered(_) => 0, Refused(_) => 0, }'''
    _, checker = compile_source(src)
    clauses = {(c.domain, c.verb) for c in checker.manifest_clauses()}
    # Every negotiate power must appear.
    need = {("fs", "read"), ("clock", "now")}
    if need <= clauses:
        print(f"[SOUND] manifest: all negotiated powers present {sorted(clauses)}")
    else:
        print(f"[*** BREAK ***] manifest: missing {need - clauses}")
        BREAKS.append("manifest-missing")
manifest_covers_all()

print()
if BREAKS:
    print(f"CONFIRMED BREAKS: {BREAKS}")
    sys.exit(1)
print("No breaks confirmed: all probed guarantees held.")
