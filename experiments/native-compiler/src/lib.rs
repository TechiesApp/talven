//! A bounded port of the reference frontend and hosted C backend for scalars and static text.
//!
//! The lexer, parser, checker, and emitter follow `talven/frontend.py` and `talven/backend.py`
//! in order, codes, messages, and spans. Record declarations are the one unsupported feature
//! (`E0801`); without records, borrow, field, record-literal, assignment, and `let mut` syntax
//! always receives the reference's diagnostics.
use std::collections::BTreeMap;
use std::ops::Range;

pub const PROFILE: &str = "native-scalar-text-v1";
pub const MAX_SOURCE: usize = 256 * 1024;
const MAX_TOKENS: usize = 16384;
const MAX_AST_DEPTH: usize = 128;
/// The reference parser is recursive and reports Python's `RecursionError` as `E0005`. This is
/// the deepest Python-equivalent parser call (function body block = 0) that CPython 3.12 and
/// 3.13 complete from the reference CLI; within a frame or two the boundary is interpreter
/// dependent (3.11 and 3.14 differ by one level).
const MAX_PARSER_FRAMES: usize = 992;
const KEYWORDS: [&str; 9] = [
    "fn", "struct", "let", "mut", "return", "if", "else", "true", "false",
];
const SIZE_LIMIT: &str = "Source exceeds the 256 KiB prototype limit";

