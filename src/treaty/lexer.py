"""Lexer for Treaty."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LexError

KEYWORDS = {
    "fn", "let", "if", "then", "else", "match", "policy", "grant", "refuse",
    "over", "where", "and", "claim", "negotiate", "region", "true", "false",
}

TWO_CHAR = {
    "->": "ARROW", "=>": "FATARROW", "==": "EQ", "!=": "NEQ",
    "<=": "LE", ">=": "GE",
}

ONE_CHAR = {
    "(": "LPAREN", ")": "RPAREN", "{": "LBRACE", "}": "RBRACE",
    "[": "LBRACK", "]": "RBRACK", ":": "COLON", ",": "COMMA", ";": "SEMI",
    "=": "ASSIGN", ".": "DOT", "+": "PLUS", "<": "LT", ">": "GT",
}


@dataclass
class Token:
    kind: str
    value: str
    line: int
    col: int

    def __repr__(self) -> str:  # pragma: no cover
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.col})"


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    line = 1
    col = 1
    n = len(source)

    def adv(count: int = 1) -> None:
        nonlocal i, col
        i += count
        col += count

    while i < n:
        c = source[i]
        if c == "\n":
            i += 1
            line += 1
            col = 1
            continue
        if c in " \t\r":
            adv()
            continue
        if c == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue

        start_col = col

        if c == '"':
            adv()
            buf = []
            while i < n and source[i] != '"':
                ch = source[i]
                if ch == "\\":
                    adv()
                    if i >= n:
                        raise LexError("unterminated string escape", line, col)
                    esc = source[i]
                    buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc, esc))
                    adv()
                elif ch == "\n":
                    raise LexError("unterminated text literal", line, start_col)
                else:
                    buf.append(ch)
                    adv()
            if i >= n:
                raise LexError("unterminated text literal", line, start_col)
            adv()
            tokens.append(Token("TEXT", "".join(buf), line, start_col))
            continue

        if c.isdigit():
            buf = []
            while i < n and source[i].isdigit():
                buf.append(source[i])
                adv()
            tokens.append(Token("INT", "".join(buf), line, start_col))
            continue

        if c.isalpha() or c == "_":
            buf = []
            while i < n and (source[i].isalnum() or source[i] == "_"):
                buf.append(source[i])
                adv()
            word = "".join(buf)
            if word in KEYWORDS:
                tokens.append(Token(word.upper(), word, line, start_col))
            else:
                tokens.append(Token("IDENT", word, line, start_col))
            continue

        pair = source[i:i + 2]
        if pair in TWO_CHAR:
            tokens.append(Token(TWO_CHAR[pair], pair, line, start_col))
            adv(2)
            continue
        if c in ONE_CHAR:
            tokens.append(Token(ONE_CHAR[c], c, line, start_col))
            adv()
            continue

        raise LexError(f"unexpected character {c!r}", line, col)

    tokens.append(Token("EOF", "", line, col))
    return tokens
