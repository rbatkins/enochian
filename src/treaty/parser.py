"""Recursive-descent parser for Treaty."""

from __future__ import annotations

from . import ast
from .errors import ParseError
from .lexer import Token, tokenize


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self, offset: int = 0) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

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
            raise ParseError(f"expected {kind} but found {tok.kind} ({tok.value!r})", tok.line, tok.col)
        return self.advance()

    def expect_ident(self, word: str | None = None) -> Token:
        tok = self.expect("IDENT")
        if word is not None and tok.value != word:
            raise ParseError(f"expected {word!r} but found {tok.value!r}", tok.line, tok.col)
        return tok

    # -- program ------------------------------------------------------------
    def parse_program(self) -> ast.Program:
        policy: ast.Policy | None = None
        fns: list[ast.FnDecl] = []
        while not self.at("EOF"):
            if self.at("POLICY"):
                if policy is not None:
                    tok = self.peek()
                    raise ParseError("a program may declare at most one policy block", tok.line, tok.col)
                policy = self.parse_policy()
            elif self.at("FN"):
                fns.append(self.parse_fn())
            else:
                tok = self.peek()
                raise ParseError(f"expected `policy` or `fn`, found {tok.kind}", tok.line, tok.col)
        return ast.Program(policy, fns)

    # -- policy -------------------------------------------------------------
    def parse_policy(self) -> ast.Policy:
        kw = self.expect("POLICY")
        self.expect("LBRACE")
        grants: list[ast.Grant] = []
        while not self.at("RBRACE"):
            grants.append(self.parse_grant())
        self.expect("RBRACE")
        return ast.Policy(grants, kw.line, kw.col)

    def parse_grant(self) -> ast.Grant:
        if self.at("REFUSE"):
            tok = self.advance()
            refuse = True
        else:
            tok = self.expect("GRANT")
            refuse = False
        verb = self.expect("IDENT").value
        self.expect("OVER")
        domain = self.expect("IDENT").value
        preds: list[ast.Pred] = []
        if self.at("WHERE"):
            self.advance()
            preds = self.parse_preds()
        return ast.Grant(refuse, verb, domain, preds, tok.line, tok.col)

    # -- refinement predicates ---------------------------------------------
    def parse_preds(self) -> list[ast.Pred]:
        preds = [self.parse_pred()]
        while self.at("AND"):
            self.advance()
            preds.append(self.parse_pred())
        return preds

    def parse_pred(self) -> ast.Pred:
        tok = self.expect("IDENT")
        kind = tok.value
        if kind == "path":
            self.expect_ident("under")
            val = self.expect("TEXT").value
            return ast.Pred("path", val, tok.line, tok.col)
        if kind == "host":
            self.expect_ident("eq")
            val = self.expect("TEXT").value
            return ast.Pred("host", val, tok.line, tok.col)
        if kind == "bytes_le":
            val = int(self.expect("INT").value)
            return ast.Pred("bytes_le", val, tok.line, tok.col)
        if kind == "total_le":
            val = int(self.expect("INT").value)
            return ast.Pred("total_le", val, tok.line, tok.col)
        raise ParseError(
            f"unknown refinement predicate {kind!r} (expected path/host/bytes_le/total_le)",
            tok.line, tok.col)

    # -- functions ----------------------------------------------------------
    def parse_fn(self) -> ast.FnDecl:
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
        ret = self.parse_type()
        self.expect("ASSIGN")
        body = self.parse_expr()
        return ast.FnDecl(name, params, ret, body, kw.line, kw.col)

    def parse_param(self) -> ast.Param:
        name = self.expect("IDENT").value
        self.expect("COLON")
        return ast.Param(name, self.parse_type())

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

    # -- expressions --------------------------------------------------------
    # Treaty's expression language is deliberately tiny: its subject is the
    # capability protocol, not arithmetic. Values flow through claims,
    # negotiate, matches, method calls, and a few world-free builtins.
    def parse_expr(self) -> ast.Expr:
        return self.parse_postfix()

    def parse_postfix(self) -> ast.Expr:
        expr = self.parse_primary()
        while self.at("DOT"):
            dot = self.advance()
            verb = self.expect("IDENT").value
            self.expect("LPAREN")
            args: list[ast.Expr] = []
            if not self.at("RPAREN"):
                args.append(self.parse_expr())
                while self.at("COMMA"):
                    self.advance()
                    args.append(self.parse_expr())
            self.expect("RPAREN")
            expr = ast.MethodCall(expr, verb, args, dot.line, dot.col)
        return expr

    def parse_primary(self) -> ast.Expr:
        tok = self.peek()
        kind = tok.kind

        if kind == "INT":
            self.advance()
            return ast.IntLit(int(tok.value), tok.line, tok.col)
        if kind == "TEXT":
            self.advance()
            return ast.TextLit(tok.value, tok.line, tok.col)
        if kind == "TRUE":
            self.advance()
            return ast.BoolLit(True, tok.line, tok.col)
        if kind == "FALSE":
            self.advance()
            return ast.BoolLit(False, tok.line, tok.col)
        if kind == "LPAREN":
            self.advance()
            inner = self.parse_expr()
            self.expect("RPAREN")
            return inner
        if kind == "LBRACK":
            return self.parse_list()
        if kind == "LBRACE":
            return self.parse_block()
        if kind == "IF":
            return self.parse_if()
        if kind == "MATCH":
            return self.parse_match()
        if kind == "REGION":
            return self.parse_region()
        if kind == "CLAIM":
            return self.parse_claim()
        if kind == "NEGOTIATE":
            self.advance()
            self.expect("LPAREN")
            inner = self.parse_expr()
            self.expect("RPAREN")
            return ast.Negotiate(inner, tok.line, tok.col)
        if kind == "IDENT":
            return self.parse_ident_expr()

        raise ParseError(f"unexpected token {kind} ({tok.value!r})", tok.line, tok.col)

    def parse_list(self) -> ast.Expr:
        lb = self.expect("LBRACK")
        elems: list[ast.Expr] = []
        if not self.at("RBRACK"):
            elems.append(self.parse_expr())
            while self.at("COMMA"):
                self.advance()
                if self.at("RBRACK"):
                    break
                elems.append(self.parse_expr())
        self.expect("RBRACK")
        return ast.ListLit(elems, lb.line, lb.col)

    def parse_ident_expr(self) -> ast.Expr:
        tok = self.expect("IDENT")
        name = tok.value
        is_upper = name[0].isupper()
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
        if is_upper:
            return ast.Construct(name, [], tok.line, tok.col)
        return ast.Var(name, tok.line, tok.col)

    def parse_claim(self) -> ast.Expr:
        kw = self.expect("CLAIM")
        verb = self.expect("IDENT").value
        self.expect("OVER")
        domain = self.expect("IDENT").value
        preds: list[ast.Pred] = []
        if self.at("WHERE"):
            self.advance()
            preds = self.parse_preds()
        return ast.ClaimExpr(verb, domain, preds, kw.line, kw.col)

    def parse_region(self) -> ast.Expr:
        kw = self.expect("REGION")
        name = self.expect("IDENT").value
        body = self.parse_block()
        return ast.Region(name, body, kw.line, kw.col)

    def parse_block(self) -> ast.Block:
        lb = self.expect("LBRACE")
        statements: list[object] = []
        result: ast.Expr | None = None
        while True:
            if self.at("LET"):
                statements.append(self.parse_let())
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

    def parse_let(self) -> ast.LetStmt:
        kw = self.expect("LET")
        name = self.expect("IDENT").value
        if self.at("COLON"):
            self.advance()
            self.parse_type()  # optional annotation, ignored (inference is used)
        self.expect("ASSIGN")
        value = self.parse_expr()
        return ast.LetStmt(name, value, kw.line, kw.col)

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
        cases = [self.parse_case()]
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
        tok = self.peek()
        kind = tok.kind
        if kind == "IDENT" and tok.value == "_":
            self.advance()
            return ast.Pattern("wildcard", line=tok.line, col=tok.col)
        if kind == "INT":
            self.advance()
            return ast.Pattern("literal", value=int(tok.value), line=tok.line, col=tok.col)
        if kind == "TEXT":
            self.advance()
            return ast.Pattern("literal", value=tok.value, line=tok.line, col=tok.col)
        if kind in ("TRUE", "FALSE"):
            self.advance()
            return ast.Pattern("literal", value=(kind == "TRUE"), line=tok.line, col=tok.col)
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