#[derive(Debug)]
pub struct Error {
    pub code: &'static str,
    pub message: String,
    pub span: Range<usize>,
}
type Result<T> = std::result::Result<T, Error>;
fn error(code: &'static str, message: impl Into<String>, span: Range<usize>) -> Error {
    Error {
        code,
        message: message.into(),
        span,
    }
}
/// The source-size diagnostic shared with the CLI, which checks bytes before UTF-8 decoding.
pub fn size_error() -> Error {
    error("E0005", SIZE_LIMIT, 0..0)
}
pub fn json(text: &str) -> String {
    let mut out = String::from("\"");
    for ch in text.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            ch if ch < ' ' => out.push_str(&format!("\\u{:04x}", ch as u32)),
            ch => out.push(ch),
        }
    }
    out.push('"');
    out
}
/// Zero-based line and UTF-16 character, like the reference's LSP-compatible positions.
pub fn line_character(source: &str, offset: usize) -> (usize, usize) {
    let prefix = &source[..offset];
    let line = prefix.bytes().filter(|ch| *ch == b'\n').count();
    let column = prefix
        .rsplit('\n')
        .next()
        .unwrap_or("")
        .encode_utf16()
        .count();
    (line, column)
}
fn position(source: &str, offset: usize) -> String {
    let (line, column) = line_character(source, offset);
    format!("{{\"line\":{line},\"character\":{column}}}")
}
pub fn receipt(source: &str, failure: Option<&Error>) -> String {
    let diagnostics = failure.map(|e| format!(
        "{{\"code\":{},\"message\":{},\"severity\":1,\"source\":\"talven-native\",\"range\":{{\"start\":{},\"end\":{}}}}}",
        json(e.code), json(&e.message), position(source, e.span.start), position(source, e.span.end)
    )).unwrap_or_default();
    format!(
        "{{\"schema\":\"talven.diagnostics.v1\",\"profile\":\"{PROFILE}\",\"ok\":{},\"diagnostics\":[{diagnostics}]}}\n",
        failure.is_none()
    )
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum TokenKind {
    Id,
    Int,
    Text,
    Eof,
    /// Keywords and operators, whose kind is their spelling.
    Fixed,
}
#[derive(Clone, Debug)]
struct Token {
    kind: TokenKind,
    text: String,
    span: Range<usize>,
}
impl Token {
    fn kind(&self) -> &str {
        match self.kind {
            TokenKind::Id => "id",
            TokenKind::Int => "int",
            TokenKind::Text => "text",
            TokenKind::Eof => "eof",
            TokenKind::Fixed => &self.text,
        }
    }
}

/// Validate and decode one quoted literal starting at byte `start`.
fn text_literal(source: &str, start: usize) -> Result<(usize, String)> {
    let mut chars = String::new();
    let mut at = start + 1;
    while at < source.len() {
        let ch = source[at..].chars().next().expect("char boundary");
        if ch == '"' {
            return Ok((at + 1, chars));
        }
        if (ch as u32) < 32 || ch as u32 == 127 {
            return Err(error(
                "E0006",
                "Text literals require escapes for control characters and newlines",
                start..at + 1,
            ));
        }
        if ch == '\\' {
            at += 1;
            if at >= source.len() {
                break;
            }
            let escaped = source[at..].chars().next().expect("char boundary");
            at += escaped.len_utf8();
            chars.push(match escaped {
                '"' => '"',
                '\\' => '\\',
                'n' => '\n',
                'r' => '\r',
                't' => '\t',
                '0' => '\0',
                _ => {
                    return Err(error(
                        "E0006",
                        "Unsupported text escape; use \\\", \\\\, \\n, \\r, \\t, or \\0",
                        start..at,
                    ));
                }
            });
        } else {
            at += ch.len_utf8();
            chars.push(ch);
        }
    }
    Err(error("E0006", "Unterminated text literal", start..at))
}

fn is_space(rest: &[u8]) -> bool {
    matches!(rest[0], b' ' | b'\t' | b'\n') || rest.starts_with(b"\r\n")
}

fn lex(source: &str) -> Result<Vec<Token>> {
    if source.len() > MAX_SOURCE {
        return Err(size_error());
    }
    // Bidirectional controls can make displayed code differ from compiled code.
    if let Some((at, ch)) = source
        .char_indices()
        .find(|(_, ch)| matches!(ch, '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}'))
    {
        return Err(error(
            "E0001",
            "Bidirectional control characters are not allowed in source",
            at..at + ch.len_utf8(),
        ));
    }
    let bytes = source.as_bytes();
    let mut tokens = Vec::new();
    let mut at = 0;
    while at < bytes.len() {
        let start = at;
        let rest = &bytes[at..];
        let kind;
        if rest[0] == b'"' {
            at = text_literal(source, at)?.0;
            kind = TokenKind::Text;
        } else if is_space(rest) {
            while at < bytes.len() && is_space(&bytes[at..]) {
                at += if bytes[at] == b'\r' { 2 } else { 1 };
            }
            continue;
        } else if rest.starts_with(b"//") {
            // Comments stop at any CR, so a lone CR cannot hide code inside a comment.
            at += rest
                .iter()
                .position(|b| matches!(b, b'\r' | b'\n'))
                .unwrap_or(rest.len());
            continue;
        } else if rest[0].is_ascii_digit() {
            at += rest.iter().take_while(|b| b.is_ascii_digit()).count();
            kind = TokenKind::Int;
        } else if rest[0].is_ascii_alphabetic() || rest[0] == b'_' {
            at += rest
                .iter()
                .take_while(|b| b.is_ascii_alphanumeric() || **b == b'_')
                .count();
            kind = if KEYWORDS.contains(&&source[start..at]) {
                TokenKind::Fixed
            } else {
                TokenKind::Id
            };
        } else if ["->", "==", "!=", "<=", ">=", "&&", "||"]
            .iter()
            .any(|op| rest.starts_with(op.as_bytes()))
        {
            at += 2;
            kind = TokenKind::Fixed;
        } else if b"{}():;,.+*/%<>=!&-".contains(&rest[0]) {
            at += 1;
            kind = TokenKind::Fixed;
        } else {
            let ch = source[at..].chars().next().expect("char boundary");
            let message = if ch == '\r' {
                "Carriage return must be followed by a line feed"
            } else {
                "Unexpected character"
            };
            return Err(error("E0001", message, at..at + ch.len_utf8()));
        }
        tokens.push(Token {
            kind,
            text: source[start..at].into(),
            span: start..at,
        });
        if tokens.len() > MAX_TOKENS {
            return Err(error(
                "E0005",
                "Source exceeds the prototype token limit",
                start..at,
            ));
        }
    }
    tokens.push(Token {
        kind: TokenKind::Eof,
        text: String::new(),
        span: at..at,
    });
    Ok(tokens)
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Ty {
    Int,
    Bool,
    Text,
}
impl Ty {
    fn name(self) -> &'static str {
        match self {
            Self::Int => "i32",
            Self::Bool => "bool",
            Self::Text => "str",
        }
    }
    fn c(self) -> &'static str {
        match self {
            Self::Int => "int32_t",
            Self::Bool => "bool",
            Self::Text => "tv_str",
        }
    }
}
#[derive(Clone, Debug)]
enum ExprKind {
    Int(String),
    Bool(bool),
    Text(String),
    Name(String),
    Call(String, Vec<usize>),
    Record(String, Vec<usize>),
    Field(String, usize),
    Borrow(usize),
    Unary(String, usize),
    Binary(String, usize, usize),
}
#[derive(Clone, Debug)]
struct Expr {
    kind: ExprKind,
    span: Range<usize>,
    ty: Option<Ty>,
}
impl Expr {
    /// Children in the reference's `[*args, *fields]` order.
    fn children(&self) -> Vec<usize> {
        match &self.kind {
            ExprKind::Call(_, args) | ExprKind::Record(_, args) => args.clone(),
            ExprKind::Field(_, child) | ExprKind::Borrow(child) | ExprKind::Unary(_, child) => {
                vec![*child]
            }
            ExprKind::Binary(_, a, b) => vec![*a, *b],
            _ => Vec::new(),
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq)]
enum StmtKind {
    Let,
    Return,
    If,
    Expr,
    Assign,
}
#[derive(Debug)]
struct Stmt {
    kind: StmtKind,
    span: Range<usize>,
    expr: usize,
    name: Option<Token>,
    annotation: Option<Token>,
    then: Vec<Stmt>,
    otherwise: Vec<Stmt>,
    mutable: bool,
    target: Option<usize>,
}
#[derive(Debug)]
struct Function {
    name: Token,
    params: Vec<(Token, Token)>,
    result: Token,
    body: Vec<Stmt>,
}
#[derive(Debug)]
pub struct Program {
    functions: Vec<Function>,
    signatures: BTreeMap<String, (Vec<Ty>, Ty)>,
    expressions: Vec<Expr>,
    console: bool,
}

fn precedence(kind: &str) -> Option<u8> {
    Some(match kind {
        "||" => 1,
        "&&" => 2,
        "==" | "!=" => 3,
        "<" | ">" | "<=" | ">=" => 4,
        "+" | "-" => 5,
        "*" | "/" | "%" => 6,
        _ => return None,
    })
}

struct Parser {
    tokens: Vec<Token>,
    index: usize,
    expressions: Vec<Expr>,
}
impl Parser {
    fn current(&self) -> &Token {
        &self.tokens[self.index]
    }
    fn previous_end(&self) -> usize {
        self.tokens[self.index - 1].span.end
    }
    fn take(&mut self, kind: &str) -> Result<Token> {
        let token = self.current().clone();
        if token.kind() != kind {
            let found = if token.text.is_empty() {
                "end of file"
            } else {
                &token.text
            };
            return Err(error(
                "E0002",
                format!("Expected {kind}, found {found}"),
                token.span,
            ));
        }
        self.index += 1;
        Ok(token)
    }
    fn accept(&mut self, kind: &str) -> bool {
        if self.current().kind() == kind {
            self.index += 1;
            true
        } else {
            false
        }
    }
    /// Mirror the point where the reference's recursive parser would exhaust Python's stack.
    fn guard(peak: usize) -> Result<()> {
        if peak > MAX_PARSER_FRAMES {
            Err(error(
                "E0005",
                "Expression or block nesting exceeds the prototype limit",
                0..0,
            ))
        } else {
            Ok(())
        }
    }
    fn type_token(&mut self) -> Result<Token> {
        if self.current().kind() != "&" {
            return self.take("id");
        }
        let start = self.take("&")?.span.start;
        let mutable = self.accept("mut");
        let name = self.take("id")?;
        Ok(Token {
            kind: TokenKind::Id,
            text: format!("{}{}", if mutable { "&mut " } else { "&" }, name.text),
            span: start..name.span.end,
        })
    }
    fn pairs(&mut self, end: &str) -> Result<Vec<(Token, Token)>> {
        let mut result = Vec::new();
        while self.current().kind() != end {
            let name = self.take("id")?;
            self.take(":")?;
            result.push((name, self.type_token()?));
            if !self.accept(",") {
                break;
            }
        }
        self.take(end)?;
        Ok(result)
    }
    fn program(&mut self) -> Result<(Vec<Function>, Option<Range<usize>>)> {
        let mut functions = Vec::new();
        let mut record = None;
        while self.current().kind() != "eof" {
            let start = self.current().span.clone();
            if self.accept("struct") {
                self.take("id")?;
                self.take("{")?;
                self.pairs("}")?;
                record.get_or_insert(start);
            } else {
                self.take("fn")?;
                let name = self.take("id")?;
                self.take("(")?;
                let params = self.pairs(")")?;
                self.take("->")?;
                let result = self.type_token()?;
                let body = self.block(0)?;
                functions.push(Function {
                    name,
                    params,
                    result,
                    body,
                });
            }
        }
        Ok((functions, record))
    }
    fn block(&mut self, frame: usize) -> Result<Vec<Stmt>> {
        Self::guard(frame + 2)?;
        self.take("{")?;
        let mut statements = Vec::new();
        while self.current().kind() != "}" {
            let start = self.current().span.start;
            let mut stmt = Stmt {
                kind: StmtKind::Expr,
                span: 0..0,
                expr: 0,
                name: None,
                annotation: None,
                then: Vec::new(),
                otherwise: Vec::new(),
                mutable: false,
                target: None,
            };
            if self.accept("let") {
                stmt.kind = StmtKind::Let;
                stmt.mutable = self.accept("mut");
                stmt.name = Some(self.take("id")?);
                if self.accept(":") {
                    Self::guard(frame + 3)?;
                    stmt.annotation = Some(self.type_token()?);
                }
                self.take("=")?;
                stmt.expr = self.expression(0, frame + 1)?;
                self.take(";")?;
            } else if self.accept("return") {
                stmt.kind = StmtKind::Return;
                stmt.expr = self.expression(0, frame + 1)?;
                self.take(";")?;
            } else if self.accept("if") {
                stmt.kind = StmtKind::If;
                self.take("(")?;
                stmt.expr = self.expression(0, frame + 1)?;
                self.take(")")?;
                stmt.then = self.block(frame + 1)?;
                if self.accept("else") {
                    stmt.otherwise = self.block(frame + 1)?;
                }
            } else {
                stmt.expr = self.expression(0, frame + 1)?;
                if matches!(self.expressions[stmt.expr].kind, ExprKind::Field(..))
                    && self.accept("=")
                {
                    stmt.kind = StmtKind::Assign;
                    stmt.target = Some(stmt.expr);
                    stmt.expr = self.expression(0, frame + 1)?;
                }
                self.take(";")?;
            }
            stmt.span = start..self.previous_end();
            statements.push(stmt);
        }
        self.take("}")?;
        Ok(statements)
    }
    fn add(&mut self, kind: ExprKind, span: Range<usize>) -> usize {
        self.expressions.push(Expr {
            kind,
            span,
            ty: None,
        });
        self.expressions.len() - 1
    }
    fn expression(&mut self, minimum: u8, frame: usize) -> Result<usize> {
        Self::guard(frame + 2)?;
        let token = self.current().clone();
        let mut left;
        if self.accept("&") {
            self.accept("mut");
            let child = self.expression(7, frame + 1)?;
            let end = self.expressions[child].span.end;
            left = self.add(ExprKind::Borrow(child), token.span.start..end);
        } else if matches!(token.kind(), "-" | "!") {
            self.index += 1;
            let child = self.expression(7, frame + 1)?;
            let end = self.expressions[child].span.end;
            left = self.add(
                ExprKind::Unary(token.text.clone(), child),
                token.span.start..end,
            );
        } else if self.accept("(") {
            left = self.expression(0, frame + 1)?;
            self.take(")")?;
        } else if token.kind == TokenKind::Text {
            self.index += 1;
            let value = text_literal(&token.text, 0)?.1;
            left = self.add(ExprKind::Text(value), token.span);
        } else if matches!(token.kind(), "int" | "true" | "false") {
            self.index += 1;
            let kind = if token.kind == TokenKind::Int {
                ExprKind::Int(token.text)
            } else {
                ExprKind::Bool(token.text == "true")
            };
            left = self.add(kind, token.span);
        } else {
            let name = self.take("id")?;
            if self.accept("(") {
                let mut args = Vec::new();
                while self.current().kind() != ")" {
                    args.push(self.expression(0, frame + 1)?);
                    if !self.accept(",") {
                        break;
                    }
                }
                let end = self.take(")")?.span.end;
                left = self.add(ExprKind::Call(name.text, args), name.span.start..end);
            } else if self.accept("{") {
                let mut fields = Vec::new();
                while self.current().kind() != "}" {
                    self.take("id")?;
                    self.take(":")?;
                    fields.push(self.expression(0, frame + 1)?);
                    if !self.accept(",") {
                        break;
                    }
                }
                let end = self.take("}")?.span.end;
                left = self.add(ExprKind::Record(name.text, fields), name.span.start..end);
            } else {
                left = self.add(ExprKind::Name(name.text), name.span);
            }
        }
        loop {
            if self.accept(".") {
                let name = self.take("id")?;
                let start = self.expressions[left].span.start;
                left = self.add(ExprKind::Field(name.text, left), start..name.span.end);
                continue;
            }
            let Some(priority) = precedence(self.current().kind()) else {
                break;
            };
            if priority < minimum {
                break;
            }
            let op = self.current().text.clone();
            self.index += 1;
            let right = self.expression(priority + 1, frame + 1)?;
            let span = self.expressions[left].span.start..self.expressions[right].span.end;
            left = self.add(ExprKind::Binary(op, left, right), span.clone());
            if matches!(priority, 3 | 4) && precedence(self.current().kind()) == Some(priority) {
                return Err(error(
                    "E0002",
                    "Comparisons do not chain; add parentheses",
                    span.start..self.current().span.end,
                ));
            }
        }
        Ok(left)
    }
}

/// The reference's post-parse depth walk: an explicit stack, popped last-first.
fn check_depth(functions: &[Function], expressions: &[Expr]) -> Result<()> {
    enum Node<'a> {
        Stmt(&'a Stmt),
        Expr(usize),
    }
    let mut pending: Vec<(Node, usize)> = functions
        .iter()
        .flat_map(|f| f.body.iter().map(|s| (Node::Stmt(s), 1)))
        .collect();
    while let Some((node, depth)) = pending.pop() {
        if depth > MAX_AST_DEPTH {
            let span = match node {
                Node::Stmt(stmt) => stmt.span.clone(),
                Node::Expr(index) => expressions[index].span.clone(),
            };
            return Err(error(
                "E0005",
                "Syntax tree exceeds the 128-level prototype limit",
                span,
            ));
        }
        match node {
            Node::Stmt(stmt) => {
                pending.push((Node::Expr(stmt.expr), depth + 1));
                pending.extend(stmt.then.iter().map(|s| (Node::Stmt(s), depth + 1)));
                pending.extend(stmt.otherwise.iter().map(|s| (Node::Stmt(s), depth + 1)));
                if let Some(target) = stmt.target {
                    pending.push((Node::Expr(target), depth + 1));
                }
            }
            Node::Expr(index) => pending.extend(
                expressions[index]
                    .children()
                    .into_iter()
                    .map(|c| (Node::Expr(c), depth + 1)),
            ),
        }
    }
    Ok(())
}

fn same(actual: Ty, expected: Ty, span: Range<usize>) -> Result<()> {
    if actual == expected {
        Ok(())
    } else {
        Err(error(
            "E0201",
            format!(
                "Expected {}, found {}; implicit conversions are not supported",
                expected.name(),
                actual.name()
            ),
            span,
        ))
    }
}
fn type_name(token: &Token, parameter: bool) -> Result<Ty> {
    let text = token.text.as_str();
    let base = text
        .strip_prefix("&mut ")
        .or_else(|| text.strip_prefix('&'));
    if base.is_some() && !parameter {
        return Err(error(
            "E0304",
            "Borrowed types are allowed only on function parameters; references cannot escape",
            token.span.clone(),
        ));
    }
    let ty = match base.unwrap_or(text) {
        "i32" => Ty::Int,
        "bool" => Ty::Bool,
        "str" => Ty::Text,
        _ => {
            return Err(error(
                "E0101",
                format!("Unknown type {text}"),
                token.span.clone(),
            ));
        }
    };
    if base.is_some() {
        return Err(error(
            "E0305",
            "Only named records can be borrowed in this profile",
            token.span.clone(),
        ));
    }
    Ok(ty)
}

type Bindings = BTreeMap<String, Ty>;
struct Checker<'a> {
    expressions: &'a mut [Expr],
    signatures: &'a BTreeMap<String, (Vec<Ty>, Ty)>,
    result: Ty,
    console: bool,
}
impl Checker<'_> {
    fn bind(&self, name: &Token, ty: Ty, bindings: &mut Bindings, mutable: bool) -> Result<()> {
        if bindings.contains_key(&name.text) {
            return Err(error(
                "E0102",
                format!("Duplicate or shadowed binding {}", name.text),
                name.span.clone(),
            ));
        }
        if mutable {
            return Err(error(
                "E0305",
                "let mut currently supports owned records with scalar fields",
                name.span.clone(),
            ));
        }
        bindings.insert(name.text.clone(), ty);
        Ok(())
    }
    fn block(&mut self, body: &[Stmt], bindings: &mut Bindings) -> Result<bool> {
        let mut reachable = true;
        for stmt in body {
            if !reachable {
                return Err(error("E0206", "Unreachable statement", stmt.span.clone()));
            }
            if stmt.kind == StmtKind::Assign {
                self.assignment(stmt, bindings)?;
                continue;
            }
            let ty = self.expr(stmt.expr, bindings)?;
            let span = self.expressions[stmt.expr].span.clone();
            match stmt.kind {
                StmtKind::Let => {
                    if let Some(annotation) = &stmt.annotation {
                        same(ty, type_name(annotation, false)?, span)?;
                    }
                    let name = stmt.name.as_ref().expect("let name");
                    self.bind(name, ty, bindings, stmt.mutable)?;
                }
                StmtKind::Return => {
                    same(ty, self.result, span)?;
                    reachable = false;
                }
                StmtKind::If => {
                    same(ty, Ty::Bool, span)?;
                    let then_live = self.block(&stmt.then, &mut bindings.clone())?;
                    let else_live = self.block(&stmt.otherwise, &mut bindings.clone())?;
                    reachable = then_live || else_live;
                }
                StmtKind::Expr | StmtKind::Assign => (),
            }
        }
        Ok(reachable)
    }
    fn assignment(&mut self, stmt: &Stmt, bindings: &Bindings) -> Result<()> {
        let target = stmt.target.expect("assignment target");
        let place = match &self.expressions[target].kind {
            ExprKind::Field(_, place) => *place,
            _ => unreachable!("assignment targets are fields"),
        };
        if !matches!(self.expressions[place].kind, ExprKind::Name(_)) {
            return Err(error(
                "E0305",
                "Assignment requires a scalar field of a named record binding",
                self.expressions[target].span.clone(),
            ));
        }
        // Without records, a scalar binding has no field to assign.
        self.expr(target, bindings)?;
        unreachable!("fields of scalar bindings are always rejected")
    }
    fn lookup(&self, index: usize, bindings: &Bindings) -> Result<Ty> {
        let expr = &self.expressions[index];
        let ExprKind::Name(name) = &expr.kind else {
            unreachable!("lookup of a name")
        };
        bindings.get(name).copied().ok_or_else(|| {
            error(
                "E0101",
                format!("Unknown binding {name}"),
                expr.span.clone(),
            )
        })
    }
    /// A borrow argument always fails without records; report the reference's first reason.
    fn borrow(&self, index: usize, bindings: &Bindings) -> Result<Ty> {
        let ExprKind::Borrow(place) = self.expressions[index].kind else {
            unreachable!("borrow expression")
        };
        let span = self.expressions[place].span.clone();
        if !matches!(self.expressions[place].kind, ExprKind::Name(_)) {
            return Err(error(
                "E0305",
                "Borrow a named record binding; temporaries, fields, and nested references are unsupported",
                span,
            ));
        }
        self.lookup(place, bindings)?;
        Err(error(
            "E0305",
            "Only named records can be borrowed in this profile",
            span,
        ))
    }
    fn argument(&mut self, index: usize, bindings: &Bindings) -> Result<Ty> {
        if matches!(self.expressions[index].kind, ExprKind::Borrow(_)) {
            self.borrow(index, bindings)
        } else {
            self.expr(index, bindings)
        }
    }
    fn expr(&mut self, index: usize, bindings: &Bindings) -> Result<Ty> {
        let expr = self.expressions[index].clone();
        let span = expr.span.clone();
        let ty = match expr.kind {
            ExprKind::Int(value) => {
                let digits = value.trim_start_matches('0');
                if digits.len() > 10 || digits.parse::<u64>().unwrap_or_default() > i32::MAX as u64
                {
                    return Err(error(
                        "E0202",
                        "Integer literal is outside the i32 range",
                        span,
                    ));
                }
                Ty::Int
            }
            ExprKind::Bool(_) => Ty::Bool,
            ExprKind::Text(_) => Ty::Text,
            ExprKind::Name(_) => self.lookup(index, bindings)?,
            ExprKind::Field(name, child) => {
                let base = self.expr(child, bindings)?;
                return Err(error(
                    "E0101",
                    format!("Type {} has no field {name}", base.name()),
                    span,
                ));
            }
            ExprKind::Record(name, _) => {
                return Err(error("E0101", format!("Unknown record {name}"), span));
            }
            ExprKind::Call(name, args) if name == "print" => {
                if args.len() != 1 {
                    return Err(error("E0203", "print expects 1 argument", span));
                }
                let actual = self.argument(args[0], bindings)?;
                same(actual, Ty::Text, self.expressions[args[0]].span.clone())?;
                self.console = true;
                Ty::Int
            }
            ExprKind::Call(name, args) => {
                let (params, result) = self.signatures.get(&name).cloned().ok_or_else(|| {
                    error("E0101", format!("Unknown function {name}"), span.clone())
                })?;
                if args.len() != params.len() {
                    return Err(error(
                        "E0203",
                        format!("{name} expects {} arguments", params.len()),
                        span,
                    ));
                }
                for (arg, expected) in args.iter().zip(params) {
                    let actual = self.argument(*arg, bindings)?;
                    same(actual, expected, self.expressions[*arg].span.clone())?;
                }
                result
            }
            ExprKind::Borrow(_) => {
                return Err(error(
                    "E0304",
                    "Borrow expressions are allowed only as direct call arguments; references cannot be stored or returned",
                    span,
                ));
            }
            ExprKind::Unary(op, child) => {
                if op == "-"
                    && matches!(&self.expressions[child].kind, ExprKind::Int(v) if v.trim_start_matches('0') == "2147483648")
                {
                    self.expressions[child].ty = Some(Ty::Int);
                    Ty::Int
                } else {
                    let expected = if op == "-" { Ty::Int } else { Ty::Bool };
                    let actual = self.expr(child, bindings)?;
                    same(actual, expected, self.expressions[child].span.clone())?;
                    expected
                }
            }
            ExprKind::Binary(op, a, b) => {
                let left = self.expr(a, bindings)?;
                let right = self.expr(b, bindings)?;
                let (a_span, b_span) = (
                    self.expressions[a].span.clone(),
                    self.expressions[b].span.clone(),
                );
                match op.as_str() {
                    "&&" | "||" => {
                        same(left, Ty::Bool, a_span)?;
                        same(right, Ty::Bool, b_span)?;
                        Ty::Bool
                    }
                    "==" | "!=" => {
                        if left == Ty::Text {
                            return Err(error(
                                "E0204",
                                "Equality currently supports only i32 and bool",
                                span,
                            ));
                        }
                        same(right, left, b_span)?;
                        Ty::Bool
                    }
                    _ => {
                        same(left, Ty::Int, a_span)?;
                        same(right, Ty::Int, b_span)?;
                        if matches!(op.as_str(), "<" | ">" | "<=" | ">=") {
                            Ty::Bool
                        } else {
                            Ty::Int
                        }
                    }
                }
            }
        };
        self.expressions[index].ty = Some(ty);
        Ok(ty)
    }
}

