# Enochian Language Reference

Version 0.1. This document defines the surface syntax and the static and dynamic
semantics of the language as implemented in `src/enochian`.

---

## 1. Lexical structure

- **Comments** start with `#` and run to end of line.
- **Whitespace** (spaces, tabs, newlines) separates tokens and is otherwise
  insignificant.
- **Identifiers** match `[A-Za-z_][A-Za-z0-9_]*`. The leading case is
  meaningful (see §3).
- **Int literals**: `[0-9]+`. Arbitrary precision.
- **Float literals**: `[0-9]+\.[0-9]+` (a digit is required on both sides of the
  dot).
- **Text literals**: `"..."` with escapes `\n`, `\t`, `\"`, `\\`. No multi-line
  text literals.
- **Keywords**: `fn let mut set if then else match type record requires ensures
  true false and or not result import`.
- **Operators and punctuation**: `-> => == != <= >= && || :: ( ) { } [ ] : , ;
  = + - * / % < > . | !`

---

## 2. Grammar

```ebnf
program     = { declaration } ;
declaration = fnDecl | typeDecl | recordDecl ;

typeDecl    = "type" UpperName "=" variant { "|" variant } ;
variant     = UpperName [ "(" [ type { "," type } ] ")" ] ;

recordDecl  = "record" UpperName "{" [ field { "," field } [ "," ] ] "}" ;
field       = lowerOrName ":" type ;

fnDecl      = "fn" LowerName "(" [ param { "," param } ] ")"
              "->" type { effect } { contract } "=" expr ;
param       = LowerName ":" type ;
effect      = "!" Name ;
contract    = ( "requires" | "ensures" ) expr ;

type        = Name [ "[" type { "," type } "]" ] ;

expr        = binary ;
binary      = unary { binop unary } ;        (* precedence-climbed; see §4 *)
unary       = ( "not" | "-" ) unary | postfix ;
postfix     = primary { "." Name } ;
primary     = INT | FLOAT | TEXT | "true" | "false" | "result"
            | "(" expr ")"
            | "[" [ expr { "," expr } [ "," ] ] "]"
            | block | ifExpr | matchExpr
            | LowerName [ "(" [ args ] ")" ]            (* var or call *)
            | UpperName ( "(" [ args ] ")" | "{" recFields "}" | ε ) ;
args        = expr { "," expr } ;
recFields   = Name ":" expr { "," Name ":" expr } [ "," ] ;

block       = "{" { statement } expr "}" ;
statement   = letStmt ";" | setStmt ";" | expr ";" ;
letStmt     = "let" [ "mut" ] LowerName [ ":" type ] "=" expr ;
setStmt     = "set" LowerName "=" expr ;

ifExpr      = "if" expr "then" expr "else" expr ;
matchExpr   = "match" expr "{" case { "," case } [ "," ] "}" ;
case        = pattern "=>" expr ;

pattern     = patAtom [ "::" pattern ] ;     (* :: is right-associative *)
patAtom     = "_" | INT | FLOAT | TEXT | "true" | "false"
            | "[" "]"
            | UpperName [ "(" pattern { "," pattern } ")" ]   (* variant *)
            | LowerName ;                                     (* binding *)
```

`UpperName` begins with an uppercase letter; `LowerName` with lowercase or `_`.
`Name` is either.

---

## 3. The naming law

- **Types and sum-type variants** begin with an uppercase letter
  (`Int`, `Option`, `Circle`, `Account`).
- **Functions and variables** begin with a lowercase letter (`main`, `acc`).

This is enforced by the checker and used by the parser to disambiguate, with
zero lookahead, between a function call `f(x)` and a variant construction
`F(x)`, and between a variable `x` and a nullary variant `X`.

---

## 4. Operators and precedence

From lowest to highest binding. All are left-associative except `::`.

| Precedence | Operators | Types |
|---|---|---|
| 1 | `or` `\|\|` | `Bool, Bool -> Bool` (short-circuit) |
| 2 | `and` `&&` | `Bool, Bool -> Bool` (short-circuit) |
| 3 | `==` `!=` | `T, T -> Bool` (any equal types) |
| 4 | `<` `<=` `>` `>=` | `Int/Float/Text -> Bool` |
| 5 | `::` (right) | `T, List[T] -> List[T]` |
| 6 | `+` `-` | `Int/Float`; `+` also `Text,Text -> Text` |
| 7 | `*` `/` `%` | `Int/Float`; `%` is `Int` only |
| (prefix) | `not` `-` | `Bool -> Bool`; `Int/Float` negation |
| (postfix) | `.field` | record field access |

`or`/`||` and `and`/`&&` are spellings of the same operator. `not` is the only
logical negation (`!` is reserved for effect annotations).

`/` on two `Int` truncates toward zero. `/` or `%` by zero is a `ContractError`.

