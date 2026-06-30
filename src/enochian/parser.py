"""Recursive-descent parser for Enochian.

Disambiguation rule (first principles -> one canonical reading):
  * Type names and sum-type variants start with an UPPERCASE letter.
  * Functions and variables start with a lowercase letter.
This single naming law lets the parser decide, with zero lookahead tricks,
whether `Foo(x)` builds a variant or `foo(x)` calls a function. It also makes
generated code uniform, which is the whole point.
"""

from __future__ import annotations

from . import ast
from .errors import ParseError
from .lexer import Token, tokenize

# Binary operator precedence. Higher binds tighter.
BINARY_PREC = {
    "OR": 1, "AND": 2,
    "EQ": 3, "NEQ": 3,
    "LT": 4, "LE": 4, "GT": 4, "GE": 4,
    "CONS": 5,
    "PLUS": 6, "MINUS": 6,
    "STAR": 7, "SLASH": 7, "PERCENT": 7,
}
RIGHT_ASSOC = {"CONS"}

OP_TEXT = {
    "OR": "or", "AND": "and", "EQ": "==", "NEQ": "!=",
    "LT": "<", "LE": "<=", "GT": ">", "GE": ">=", "CONS": "::",
    "PLUS": "+", "MINUS": "-", "STAR": "*", "SLASH": "/", "PERCENT": "%",
}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # -- token helpers ------------------------------------------------------
    def peek(self, offset: int = 0) -> Token:
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def at(self, kind: str) -> bool:
        return self.peek().kind == kind

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.peek()
        if tok.kind != kind:
            raise ParseError(
                f"expected {kind} but found {tok.kind} ({tok.value!r})",
                tok.line, tok.col,
            )
        return self.advance()

    # -- entry point --------------------------------------------------------
    def parse_program(self) -> ast.Program:
        type_decls: list[ast.TypeDecl] = []
        record_decls: list[ast.RecordDecl] = []
        fn_decls: list[ast.FnDecl] = []
        while not self.at("EOF"):
            if self.at("TYPE"):
                type_decls.append(self.parse_type_decl())
            elif self.at("RECORD"):
                record_decls.append(self.parse_record_decl())
            elif self.at("FN"):
                fn_decls.append(self.parse_fn_decl())
            elif self.at("IMPORT"):
                tok = self.peek()
                raise ParseError("module imports are not supported yet", tok.line, tok.col)
            else:
                tok = self.peek()
                raise ParseError(
                    f"expected a top-level declaration (fn/type/record) but found {tok.kind}",
                    tok.line, tok.col,
                )
        return ast.Program(type_decls, record_decls, fn_decls)

    # -- declarations -------------------------------------------------------
    def parse_type_decl(self) -> ast.TypeDecl:
        kw = self.expect("TYPE")
        name = self.expect("IDENT").value
        self.expect("ASSIGN")
        variants = [self.parse_variant()]
        while self.at("BAR"):
            self.advance()
            variants.append(self.parse_variant())
        return ast.TypeDecl(name, variants, kw.line, kw.col)

    def parse_variant(self) -> ast.VariantDef:
        name = self.expect("IDENT").value
        arg_types: list[ast.TypeRef] = []
        if self.at("LPAREN"):
            self.advance()
            if not self.at("RPAREN"):
                arg_types.append(self.parse_type())
                while self.at("COMMA"):
                    self.advance()
                    arg_types.append(self.parse_type())
            self.expect("RPAREN")
        return ast.VariantDef(name, arg_types)

    def parse_record_decl(self) -> ast.RecordDecl:
        kw = self.expect("RECORD")
        name = self.expect("IDENT").value
        self.expect("LBRACE")
        fields: list[ast.FieldDef] = []
        if not self.at("RBRACE"):
            fields.append(self.parse_field_def())
            while self.at("COMMA"):
                self.advance()
                if self.at("RBRACE"):
                    break
                fields.append(self.parse_field_def())
        self.expect("RBRACE")
        return ast.RecordDecl(name, fields, kw.line, kw.col)

    def parse_field_def(self) -> ast.FieldDef:
        name = self.expect("IDENT").value
        self.expect("COLON")
        return ast.FieldDef(name, self.parse_type())

    def parse_fn_decl(self) -> ast.FnDecl:
        kw = self.expect("FN")
        name = self.expect("IDENT").value
        self.expect("LPAREN")
        params: list[ast.Param] = []
        if not self.at("RPAREN"):
            params.append(self.parse_param())
            while self.at("COMMA"):
                self.advance()
                params.append(self.parse_param())
        self.expect("RPAREN")
        self.expect("ARROW")
        return_type = self.parse_type()

        effects: set[str] = set()
        while self.at("BANG"):
            self.advance()
            effects.add(self.expect("IDENT").value)

        contracts: list[ast.Contract] = []
        while self.at("REQUIRES") or self.at("ENSURES"):
            ctok = self.advance()
            kind = "requires" if ctok.kind == "REQUIRES" else "ensures"
            cexpr = self.parse_expr()
            contracts.append(ast.Contract(kind, cexpr, ctok.line, ctok.col))

        self.expect("ASSIGN")
        body = self.parse_expr()
        return ast.FnDecl(name, params, return_type, effects, contracts, body, kw.line, kw.col)

    def parse_param(self) -> ast.Param:
        name = self.expect("IDENT").value
        self.expect("COLON")
        return ast.Param(name, self.parse_type())

    # -- types --------------------------------------------------------------
    def parse_type(self) -> ast.TypeRef:
        tok = self.expect("IDENT")
        args: list[ast.TypeRef] = []
        if self.at("LBRACK"):
            self.advance()
            args.append(self.parse_type())
            while self.at("COMMA"):
                self.advance()
                args.append(self.parse_type())
            self.expect("RBRACK")
        return ast.TypeRef(tok.value, args, tok.line, tok.col)

    # -- expressions (precedence climbing) ----------------------------------
    def parse_expr(self, min_prec: int = 0) -> ast.Expr:
        left = self.parse_unary()
        while True:
            kind = self.peek().kind
            prec = BINARY_PREC.get(kind)
            if prec is None or prec < min_prec:
                break
            op_tok = self.advance()
            next_min = prec if kind in RIGHT_ASSOC else prec + 1
            right = self.parse_expr(next_min)
            left = ast.Binary(OP_TEXT[kind], left, right, op_tok.line, op_tok.col)
        return left

    def parse_unary(self) -> ast.Expr:
        tok = self.peek()
        if tok.kind == "NOT":
            self.advance()
            return ast.Unary("not", self.parse_unary(), tok.line, tok.col)
        if tok.kind == "MINUS":
            self.advance()
            return ast.Unary("-", self.parse_unary(), tok.line, tok.col)
        return self.parse_postfix()

    def parse_postfix(self) -> ast.Expr:
        expr = self.parse_primary()
        while self.at("DOT"):
            dot = self.advance()
            field = self.expect("IDENT").value
            expr = ast.FieldAccess(expr, field, dot.line, dot.col)
        return expr

    def parse_primary(self) -> ast.Expr:
        tok = self.peek()
        kind = tok.kind

        if kind == "INT":
            self.advance()
            return ast.IntLit(int(tok.value), tok.line, tok.col)
        if kind == "FLOAT":
            self.advance()
            return ast.FloatLit(float(tok.value), tok.line, tok.col)
        if kind == "TEXT":
            self.advance()
            return ast.TextLit(tok.value, tok.line, tok.col)
        if kind == "TRUE":
            self.advance()
            return ast.BoolLit(True, tok.line, tok.col)
        if kind == "FALSE":
            self.advance()
            return ast.BoolLit(False, tok.line, tok.col)
        if kind == "RESULT":
            self.advance()
            return ast.ResultVar(tok.line, tok.col)
        if kind == "LPAREN":
            self.advance()
            inner = self.parse_expr()
            self.expect("RPAREN")
            return inner
        if kind == "LBRACK":
            return self.parse_list_lit()
        if kind == "LBRACE":
            return self.parse_block()
        if kind == "IF":
            return self.parse_if()
        if kind == "MATCH":
            return self.parse_match()
        if kind == "IDENT":
            return self.parse_ident_expr()

        raise ParseError(f"unexpected token {kind} ({tok.value!r}) in expression", tok.line, tok.col)

    def parse_list_lit(self) -> ast.Expr:
        lb = self.expect("LBRACK")
        elements: list[ast.Expr] = []
        if not self.at("RBRACK"):
            elements.append(self.parse_expr())
            while self.at("COMMA"):
                self.advance()
                if self.at("RBRACK"):
                    break
                elements.append(self.parse_expr())
        self.expect("RBRACK")
        return ast.ListLit(elements, lb.line, lb.col)

    def parse_ident_expr(self) -> ast.Expr:
        tok = self.expect("IDENT")
        name = tok.value
        is_upper = name[0].isupper()

        # Record literal: `Name { field: expr, ... }`
        if is_upper and self.at("LBRACE"):
            self.advance()
            fields: dict[str, ast.Expr] = {}
            if not self.at("RBRACE"):
                fields.update(self.parse_record_field())
                while self.at("COMMA"):
                    self.advance()
                    if self.at("RBRACE"):
                        break
                    fields.update(self.parse_record_field())
            self.expect("RBRACE")
            return ast.RecordLit(name, fields, tok.line, tok.col)

        # Call or variant construction with arguments.
        if self.at("LPAREN"):
            self.advance()
            args: list[ast.Expr] = []
            if not self.at("RPAREN"):
                args.append(self.parse_expr())
                while self.at("COMMA"):
                    self.advance()
                    args.append(self.parse_expr())
            self.expect("RPAREN")
            if is_upper:
                return ast.Construct(name, args, tok.line, tok.col)
            return ast.Call(name, args, tok.line, tok.col)

        # Bare name.
        if is_upper:
            return ast.Construct(name, [], tok.line, tok.col)
        return ast.Var(name, tok.line, tok.col)

    def parse_record_field(self) -> dict[str, ast.Expr]:
        name = self.expect("IDENT").value
        self.expect("COLON")
        return {name: self.parse_expr()}

    def parse_block(self) -> ast.Expr:
        lb = self.expect("LBRACE")
        statements: list[object] = []
        result: ast.Expr | None = None
        while True:
            if self.at("LET"):
                statements.append(self.parse_let_stmt())
                self.expect("SEMI")
            elif self.at("SET"):
                statements.append(self.parse_set_stmt())
                self.expect("SEMI")
            else:
                expr = self.parse_expr()
                if self.at("SEMI"):
                    self.advance()
                    statements.append(ast.ExprStmt(expr, expr.line, expr.col))
                else:
                    result = expr
                    break
        self.expect("RBRACE")
        return ast.Block(statements, result, lb.line, lb.col)

    def parse_let_stmt(self) -> ast.LetStmt:
        kw = self.expect("LET")
        mutable = False
        if self.at("MUT"):
            self.advance()
            mutable = True
        name = self.expect("IDENT").value
        declared: ast.TypeRef | None = None
        if self.at("COLON"):
            self.advance()
            declared = self.parse_type()
        self.expect("ASSIGN")
        value = self.parse_expr()
        return ast.LetStmt(name, mutable, declared, value, kw.line, kw.col)

    def parse_set_stmt(self) -> ast.SetStmt:
        kw = self.expect("SET")
        name = self.expect("IDENT").value
        self.expect("ASSIGN")
        value = self.parse_expr()
        return ast.SetStmt(name, value, kw.line, kw.col)

    def parse_if(self) -> ast.Expr:
        kw = self.expect("IF")
        cond = self.parse_expr()
        self.expect("THEN")
        then_branch = self.parse_expr()
        self.expect("ELSE")
        else_branch = self.parse_expr()
        return ast.If(cond, then_branch, else_branch, kw.line, kw.col)

    def parse_match(self) -> ast.Expr:
        kw = self.expect("MATCH")
        scrutinee = self.parse_expr()
        self.expect("LBRACE")
        cases: list[ast.MatchCase] = []
        cases.append(self.parse_case())
        while self.at("COMMA"):
            self.advance()
            if self.at("RBRACE"):
                break
            cases.append(self.parse_case())
        self.expect("RBRACE")
        return ast.Match(scrutinee, cases, kw.line, kw.col)

    def parse_case(self) -> ast.MatchCase:
        pattern = self.parse_pattern()
        self.expect("FATARROW")
        body = self.parse_expr()
        return ast.MatchCase(pattern, body)

    def parse_pattern(self) -> ast.Pattern:
        head = self.parse_pattern_atom()
        if self.at("CONS"):
            tok = self.advance()
            tail = self.parse_pattern()
            return ast.Pattern("cons", subpatterns=[head, tail], line=tok.line, col=tok.col)
        return head

    def parse_pattern_atom(self) -> ast.Pattern:
        tok = self.peek()
        kind = tok.kind
        if kind == "IDENT" and tok.value == "_":
            self.advance()
            return ast.Pattern("wildcard", line=tok.line, col=tok.col)
        if kind == "INT":
            self.advance()
            return ast.Pattern("literal", value=int(tok.value), line=tok.line, col=tok.col)
        if kind == "FLOAT":
            self.advance()
            return ast.Pattern("literal", value=float(tok.value), line=tok.line, col=tok.col)
        if kind == "TEXT":
            self.advance()
            return ast.Pattern("literal", value=tok.value, line=tok.line, col=tok.col)
        if kind in ("TRUE", "FALSE"):
            self.advance()
            return ast.Pattern("literal", value=(kind == "TRUE"), line=tok.line, col=tok.col)
        if kind == "LBRACK":
            self.advance()
            self.expect("RBRACK")
            return ast.Pattern("empty_list", line=tok.line, col=tok.col)
        if kind == "IDENT":
            self.advance()
            if tok.value[0].isupper():
                subs: list[ast.Pattern] = []
                if self.at("LPAREN"):
                    self.advance()
                    if not self.at("RPAREN"):
                        subs.append(self.parse_pattern())
                        while self.at("COMMA"):
                            self.advance()
                            subs.append(self.parse_pattern())
                    self.expect("RPAREN")
                return ast.Pattern("variant", name=tok.value, subpatterns=subs, line=tok.line, col=tok.col)
            return ast.Pattern("binding", name=tok.value, line=tok.line, col=tok.col)
        raise ParseError(f"invalid pattern starting with {kind}", tok.line, tok.col)


def parse(source: str) -> ast.Program:
    return Parser(tokenize(source)).parse_program()