pub fn analyze(source: &str) -> Result<Program> {
    let mut parser = Parser {
        tokens: lex(source)?,
        index: 0,
        expressions: Vec::new(),
    };
    let (functions, record) = parser.program()?;
    let mut expressions = parser.expressions;
    check_depth(&functions, &expressions)?;
    if let Some(span) = record {
        return Err(error(
            "E0801",
            "Native experiment does not support struct declarations or records; use the reference compiler",
            span,
        ));
    }
    let mut names = vec!["i32", "bool", "str", "print"];
    for f in &functions {
        if names.contains(&f.name.text.as_str()) {
            return Err(error(
                "E0102",
                format!("Duplicate or reserved declaration {}", f.name.text),
                f.name.span.clone(),
            ));
        }
        names.push(&f.name.text);
    }
    let mut signatures = BTreeMap::new();
    for f in &functions {
        let result = type_name(&f.result, false)?;
        let params = f
            .params
            .iter()
            .map(|(_, ty)| type_name(ty, true))
            .collect::<Result<Vec<_>>>()?;
        signatures.insert(f.name.text.clone(), (params, result));
    }
    let mut console = false;
    for f in &functions {
        let (params, result) = signatures[&f.name.text].clone();
        let mut checker = Checker {
            expressions: &mut expressions,
            signatures: &signatures,
            result,
            console,
        };
        let mut bindings = Bindings::new();
        for ((name, _), ty) in f.params.iter().zip(params) {
            checker.bind(name, ty, &mut bindings, false)?;
        }
        if checker.block(&f.body, &mut bindings)? {
            return Err(error(
                "E0205",
                format!(
                    "Function {} must return {} on every path",
                    f.name.text, f.result.text
                ),
                f.name.span.clone(),
            ));
        }
        console = checker.console;
    }
    Ok(Program {
        functions,
        signatures,
        expressions,
        console,
    })
}