---

## 5. Types

Built-in:

- **Primitives**: `Int` (arbitrary precision), `Float` (64-bit), `Bool`,
  `Text`, `Unit`.
- **`List[T]`** — immutable homogeneous sequence.
- **`Option[T]`** — `Some(T)` | `None`. Models absence. Replaces null.
- **`Result[T, E]`** — `Ok(T)` | `Err(E)`. Models recoverable failure.

User-defined:

- **`record Name { f: T, ... }`** — a product type with named fields. Immutable.
  Constructed with `Name { f: expr, ... }` (all fields required, no extras),
  read with `value.f`.
- **`type Name = A | B(T) | C(T, U)`** — a sum type. Constructed by naming a
  variant (`A`, `B(x)`), deconstructed by `match`.

There is no `null` and no implicit conversion between any two types. Variant
names must be unique across all sum types, and `Some`/`None`/`Ok`/`Err` are
reserved.

---

## 6. Expressions and statements

Everything is an expression and yields a value.

- **`if c then a else b`** — `c : Bool`; `a` and `b` must have the same type;
  both branches are required.
- **`match`** — see §7.
- **Block `{ stmt; ... result }`** — introduces a scope. Each statement is a
  `let`, a `set`, or a discarded expression, terminated by `;`. The trailing
  `result` (no `;`) is the block's value. A discarded expression statement must
  have type `Unit`, so a meaningful value can never be dropped by accident.
- **`let [mut] name [: T] = expr`** — binds a name in the current block.
  Immutable unless `mut`.
- **`set name = expr`** — reassigns an existing `mut` binding (it may live in an
  enclosing scope). Targeting an immutable or undefined name is a compile error.

---

## 7. Pattern matching

`match scrutinee { pat => expr, ... }`. The first matching arm wins. Patterns:

| Pattern | Matches |
|---|---|
| `_` | anything (no binding) |
| `name` | anything, binding it to `name` |
| literal (`0`, `1.5`, `"x"`, `true`) | an equal value of the same type |
| `[]` | the empty list |
| `head :: tail` | a non-empty list, binding head and tail |
| `Variant(p, ...)` | that variant, recursing into sub-patterns |

**Exhaustiveness is mandatory.** A match must cover all variants of a sum type,
both `Some`/`None`, both `Ok`/`Err`, both `true`/`false`, or both `[]` and
`h :: t` — unless it ends with a catch-all (`_` or a binding). An arm after a
catch-all is a compile error (unreachable).

---

## 8. Effects

A function lists the effects it may perform after its return type, each as
`!name` (e.g. `!io`). The checker computes the effects a body performs from the
builtins and functions it calls, and rejects any effect that is not declared.
Functions with no annotation are pure, and this is verified. `requires`/`ensures`
expressions must be pure.

The only built-in effect in this version is `io` (produced by `print`).

---

## 9. Contracts

After the effect list, a function may state any number of contracts:

- **`requires <bool expr>`** — a precondition over the parameters.
- **`ensures <bool expr>`** — a postcondition; may reference `result`, the
  function's return value.

Contracts are pure boolean expressions, evaluated at runtime. A failure raises a
`ContractError`, which is **not catchable from Enochian code**: it signals a
programmer bug and aborts.

---

## 10. Built-in functions

| Function | Type | Effect |
|---|---|---|
| `print(t)` | `Text -> Unit` | `io` |
| `len(xs)` | `List[T] -> Int` | — |
| `get(xs, i)` | `List[T], Int -> Option[T]` | — (safe; no out-of-bounds) |
| `push(xs, x)` | `List[T], T -> List[T]` | — (returns a new list) |
| `concat(a, b)` | `List[T], List[T] -> List[T]` | — |
| `int_to_text(n)` | `Int -> Text` | — |
| `float_to_text(x)` | `Float -> Text` | — |
| `bool_to_text(b)` | `Bool -> Text` | — |
| `text_len(t)` | `Text -> Int` | — |

---

## 11. Programs and execution

A program is a set of top-level declarations; order does not matter (forward
references and mutual recursion are allowed). Execution begins at a chosen entry
function (default `main`), invoked with no arguments.

The pipeline is: **parse → static check → interpret**. If the static check finds
any fault — a type error, an unbound name, a non-exhaustive match, an undeclared
effect, an illegal mutation — the program is rejected before any code runs.

---

## 12. Errors (host-level)

The toolchain distinguishes:

- `LexError`, `ParseError` — malformed source.
- `CompileError` — any static-check fault (the bulk of bug prevention).
- `ContractError` — a runtime contract violation or a totality violation
  (division by zero). Always a programmer bug.
- `PanicError` — an explicit, acknowledged abort.

Only the first three can occur for a well-written program under normal use; the
first two and `CompileError` occur before execution.
