"""Lexer for Enochian.

Design note (first principles): Enochian has *one* lexical form for each
concept. There are no synonyms, no significant whitespace games, and no
optional punctuation. Statements inside a block are terminated by `;` and the
final expression is not. This removes a whole class of ambiguity that makes
generated code inconsistent (and makes diffs noisy).
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LexError

KEYWORDS = {
    "fn", "let", "mut", "set", "if", "then", "else", "match", "type",
    "record", "requires", "ensures", "true", "false", "and", "or", "not",
    "result", "import",
}

# Multi-character operators must be tried before single-character ones.
TWO_CHAR = {
    "->": "ARROW",
    "=>": "FATARROW",
    "==": "EQ",
    "!=": "NEQ",
    "<=": "LE",
    ">=": "GE",
    "&&": "AND",
    "||": "OR",
    "::": "CONS",
}

ONE_CHAR = {
    "(": "LPAREN", ")": "RPAREN",
    "{": "LBRACE", "}": "RBRACE",
    "[": "LBRACK", "]": "RBRACK",
    ":": "COLON", ",": "COMMA", ";": "SEMI",
    "=": "ASSIGN", "+": "PLUS", "-": "MINUS",
    "*": "STAR", "/": "SLASH", "%": "PERCENT",
    "<": "LT", ">": "GT", ".": "DOT", "|": "BAR",
    "!": "BANG",
}


@dataclass
class Token:
    kind: str
    value: str
    line: int
    col: int

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.col})"


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    line = 1
    col = 1
    n = len(source)

    def advance(count: int = 1) -> None:
        nonlocal i, col
        i += count
        col += count

    while i < n:
        c = source[i]

        # Newlines
        if c == "\n":
            i += 1
            line += 1
            col = 1
            continue

        # Whitespace
        if c in " \t\r":
            advance()
            continue

        # Comments: `#` to end of line.
        if c == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue

        start_col = col

        # Text literals: "double quoted" with simple escapes.
        if c == '"':
            advance()
            buf = []
            while i < n and source[i] != '"':
                ch = source[i]
                if ch == "\\":
                    advance()
                    if i >= n:
                        raise LexError("unterminated string escape", line, col)
                    esc = source[i]
                    buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc, esc))
                    advance()
                elif ch == "\n":
                    raise LexError("unterminated text literal", line, start_col)
                else:
                    buf.append(ch)
                    advance()
            if i >= n:
                raise LexError("unterminated text literal", line, start_col)
            advance()  # closing quote
            tokens.append(Token("TEXT", "".join(buf), line, start_col))
            continue

        # Numbers: Int and Float. No leading-dot, no trailing-dot (clarity).
        if c.isdigit():
            buf = []
            is_float = False
            while i < n and source[i].isdigit():
                buf.append(source[i])
                advance()
            if i < n and source[i] == "." and i + 1 < n and source[i + 1].isdigit():
                is_float = True
                buf.append(".")
                advance()
                while i < n and source[i].isdigit():
                    buf.append(source[i])
                    advance()
            tokens.append(Token("FLOAT" if is_float else "INT", "".join(buf), line, start_col))
            continue

        # Identifiers and keywords.
        if c.isalpha() or c == "_":
            buf = []
            while i < n and (source[i].isalnum() or source[i] == "_"):
                buf.append(source[i])
                advance()
            word = "".join(buf)
            if word in KEYWORDS:
                tokens.append(Token(word.upper(), word, line, start_col))
            else:
                tokens.append(Token("IDENT", word, line, start_col))
            continue

        # Two-character operators.
        pair = source[i:i + 2]
        if pair in TWO_CHAR:
            tokens.append(Token(TWO_CHAR[pair], pair, line, start_col))
            advance(2)
            continue

        # Single-character operators.
        if c in ONE_CHAR:
            tokens.append(Token(ONE_CHAR[c], c, line, start_col))
            advance()
            continue

        raise LexError(f"unexpected character {c!r}", line, col)

    tokens.append(Token("EOF", "", line, col))
    return tokens