/// Checked arithmetic helpers, in the reference's definition order.
const HELPER_NAMES: [&str; 7] = [
    "tv_narrow",
    "tv_add",
    "tv_sub",
    "tv_mul",
    "tv_neg",
    "tv_div",
    "tv_mod",
];
const HOSTED_TRAP: &str = "static _Noreturn void talven_trap(void) { abort(); }";
const HEADER: [&str; 8] = [
    "/* Generated by the Talven static-text prototype. */",
    "#include <stdint.h>",
    "#include <stdbool.h>",
    "#include <stddef.h>",
    "typedef struct { const uint8_t *data; size_t len; } tv_str;",
    "#include <stdlib.h>",
    "#include <limits.h>",
    "_Static_assert(INT_MAX >= INT32_MAX, \"Talven hosted entry requires at least 32-bit int\");",
];
/// `runtime.c` holds a comment and then one helper per blank-line-separated chunk.
fn helper_definitions() -> Vec<&'static str> {
    let chunks: Vec<_> = include_str!("runtime.c")
        .trim_end()
        .split("\n\n")
        .skip(1)
        .collect();
    assert_eq!(chunks.len(), HELPER_NAMES.len(), "runtime.c helper layout");
    chunks
}
fn console_definition() -> &'static str {
    // The first line of console.c is a provenance comment, not emitted.
    include_str!("console.c")
        .split_once('\n')
        .expect("console.c layout")
        .1
}

struct Emitter<'a> {
    expressions: &'a [Expr],
    lines: Vec<String>,
    indent: usize,
    counter: usize,
    used: [bool; 7],
}
impl Emitter<'_> {
    fn line(&mut self, text: impl AsRef<str>) {
        self.lines
            .push(format!("{}{}", "    ".repeat(self.indent), text.as_ref()));
    }
    fn temp(&mut self, ty: Ty, value: String) -> String {
        self.counter += 1;
        let name = format!("tv_tmp_{}", self.counter);
        self.line(format!("{} {name} = {value};", ty.c()));
        name
    }
    fn helper(&mut self, name: &str) -> String {
        let index = HELPER_NAMES.iter().position(|h| h[3..] == *name);
        self.used[index.expect("known helper")] = true;
        format!("tv_{name}")
    }
    fn expr(&mut self, index: usize) -> String {
        let expr = &self.expressions[index];
        let ty = expr.ty.expect("checked expression");
        match &expr.kind {
            ExprKind::Int(value) => {
                let digits = value.trim_start_matches('0');
                let value: u32 = if digits.is_empty() {
                    0
                } else {
                    digits.parse().expect("checked i32 literal")
                };
                format!("INT32_C({value})")
            }
            ExprKind::Bool(value) => value.to_string(),
            ExprKind::Name(name) => self.temp(ty, format!("tv_v_{name}")),
            ExprKind::Text(value) => {
                self.counter += 1;
                let name = format!("tv_text_{}", self.counter);
                self.line(format!("static const uint8_t {name}[] = {{"));
                for chunk in value.as_bytes().chunks(16) {
                    let bytes = chunk
                        .iter()
                        .map(|b| format!("0x{b:02x}"))
                        .collect::<Vec<_>>()
                        .join(", ");
                    self.line(format!("    {bytes},"));
                }
                if value.is_empty() {
                    self.line("    0");
                }
                self.line("};");
                self.temp(Ty::Text, format!("(tv_str){{{name}, {}}}", value.len()))
            }
            ExprKind::Call(name, args) => {
                let values = args.iter().map(|a| self.expr(*a)).collect::<Vec<_>>();
                let callee = if name == "print" {
                    "tv_console_print".into()
                } else {
                    format!("tv_f_{name}")
                };
                self.temp(ty, format!("{callee}({})", values.join(", ")))
            }
            ExprKind::Unary(op, child) => {
                if op == "-"
                    && matches!(&self.expressions[*child].kind, ExprKind::Int(v) if v.trim_start_matches('0') == "2147483648")
                {
                    return "INT32_MIN".into();
                }
                let operand = self.expr(*child);
                let value = if op == "-" {
                    format!("{}({operand})", self.helper("neg"))
                } else {
                    format!("!({operand})")
                };
                self.temp(ty, value)
            }
            ExprKind::Binary(op, a, b) => {
                let left = self.expr(*a);
                if op == "&&" || op == "||" {
                    let result = self.temp(Ty::Bool, left);
                    let negate = if op == "||" { "!" } else { "" };
                    self.line(format!("if ({negate}{result}) {{"));
                    self.indent += 1;
                    let right = self.expr(*b);
                    self.line(format!("{result} = {right};"));
                    self.indent -= 1;
                    self.line("}");
                    return result;
                }
                let right = self.expr(*b);
                let helper = match op.as_str() {
                    "+" => Some("add"),
                    "-" => Some("sub"),
                    "*" => Some("mul"),
                    "/" => Some("div"),
                    "%" => Some("mod"),
                    _ => None,
                };
                let value = match helper {
                    Some(h) => format!("{}({left}, {right})", self.helper(h)),
                    None => format!("({left}) {op} ({right})"),
                };
                self.temp(ty, value)
            }
            ExprKind::Record(..) | ExprKind::Field(..) | ExprKind::Borrow(_) => {
                unreachable!("rejected by the checker")
            }
        }
    }
    fn block(&mut self, body: &[Stmt]) {
        for stmt in body {
            let value = self.expr(stmt.expr);
            match stmt.kind {
                StmtKind::Let => {
                    let name = &stmt.name.as_ref().expect("let name").text;
                    let ty = self.expressions[stmt.expr].ty.expect("checked let");
                    self.line(format!("{} tv_v_{name} = {value};", ty.c()));
                    self.line(format!("(void)tv_v_{name};"));
                }
                StmtKind::Return => self.line(format!("return {value};")),
                StmtKind::Expr => self.line(format!("(void)({value});")),
                StmtKind::If => {
                    self.line(format!("if ({value}) {{"));
                    self.indent += 1;
                    self.block(&stmt.then);
                    self.indent -= 1;
                    self.line("} else {");
                    self.indent += 1;
                    self.block(&stmt.otherwise);
                    self.indent -= 1;
                    self.line("}");
                }
                StmtKind::Assign => unreachable!("rejected by the checker"),
            }
        }
    }
}
fn signature(program: &Program, f: &Function) -> String {
    let (params, result) = &program.signatures[&f.name.text];
    let params = f
        .params
        .iter()
        .zip(params)
        .map(|((name, _), ty)| format!("{} tv_v_{}", ty.c(), name.text))
        .collect::<Vec<_>>()
        .join(", ");
    let params = if params.is_empty() {
        "void".into()
    } else {
        params
    };
    format!("{} tv_f_{}({params})", result.c(), f.name.text)
}
pub fn emit_c(program: &Program, console: bool) -> Result<String> {
    if program.console && !console {
        return Err(error(
            "E0404",
            "print requires hosted POSIX console support; enable --console",
            0..0,
        ));
    }
    let main = program.functions.iter().find(|f| f.name.text == "main");
    if !main.is_some_and(|f| f.params.is_empty() && f.result.text == "i32") {
        return Err(error(
            "E0401",
            "A hosted executable requires fn main() -> i32",
            main.map_or(0..0, |f| f.name.span.clone()),
        ));
    }
    let mut emitter = Emitter {
        expressions: &program.expressions,
        lines: HEADER.iter().map(|line| line.to_string()).collect(),
        indent: 0,
        counter: 0,
        used: [false; 7],
    };
    if program.console {
        emitter.lines.push(console_definition().into());
    }
    let helpers_at = emitter.lines.len();
    for f in &program.functions {
        emitter.line(format!("{};", signature(program, f)));
    }
    for f in &program.functions {
        emitter.line(format!("{} {{", signature(program, f)));
        emitter.indent += 1;
        for (name, _) in &f.params {
            emitter.line(format!("(void)tv_v_{};", name.text));
        }
        emitter.block(&f.body);
        emitter.indent -= 1;
        emitter.line("}");
    }
    emitter.line("int main(void) { return (int)tv_f_main(); }");
    let mut used = emitter.used;
    // add, sub, mul, and neg narrow through tv_narrow.
    used[0] = used[1..5].iter().any(|u| *u);
    let definitions = helper_definitions();
    let mut helpers: Vec<String> = (0..HELPER_NAMES.len())
        .filter(|i| used[*i])
        .map(|i| definitions[i].to_string())
        .collect();
    if !helpers.is_empty() {
        helpers.insert(0, HOSTED_TRAP.into());
    }
    emitter.lines.splice(helpers_at..helpers_at, helpers);
    Ok(emitter.lines.join("\n") + "\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn failure(source: &str) -> (&'static str, String, Range<usize>) {
        let e = analyze(source).expect_err("expected a diagnostic");
        (e.code, e.message, e.span)
    }

    #[test]
    fn helper_layout_matches_names() {
        let definitions = helper_definitions();
        for (name, definition) in HELPER_NAMES.iter().zip(definitions) {
            assert!(definition.starts_with(&format!("static inline int32_t {name}(")));
        }
        assert!(console_definition().starts_with("\n#include <errno.h>\n"));
    }

    #[test]
    fn carriage_returns_and_bidi_controls() {
        assert!(analyze("fn f() -> i32 {\r\n return 0; }").is_ok());
        let lone = failure("fn f() -> i32 { return 0; }\r");
        assert_eq!(("E0001", 27..28), (lone.0, lone.2));
        assert_eq!(
            "Carriage return must be followed by a line feed",
            lone.1.as_str()
        );
        let comment = failure("// hidden\rfn");
        assert_eq!(9..10, comment.2);
        let bidi = failure("fn f() -> str { return \"\u{202e}\"; }");
        assert_eq!(("E0001", 24..27), (bidi.0, bidi.2));
        let nbsp = failure("fn\u{a0}f() -> i32 { return 0; }");
        assert_eq!(("E0001", "Unexpected character"), (nbsp.0, nbsp.1.as_str()));
        let raw_cr = failure("fn f() -> str { return \"a\rb\"; }");
        assert_eq!("E0006", raw_cr.0);
    }

    #[test]
    fn chained_comparisons_are_rejected() {
        let source = "fn f(a: i32) -> bool { return a < 1 < 2; }";
        let (code, message, span) = failure(source);
        assert_eq!(
            ("E0002", "Comparisons do not chain; add parentheses"),
            (code, message.as_str())
        );
        assert_eq!(30..37, span);
        assert!(analyze("fn f(a: bool) -> bool { return a == 1 < 2; }").is_ok());
    }

    #[test]
    fn parentheses_do_not_count_toward_tree_depth() {
        let nested = format!(
            "fn f() -> i32 {{ return {}1{}; }}",
            "(".repeat(127),
            ")".repeat(127)
        );
        assert!(analyze(&nested).is_ok());
        let chain = format!("fn f() -> i32 {{ return {}; }}", ["1"; 200].join("+"));
        assert_eq!("E0005", failure(&chain).0);
    }

    #[test]
    fn let_mut_and_record_syntax_follow_the_reference() {
        let (code, _, span) = failure("fn f() -> i32 { let mut x = 1; return x; }");
        assert_eq!(("E0305", 24..25), (code, span));
        assert_eq!("E0801", failure("struct A { x: i32 }").0);
        assert_eq!("E0101", failure("fn f(x: i32) -> i32 { return x.y; }").0);
    }

    #[test]
    fn only_referenced_helpers_are_emitted() {
        let quiet = emit_c(&analyze("fn main() -> i32 { return 0; }").unwrap(), false).unwrap();
        assert!(!quiet.contains("talven_trap") && !quiet.contains("tv_narrow"));
        let div = emit_c(
            &analyze("fn main() -> i32 { return 4 / 2; }").unwrap(),
            false,
        )
        .unwrap();
        assert!(div.contains(HOSTED_TRAP) && div.contains("tv_div(") && !div.contains("tv_narrow"));
        let neg = emit_c(
            &analyze("fn main() -> i32 { return -(1); }").unwrap(),
            false,
        )
        .unwrap();
        assert!(neg.contains("tv_narrow(int64_t") && !neg.contains("tv_add("));
    }
}
