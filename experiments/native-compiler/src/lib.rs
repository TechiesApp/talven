//! A bounded port of the reference frontend and hosted C backend for scalars, static text,
//! and by-value records.
//!
//! The lexer, parser, checker, and emitter follow `talven/frontend.py` and `talven/backend.py`
//! in order, codes, messages, and spans. Records are affine by-value values with scalar fields.
//! Named record borrows are explicit, call-scoped, and nonescaping; ordered lowering
//! preserves loan scope and mutations without a runtime borrow registry.
use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write;
use std::ops::Range;

mod format;
pub use format::{format_outcomes, format_source};
mod c_api;
pub use c_api::emit_c_api;
mod input;
pub use input::read_source;
mod edit;
pub use edit::{snapshot_source, validate_edit};
mod context;
pub use context::SOURCE_FILES;
pub use context::{ContextOptions, compiler_hash, native_context, source_hash};

pub const PROFILE: &str = "native-call-borrows-v1";
pub const MAX_SOURCE: usize = 256 * 1024;
const MAX_TOKENS: usize = 16384;
const MAX_AST_DEPTH: usize = 128;
/// Active block/expression parses, counting a function body as 1, as in the reference.
const MAX_NESTING: usize = 256;
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
    Comment,
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
            TokenKind::Comment => "comment",
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
    lex_with_comments(source, false)
}

fn lex_with_comments(source: &str, include_comments: bool) -> Result<Vec<Token>> {
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
            if !include_comments {
                continue;
            }
            kind = TokenKind::Comment;
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
    /// An index into the program's record declarations.
    Record(usize),
    Borrowed(usize, bool),
}
impl Ty {
    fn is_copy(self) -> bool {
        !matches!(self, Self::Record(_))
    }
    fn name(self, records: &[Record]) -> String {
        match self {
            Self::Int => "i32".into(),
            Self::Bool => "bool".into(),
            Self::Text => "str".into(),
            Self::Record(index) => records[index].name.text.clone(),
            Self::Borrowed(index, exclusive) => format!(
                "{}{}",
                if exclusive { "&mut " } else { "&" },
                records[index].name.text
            ),
        }
    }
    fn record(self) -> Option<usize> {
        match self {
            Self::Record(index) | Self::Borrowed(index, _) => Some(index),
            _ => None,
        }
    }
    fn c(self, records: &[Record]) -> String {
        match self {
            Self::Int => "int32_t".into(),
            Self::Bool => "bool".into(),
            Self::Text => "tv_str".into(),
            Self::Record(index) => format!("struct tv_s_{}", records[index].name.text),
            Self::Borrowed(index, exclusive) => format!(
                "{}struct tv_s_{} *",
                if exclusive { "" } else { "const " },
                records[index].name.text
            ),
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
    /// A record literal: its name, then each written field label and value in source order.
    Record(String, Vec<(Token, usize)>),
    Outcome(String, Token, Option<usize>),
    Field(String, usize),
    Borrow(bool, usize),
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
            ExprKind::Call(_, args) => args.clone(),
            ExprKind::Outcome(_, _, payload) => payload.iter().copied().collect(),
            ExprKind::Record(_, fields) => fields.iter().map(|(_, value)| *value).collect(),
            ExprKind::Field(_, child) | ExprKind::Borrow(_, child) | ExprKind::Unary(_, child) => {
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
    Match,
}
#[derive(Debug)]
struct MatchArm {
    outcome: Token,
    variant: Token,
    binding: Option<Token>,
    body: Vec<Stmt>,
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
    arms: Vec<MatchArm>,
}
#[derive(Debug)]
pub struct Record {
    name: Token,
    fields: Vec<(Token, Token)>,
    /// Field names and types, resolved once every declaration is validated.
    resolved: Vec<(String, Ty)>,
    /// Present only in the explicitly selected concrete-outcome profile.
    variants: Option<Vec<(Token, Option<Token>)>>,
}
#[derive(Debug)]
struct Function {
    span: Range<usize>,
    name: Token,
    params: Vec<(Token, Token)>,
    result: Token,
    body: Vec<Stmt>,
}
#[derive(Debug)]
pub struct Program {
    records: Vec<Record>,
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
    outcomes: bool,
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
    /// The reference's explicit nesting limit; `frame` is 0 for a function body block.
    fn guard(&self, frame: usize) -> Result<()> {
        if frame + 1 > MAX_NESTING {
            Err(error(
                "E0005",
                format!(
                    "Expression or block nesting exceeds the {MAX_NESTING}-level prototype limit"
                ),
                self.current().span.clone(),
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
    fn program(&mut self) -> Result<(Vec<Record>, Vec<Function>)> {
        let mut records = Vec::new();
        let mut functions = Vec::new();
        while self.current().kind() != "eof" {
            if self.outcomes && self.accept("outcome") {
                let name = self.take("id")?;
                self.take("{")?;
                let mut variants = Vec::new();
                while self.current().kind() != "}" {
                    let variant = self.take("id")?;
                    let payload = if self.accept("(") {
                        let ty = self.type_token()?;
                        self.take(")")?;
                        Some(ty)
                    } else {
                        None
                    };
                    variants.push((variant, payload));
                    if !self.accept(",") {
                        break;
                    }
                }
                self.take("}")?;
                records.push(Record {
                    name,
                    fields: Vec::new(),
                    resolved: Vec::new(),
                    variants: Some(variants),
                });
            } else if self.accept("struct") {
                let name = self.take("id")?;
                self.take("{")?;
                let fields = self.pairs("}")?;
                records.push(Record {
                    name,
                    fields,
                    resolved: Vec::new(),
                    variants: None,
                });
            } else {
                let start = self.take("fn")?.span.start;
                let name = self.take("id")?;
                self.take("(")?;
                let params = self.pairs(")")?;
                self.take("->")?;
                let result = self.type_token()?;
                let body = self.block(0)?;
                functions.push(Function {
                    span: start..self.tokens[self.index - 1].span.end,
                    name,
                    params,
                    result,
                    body,
                });
            }
        }
        Ok((records, functions))
    }
    fn block(&mut self, frame: usize) -> Result<Vec<Stmt>> {
        self.guard(frame)?;
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
                arms: Vec::new(),
            };
            if self.outcomes && self.accept("match") {
                stmt.kind = StmtKind::Match;
                self.take("(")?;
                stmt.expr = self.expression(0, frame + 1)?;
                self.take(")")?;
                self.take("{")?;
                while self.current().kind() != "}" {
                    let outcome = self.take("id")?;
                    self.take(":")?;
                    self.take(":")?;
                    let variant = self.take("id")?;
                    let binding = if self.accept("(") {
                        let name = self.take("id")?;
                        self.take(")")?;
                        Some(name)
                    } else {
                        None
                    };
                    let body = self.block(frame + 1)?;
                    stmt.arms.push(MatchArm {
                        outcome,
                        variant,
                        binding,
                        body,
                    });
                }
                self.take("}")?;
            } else if self.accept("let") {
                stmt.kind = StmtKind::Let;
                stmt.mutable = self.accept("mut");
                stmt.name = Some(self.take("id")?);
                if self.accept(":") {
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
                if self.accept("=") {
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
    fn outcome_expression(&mut self, name: Token, frame: usize) -> Result<usize> {
        self.take(":")?;
        let variant = self.take("id")?;
        let payload = if self.accept("(") {
            let expr = self.expression(0, frame + 1)?;
            self.take(")")?;
            Some(expr)
        } else {
            None
        };
        let span = name.span.start..self.previous_end();
        Ok(self.add(ExprKind::Outcome(name.text, variant, payload), span))
    }
    fn expression(&mut self, minimum: u8, frame: usize) -> Result<usize> {
        self.guard(frame)?;
        let token = self.current().clone();
        let mut left;
        if self.accept("&") {
            let exclusive = self.accept("mut");
            let child = self.expression(7, frame + 1)?;
            let end = self.expressions[child].span.end;
            left = self.add(ExprKind::Borrow(exclusive, child), token.span.start..end);
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
            if self.outcomes && self.accept(":") {
                left = self.outcome_expression(name, frame)?;
            } else if self.accept("(") {
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
                    let key = self.take("id")?;
                    self.take(":")?;
                    fields.push((key, self.expression(0, frame + 1)?));
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
                pending.extend(
                    stmt.arms
                        .iter()
                        .flat_map(|a| a.body.iter())
                        .map(|s| (Node::Stmt(s), depth + 1)),
                );
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

fn same(actual: Ty, expected: Ty, span: Range<usize>, records: &[Record]) -> Result<()> {
    if actual == expected {
        Ok(())
    } else {
        Err(error(
            "E0201",
            format!(
                "Expected {}, found {}; implicit conversions are not supported",
                expected.name(records),
                actual.name(records)
            ),
            span,
        ))
    }
}
fn type_name(token: &Token, parameter: bool, records: &BTreeMap<String, usize>) -> Result<Ty> {
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
        name => match records.get(name) {
            Some(index) => Ty::Record(*index),
            None => {
                return Err(error(
                    "E0101",
                    format!("Unknown type {text}"),
                    token.span.clone(),
                ));
            }
        },
    };
    match (base, ty) {
        (None, _) => Ok(ty),
        (Some(_), Ty::Record(index)) => Ok(Ty::Borrowed(index, text.starts_with("&mut "))),
        (Some(_), _) => Err(error(
            "E0305",
            "Only named records can be borrowed in this profile",
            token.span.clone(),
        )),
    }
}
/// Local bindings and the owned records that may have moved on some path.
#[derive(Clone, Default)]
struct State {
    bindings: BTreeMap<String, Ty>,
    declarations: BTreeMap<String, Range<usize>>,
    moved: BTreeSet<String>,
    mutable: BTreeSet<String>,
    loans: BTreeMap<String, bool>,
}
struct Checker<'a> {
    expressions: &'a mut [Expr],
    signatures: &'a BTreeMap<String, (Vec<Ty>, Ty)>,
    records: &'a [Record],
    record_index: &'a BTreeMap<String, usize>,
    result: Ty,
    console: bool,
}
impl Checker<'_> {
    fn outcome(&self, ty: Ty) -> Option<usize> {
        ty.record().filter(|i| self.records[*i].variants.is_some())
    }
    fn handled<'a>(&self, state: &State, names: impl Iterator<Item = &'a String>) -> Result<()> {
        for name in names {
            if !state.moved.contains(name) && self.outcome(state.bindings[name]).is_some() {
                return Err(error(
                    "E0311",
                    format!("Outcome {name} leaves scope unhandled"),
                    state.declarations[name].clone(),
                ));
            }
        }
        Ok(())
    }
    fn join(&self, state: &mut State, survivors: &[State], span: Range<usize>) -> Result<()> {
        for (name, ty) in &state.bindings {
            if self.outcome(*ty).is_some() && !survivors.is_empty() {
                let first = survivors[0].moved.contains(name);
                if survivors.iter().any(|s| s.moved.contains(name) != first) {
                    return Err(error(
                        "E0311",
                        format!(
                            "Outcome {name} must be handled consistently on continuing branches"
                        ),
                        span,
                    ));
                }
            }
        }
        for branch in survivors {
            state.moved.extend(
                branch
                    .moved
                    .iter()
                    .filter(|name| state.bindings.contains_key(*name))
                    .cloned(),
            );
        }
        Ok(())
    }
    fn same(&self, actual: Ty, expected: Ty, span: Range<usize>) -> Result<()> {
        same(actual, expected, span, self.records)
    }
    fn bind(&self, name: &Token, ty: Ty, state: &mut State, mutable: bool) -> Result<()> {
        if state.bindings.contains_key(&name.text) {
            return Err(error(
                "E0102",
                format!("Duplicate or shadowed binding {}", name.text),
                name.span.clone(),
            ));
        }
        if mutable && (ty == Ty::Text || self.outcome(ty).is_some()) {
            return Err(error(
                "E0305",
                "let mut supports i32, bool, or owned records with scalar fields",
                name.span.clone(),
            ));
        }
        if mutable {
            state.mutable.insert(name.text.clone());
        }
        state.bindings.insert(name.text.clone(), ty);
        state
            .declarations
            .insert(name.text.clone(), name.span.clone());
        Ok(())
    }
    fn block(&mut self, body: &[Stmt], state: &mut State) -> Result<bool> {
        let initial: BTreeSet<String> = state.bindings.keys().cloned().collect();
        let mut reachable = true;
        for stmt in body {
            if !reachable {
                return Err(error("E0206", "Unreachable statement", stmt.span.clone()));
            }
            if stmt.kind == StmtKind::Assign {
                self.assignment(stmt, state)?;
                continue;
            }
            let ty = self.expr(stmt.expr, state, true)?;
            let span = self.expressions[stmt.expr].span.clone();
            match stmt.kind {
                StmtKind::Let => {
                    if let Some(annotation) = &stmt.annotation {
                        self.same(ty, type_name(annotation, false, self.record_index)?, span)?;
                    }
                    let name = stmt.name.as_ref().expect("let name");
                    self.bind(name, ty, state, stmt.mutable)?;
                }
                StmtKind::Return => {
                    self.same(ty, self.result, span)?;
                    self.handled(state, state.bindings.keys())?;
                    reachable = false;
                }
                StmtKind::If => {
                    self.same(ty, Ty::Bool, span)?;
                    let mut then = state.clone();
                    let mut otherwise = state.clone();
                    let then_live = self.block(&stmt.then, &mut then)?;
                    let else_live = self.block(&stmt.otherwise, &mut otherwise)?;
                    let survivors: Vec<State> = [(then, then_live), (otherwise, else_live)]
                        .into_iter()
                        .filter_map(|(s, live)| live.then_some(s))
                        .collect();
                    self.join(state, &survivors, stmt.span.clone())?;
                    reachable = then_live || else_live;
                }
                StmtKind::Match => {
                    let record = self
                        .outcome(ty)
                        .ok_or_else(|| error("E0310", "match requires an owned outcome", span))?;
                    let variants = self.records[record].variants.as_ref().unwrap().clone();
                    let mut seen = BTreeSet::new();
                    let mut survivors = Vec::new();
                    for arm in &stmt.arms {
                        if arm.outcome.text != self.records[record].name.text {
                            return Err(error(
                                "E0201",
                                format!(
                                    "Expected {}, found {}; implicit conversions are not supported",
                                    self.records[record].name.text, arm.outcome.text
                                ),
                                arm.outcome.span.clone(),
                            ));
                        }
                        let variant = variants.iter().find(|(n, _)| n.text == arm.variant.text);
                        if !seen.insert(arm.variant.text.clone()) || variant.is_none() {
                            return Err(error(
                                "E0310",
                                format!("Duplicate or unknown variant {}", arm.variant.text),
                                arm.variant.span.clone(),
                            ));
                        }
                        let (_, payload) = variant.unwrap();
                        if payload.is_some() != arm.binding.is_some() {
                            return Err(error(
                                "E0310",
                                "Match payload binding must agree with its variant",
                                arm.variant.span.clone(),
                            ));
                        }
                        let mut branch = state.clone();
                        if let Some(payload) = payload {
                            self.bind(
                                arm.binding.as_ref().unwrap(),
                                type_name(payload, false, self.record_index)?,
                                &mut branch,
                                false,
                            )?;
                        }
                        if self.block(&arm.body, &mut branch)? {
                            survivors.push(branch);
                        }
                    }
                    if seen.len() != variants.len() {
                        return Err(error(
                            "E0310",
                            "Match must handle every variant exactly once",
                            stmt.span.clone(),
                        ));
                    }
                    self.join(state, &survivors, stmt.span.clone())?;
                    reachable = !survivors.is_empty();
                }
                StmtKind::Expr => {
                    if self.outcome(ty).is_some() {
                        return Err(error(
                            "E0311",
                            "An outcome must be matched, returned, or transferred to an owning parameter",
                            span,
                        ));
                    }
                }
                StmtKind::Assign => (),
            }
        }
        if reachable {
            self.handled(
                state,
                state.bindings.keys().filter(|n| !initial.contains(*n)),
            )?;
        }
        Ok(reachable)
    }
    /// Destinations are checked before the value; the final store cannot revive an owner.
    fn assignment(&mut self, stmt: &Stmt, state: &mut State) -> Result<()> {
        let target = stmt.target.expect("assignment target");
        if matches!(self.expressions[target].kind, ExprKind::Name(_)) {
            let ty = self.lookup(target, state)?;
            self.expressions[target].ty = Some(ty);
            if !matches!(ty, Ty::Int | Ty::Bool) {
                return Err(error(
                    "E0305",
                    "Whole-binding assignment supports only i32 or bool locals",
                    self.expressions[target].span.clone(),
                ));
            }
            self.require_mutable(target, ty, state)?;
            let actual = self.expr(stmt.expr, state, true)?;
            return self.same(actual, ty, self.expressions[stmt.expr].span.clone());
        }
        let place = match self.expressions[target].kind {
            ExprKind::Field(_, place)
                if matches!(self.expressions[place].kind, ExprKind::Name(_)) =>
            {
                place
            }
            _ => {
                return Err(error(
                    "E0305",
                    "Assignment requires a named scalar local or a scalar field of a named record binding",
                    self.expressions[target].span.clone(),
                ));
            }
        };
        let ty = self.expr(target, state, false)?;
        self.require_mutable(place, self.lookup(place, state)?, state)?;
        self.access(place, state, "write")?;
        let actual = self.expr(stmt.expr, state, true)?;
        self.same(actual, ty, self.expressions[stmt.expr].span.clone())?;
        self.lookup(place, state)?;
        self.access(place, state, "write")
    }
    fn require_mutable(&self, index: usize, ty: Ty, state: &State) -> Result<()> {
        let ExprKind::Name(name) = &self.expressions[index].kind else {
            unreachable!("mutable place");
        };
        if !matches!(ty, Ty::Borrowed(_, true)) && !state.mutable.contains(name) {
            return Err(error(
                "E0303",
                format!("Mutating {name} requires a let mut owner or an &mut parameter"),
                self.expressions[index].span.clone(),
            ));
        }
        Ok(())
    }
    fn access(&self, index: usize, state: &State, action: &str) -> Result<()> {
        let ExprKind::Name(name) = &self.expressions[index].kind else {
            unreachable!("loan place");
        };
        if let Some(exclusive) = state.loans.get(name)
            && (*exclusive || action != "read")
        {
            let (article, mode) = if *exclusive {
                ("an", "exclusive")
            } else {
                ("a", "shared")
            };
            return Err(error(
                "E0302",
                format!(
                    "Cannot {action} {name}: an earlier argument holds {article} {mode} borrow until its call returns"
                ),
                self.expressions[index].span.clone(),
            ));
        }
        Ok(())
    }
    fn lookup(&self, index: usize, state: &State) -> Result<Ty> {
        let expr = &self.expressions[index];
        let ExprKind::Name(name) = &expr.kind else {
            unreachable!("lookup of a name")
        };
        let Some(ty) = state.bindings.get(name) else {
            return Err(error(
                "E0101",
                format!("Unknown binding {name}"),
                expr.span.clone(),
            ));
        };
        if state.moved.contains(name) {
            return Err(error(
                "E0301",
                format!("{name} was moved on a possible path and cannot be used again"),
                expr.span.clone(),
            ));
        }
        Ok(*ty)
    }
    fn borrow(&mut self, index: usize, state: &mut State) -> Result<Ty> {
        let ExprKind::Borrow(exclusive, place) = self.expressions[index].kind else {
            unreachable!("borrow expression");
        };
        let span = self.expressions[place].span.clone();
        let ExprKind::Name(name) = self.expressions[place].kind.clone() else {
            return Err(error(
                "E0305",
                "Borrow a named record binding; temporaries, fields, and nested references are unsupported",
                span,
            ));
        };
        let binding = self.lookup(place, state)?;
        self.expressions[place].ty = Some(binding);
        let Some(record) = binding.record() else {
            return Err(error(
                "E0305",
                "Only named records can be borrowed in this profile",
                span,
            ));
        };
        if self.records[record].variants.is_some() {
            return Err(error("E0305", "Outcomes cannot be borrowed", span));
        }
        if exclusive {
            self.require_mutable(place, binding, state)?;
        }
        self.access(
            place,
            state,
            if exclusive {
                "borrow exclusively"
            } else {
                "read"
            },
        )?;
        state.loans.insert(name, exclusive);
        let ty = Ty::Borrowed(record, exclusive);
        self.expressions[index].ty = Some(ty);
        Ok(ty)
    }
    fn argument(&mut self, index: usize, state: &mut State) -> Result<Ty> {
        if matches!(self.expressions[index].kind, ExprKind::Borrow(..)) {
            self.borrow(index, state)
        } else {
            self.expr(index, state, true)
        }
    }
    /// Check one expression. `consume` is false only for a field's base, which reads a scalar
    /// field without moving its record.
    fn expr(&mut self, index: usize, state: &mut State, consume: bool) -> Result<Ty> {
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
            ExprKind::Name(name) => {
                let ty = self.lookup(index, state)?;
                if consume && matches!(ty, Ty::Borrowed(..)) {
                    return Err(error(
                        "E0304",
                        "Borrowed parameters cannot be used as owned values; reborrow explicitly in a call",
                        span,
                    ));
                }
                self.access(
                    index,
                    state,
                    if consume && !ty.is_copy() {
                        "move"
                    } else {
                        "read"
                    },
                )?;
                if consume && !ty.is_copy() {
                    state.moved.insert(name);
                }
                ty
            }
            ExprKind::Field(name, child) => {
                let base = self.expr(child, state, false)?;
                let field = match base.record() {
                    Some(record) if self.records[record].variants.is_none() => self.records[record]
                        .resolved
                        .iter()
                        .find(|(field, _)| *field == name),
                    _ => None,
                };
                match field {
                    Some((_, ty)) => *ty,
                    None => {
                        return Err(error(
                            "E0101",
                            format!("Type {} has no field {name}", base.name(self.records)),
                            span,
                        ));
                    }
                }
            }
            ExprKind::Record(name, fields) => {
                let Some(&record) = self.record_index.get(&name) else {
                    return Err(error("E0101", format!("Unknown record {name}"), span));
                };
                if self.records[record].variants.is_some() {
                    return Err(error("E0101", format!("Unknown record {name}"), span));
                }
                let mut seen = BTreeSet::new();
                for (key, child) in fields {
                    let expected = self.records[record]
                        .resolved
                        .iter()
                        .find(|(field, _)| *field == key.text)
                        .map(|(_, ty)| *ty);
                    let Some(expected) = expected.filter(|_| !seen.contains(&key.text)) else {
                        return Err(error(
                            "E0203",
                            format!("Duplicate or unknown field {}", key.text),
                            key.span,
                        ));
                    };
                    seen.insert(key.text);
                    let actual = self.expr(child, state, true)?;
                    self.same(actual, expected, self.expressions[child].span.clone())?;
                }
                let missing: BTreeSet<&str> = self.records[record]
                    .resolved
                    .iter()
                    .map(|(field, _)| field.as_str())
                    .filter(|field| !seen.contains(*field))
                    .collect();
                if !missing.is_empty() {
                    return Err(error(
                        "E0203",
                        format!(
                            "Missing fields: {}",
                            missing.into_iter().collect::<Vec<_>>().join(", ")
                        ),
                        span,
                    ));
                }
                Ty::Record(record)
            }
            ExprKind::Outcome(name, variant, payload) => {
                let record = self
                    .record_index
                    .get(&name)
                    .copied()
                    .filter(|i| self.records[*i].variants.is_some())
                    .ok_or_else(|| {
                        error("E0310", format!("Unknown outcome {name}"), span.clone())
                    })?;
                let variants = self.records[record].variants.as_ref().unwrap();
                let expected = variants
                    .iter()
                    .find(|(n, _)| n.text == variant.text)
                    .ok_or_else(|| {
                        error(
                            "E0310",
                            format!("Unknown variant {}", variant.text),
                            span.clone(),
                        )
                    })?
                    .1
                    .clone();
                if expected.is_some() != payload.is_some() {
                    return Err(error(
                        "E0310",
                        "Constructor payload must agree with its variant",
                        span,
                    ));
                }
                if let (Some(expected), Some(child)) = (expected, payload) {
                    let actual = self.expr(child, state, true)?;
                    self.same(
                        actual,
                        type_name(&expected, false, self.record_index)?,
                        self.expressions[child].span.clone(),
                    )?;
                }
                Ty::Record(record)
            }
            ExprKind::Call(name, args) if name == "print" => {
                if args.len() != 1 {
                    return Err(error("E0203", "print expects 1 argument", span));
                }
                let actual = self.argument(args[0], state)?;
                self.same(actual, Ty::Text, self.expressions[args[0]].span.clone())?;
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
                let outer_loans = state.loans.clone();
                let checked = (|| {
                    for (arg, expected) in args.iter().zip(params) {
                        let actual = if matches!(self.expressions[*arg].kind, ExprKind::Borrow(..))
                        {
                            self.borrow(*arg, state)?
                        } else if matches!(expected, Ty::Borrowed(..)) {
                            return Err(error(
                                "E0304",
                                format!(
                                    "Pass {} explicitly with &name or &mut name",
                                    expected.name(self.records)
                                ),
                                self.expressions[*arg].span.clone(),
                            ));
                        } else {
                            self.expr(*arg, state, true)?
                        };
                        self.same(actual, expected, self.expressions[*arg].span.clone())?;
                    }
                    Ok(())
                })();
                state.loans = outer_loans;
                checked?;
                result
            }
            ExprKind::Borrow(..) => {
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
                    let actual = self.expr(child, state, true)?;
                    self.same(actual, expected, self.expressions[child].span.clone())?;
                    expected
                }
            }
            ExprKind::Binary(op, a, b) => {
                let left = self.expr(a, state, true)?;
                // The right side of &&/|| may run, so its moves count as possible.
                let before_right = matches!(op.as_str(), "&&" | "||").then(|| state.clone());
                let right = self.expr(b, state, true)?;
                let (a_span, b_span) = (
                    self.expressions[a].span.clone(),
                    self.expressions[b].span.clone(),
                );
                match op.as_str() {
                    "&&" | "||" => {
                        self.join(
                            state,
                            &[before_right.unwrap(), state.clone()],
                            b_span.clone(),
                        )?;
                        self.same(left, Ty::Bool, a_span)?;
                        self.same(right, Ty::Bool, b_span)?;
                        Ty::Bool
                    }
                    "==" | "!=" => {
                        if !matches!(left, Ty::Int | Ty::Bool) {
                            return Err(error(
                                "E0204",
                                "Equality currently supports only i32 and bool",
                                span,
                            ));
                        }
                        self.same(right, left, b_span)?;
                        Ty::Bool
                    }
                    _ => {
                        self.same(left, Ty::Int, a_span)?;
                        self.same(right, Ty::Int, b_span)?;
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

/// Reserved and duplicate global names, then record declarations, as in the reference.
fn check_declarations(
    records: &mut [Record],
    functions: &[Function],
) -> Result<BTreeMap<String, usize>> {
    let mut names: BTreeSet<&str> = ["i32", "bool", "str", "print"].into();
    // The reference visits every record before any function, whatever their source order.
    for name in records
        .iter()
        .map(|r| &r.name)
        .chain(functions.iter().map(|f| &f.name))
    {
        if !names.insert(&name.text) {
            return Err(error(
                "E0102",
                format!("Duplicate or reserved declaration {}", name.text),
                name.span.clone(),
            ));
        }
    }
    let mut index = BTreeMap::new();
    for (position, record) in records.iter().enumerate() {
        index.insert(record.name.text.clone(), position);
    }
    for position in 0..records.len() {
        let Some(variants) = records[position].variants.clone() else {
            check_record(&mut records[position])?;
            continue;
        };
        if variants.is_empty() {
            return Err(error(
                "E0310",
                "Outcomes require at least one variant",
                records[position].name.span.clone(),
            ));
        }
        let mut seen = BTreeSet::new();
        let mut resolved = Vec::new();
        for (name, payload) in variants {
            if !seen.insert(name.text.clone()) {
                return Err(error(
                    "E0102",
                    format!("Duplicate variant {}", name.text),
                    name.span,
                ));
            }
            if let Some(payload) = payload {
                let valid = matches!(payload.text.as_str(), "i32" | "bool")
                    || index
                        .get(&payload.text)
                        .is_some_and(|i| records[*i].variants.is_none());
                if !valid {
                    return Err(error(
                        "E0310",
                        "Outcome payloads must be i32, bool, or owned scalar records",
                        payload.span,
                    ));
                }
                resolved.push((name.text, type_name(&payload, false, &index)?));
            }
        }
        records[position].resolved = resolved;
    }
    Ok(index)
}

fn check_record(record: &mut Record) -> Result<()> {
    if record.fields.is_empty() {
        return Err(error(
            "E0204",
            "Prototype records must have at least one scalar field",
            record.name.span.clone(),
        ));
    }
    let mut resolved: Vec<(String, Ty)> = Vec::new();
    for (name, ty) in &record.fields {
        if resolved.iter().any(|(field, _)| *field == name.text) {
            return Err(error(
                "E0102",
                format!("Duplicate field {}", name.text),
                name.span.clone(),
            ));
        }
        let ty = match ty.text.as_str() {
            "i32" => Ty::Int,
            "bool" => Ty::Bool,
            _ => {
                return Err(error(
                    "E0204",
                    "Prototype record fields must be i32 or bool",
                    ty.span.clone(),
                ));
            }
        };
        resolved.push((name.text.clone(), ty));
    }
    record.resolved = resolved;
    Ok(())
}

struct Parsed {
    records: Vec<Record>,
    functions: Vec<Function>,
    expressions: Vec<Expr>,
}

fn parse_program(source: &str) -> Result<Parsed> {
    parse_program_mode(source, false)
}
fn parse_program_mode(source: &str, outcomes: bool) -> Result<Parsed> {
    let mut tokens = lex(source)?;
    if outcomes {
        for token in &mut tokens {
            if token.kind == TokenKind::Id && matches!(token.text.as_str(), "outcome" | "match") {
                token.kind = TokenKind::Fixed;
            }
        }
    }
    let mut parser = Parser {
        tokens,
        index: 0,
        expressions: Vec::new(),
        outcomes,
    };
    let (records, functions) = parser.program()?;
    let expressions = parser.expressions;
    check_depth(&functions, &expressions)?;
    Ok(Parsed {
        records,
        functions,
        expressions,
    })
}

fn check_program(parsed: Parsed) -> Result<Program> {
    let Parsed {
        mut records,
        functions,
        mut expressions,
    } = parsed;
    let record_index = check_declarations(&mut records, &functions)?;
    let mut signatures = BTreeMap::new();
    for f in &functions {
        let result = type_name(&f.result, false, &record_index)?;
        let params = f
            .params
            .iter()
            .map(|(_, ty)| type_name(ty, true, &record_index))
            .collect::<Result<Vec<_>>>()?;
        for ((_, token), ty) in f.params.iter().zip(&params) {
            if let Ty::Borrowed(i, _) = ty
                && records[*i].variants.is_some()
            {
                return Err(error(
                    "E0305",
                    "Outcomes cannot be borrowed",
                    token.span.clone(),
                ));
            }
        }
        signatures.insert(f.name.text.clone(), (params, result));
    }
    let mut console = false;
    for f in &functions {
        let (params, result) = signatures[&f.name.text].clone();
        let mut checker = Checker {
            expressions: &mut expressions,
            signatures: &signatures,
            records: &records,
            record_index: &record_index,
            result,
            console,
        };
        let mut state = State::default();
        for ((name, _), ty) in f.params.iter().zip(params) {
            checker.bind(name, ty, &mut state, false)?;
        }
        if checker.block(&f.body, &mut state)? {
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
        records,
        functions,
        signatures,
        expressions,
        console,
    })
}

pub fn analyze(source: &str) -> Result<Program> {
    check_program(parse_program(source)?)
}
/// Independently parse and check the explicit concrete-outcome source profile.
pub fn analyze_outcomes(source: &str) -> Result<Program> {
    check_program(parse_program_mode(source, true)?)
}

/// The reference's compact agent index, derived only from a checked program.
/// Declaration names sort lexically; parameter and field order stays as written.
pub fn agent_context(program: &Program) -> String {
    let mut functions: Vec<_> = program.functions.iter().collect();
    functions.sort_by(|a, b| a.name.text.cmp(&b.name.text));
    let functions = functions
        .iter()
        .map(|function| {
            let params = function
                .params
                .iter()
                .map(|(name, ty)| format!("{}: {}", name.text, ty.text))
                .collect::<Vec<_>>()
                .join(", ");
            json(&format!(
                "fn {}({params}) -> {}",
                function.name.text, function.result.text
            ))
        })
        .collect::<Vec<_>>()
        .join(",");
    let mut records: Vec<_> = program.records.iter().collect();
    records.sort_by(|a, b| a.name.text.cmp(&b.name.text));
    let records = records
        .iter()
        .map(|record| {
            let fields = record
                .fields
                .iter()
                .map(|(name, ty)| format!("{}: {}", name.text, ty.text))
                .collect::<Vec<_>>()
                .join(", ");
            json(&format!(
                "struct {} {{ {fields} }} (moves when passed by value)",
                record.name.text
            ))
        })
        .collect::<Vec<_>>()
        .join(",");
    format!(
        "{{\"functions\":[{functions}],\"records\":[{records}],\"schema\":\"talven.agent-context.v2\"}}\n"
    )
}

#[derive(Debug)]
pub struct AnalysisTiming {
    pub parse_ns: u128,
    pub check_ns: u128,
}

/// Measure successful full analysis without exposing an unchecked emission path.
/// Ordinary analyze does not read a clock; both paths use the same private stages.
pub fn analyze_measured(source: &str) -> Result<(Program, AnalysisTiming)> {
    let started = std::time::Instant::now();
    let parsed = parse_program(source)?;
    let parse_ns = started.elapsed().as_nanos();
    let started = std::time::Instant::now();
    let program = check_program(parsed)?;
    let check_ns = started.elapsed().as_nanos();
    Ok((program, AnalysisTiming { parse_ns, check_ns }))
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
    records: &'a [Record],
    output: String,
    indent: usize,
    counter: usize,
    used: [bool; 7],
    outcome_match: bool,
}
impl Emitter<'_> {
    fn line(&mut self, text: impl std::fmt::Display) {
        for _ in 0..self.indent {
            self.output.push_str("    ");
        }
        writeln!(self.output, "{text}").expect("writing to a String is infallible");
    }
    fn temp(&mut self, ty: Ty, value: String) -> String {
        self.counter += 1;
        let name = format!("tv_tmp_{}", self.counter);
        let ctype = ty.c(self.records);
        self.line(format_args!("{ctype} {name} = {value};"));
        name
    }
    fn helper(&mut self, name: &str) -> String {
        let index = HELPER_NAMES.iter().position(|h| h[3..] == *name);
        self.used[index.expect("known helper")] = true;
        format!("tv_{name}")
    }
    fn place(&self, index: usize) -> String {
        let expr = &self.expressions[index];
        match &expr.kind {
            ExprKind::Name(name) => {
                let name = format!("tv_v_{name}");
                if matches!(expr.ty, Some(Ty::Borrowed(..))) {
                    format!("(*{name})")
                } else {
                    name
                }
            }
            ExprKind::Field(name, child) => format!("({}).tv_m_{name}", self.place(*child)),
            _ => unreachable!("checked addressable place"),
        }
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
            ExprKind::Outcome(name, variant, payload) => {
                let record = ty.record().unwrap();
                let tag = self.records[record]
                    .variants
                    .as_ref()
                    .unwrap()
                    .iter()
                    .position(|(n, _)| n.text == variant.text)
                    .unwrap();
                let payload = payload
                    .map(|child| {
                        format!(", .tv_payload.tv_m_{} = {}", variant.text, self.expr(child))
                    })
                    .unwrap_or_default();
                self.temp(
                    ty,
                    format!("(struct tv_s_{name}){{.tv_tag = {tag}{payload}}}"),
                )
            }
            ExprKind::Name(name) => self.temp(ty, format!("tv_v_{name}")),
            ExprKind::Text(value) => {
                self.counter += 1;
                let name = format!("tv_text_{}", self.counter);
                self.line(format_args!("static const uint8_t {name}[] = {{"));
                for chunk in value.as_bytes().chunks(16) {
                    let bytes = chunk
                        .iter()
                        .map(|b| format!("0x{b:02x}"))
                        .collect::<Vec<_>>()
                        .join(", ");
                    self.line(format_args!("    {bytes},"));
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
                    self.line(format_args!("if ({negate}{result}) {{"));
                    self.indent += 1;
                    let right = self.expr(*b);
                    self.line(format_args!("{result} = {right};"));
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
            ExprKind::Field(name, child) => {
                // A named base is read in place; any other base is evaluated to a temporary.
                let record = match &self.expressions[*child].kind {
                    ExprKind::Name(_) => self.place(*child),
                    _ => self.expr(*child),
                };
                // Capture the scalar now, as the reference does.
                self.temp(ty, format!("({record}).tv_m_{name}"))
            }
            ExprKind::Record(name, fields) => {
                let values = fields
                    .iter()
                    .map(|(key, child)| format!(".tv_m_{} = {}", key.text, self.expr(*child)))
                    .collect::<Vec<_>>();
                self.temp(ty, format!("(struct tv_s_{name}){{{}}}", values.join(", ")))
            }
            ExprKind::Borrow(_, child) => self.temp(ty, format!("&({})", self.place(*child))),
        }
    }
    fn block(&mut self, body: &[Stmt]) {
        for stmt in body {
            let value = self.expr(stmt.expr);
            match stmt.kind {
                StmtKind::Let => {
                    let name = &stmt.name.as_ref().expect("let name").text;
                    let ty = self.expressions[stmt.expr].ty.expect("checked let");
                    let ctype = ty.c(self.records);
                    self.line(format_args!("{ctype} tv_v_{name} = {value};"));
                    self.line(format_args!("(void)tv_v_{name};"));
                }
                StmtKind::Return => self.line(format_args!("return {value};")),
                StmtKind::Expr => self.line(format_args!("(void)({value});")),
                StmtKind::If => {
                    self.line(format_args!("if ({value}) {{"));
                    self.indent += 1;
                    self.block(&stmt.then);
                    self.indent -= 1;
                    self.line("} else {");
                    self.indent += 1;
                    self.block(&stmt.otherwise);
                    self.indent -= 1;
                    self.line("}");
                }
                StmtKind::Assign => {
                    let target = stmt.target.expect("assignment target");
                    self.line(format_args!("{} = {value};", self.place(target)));
                }
                StmtKind::Match => {
                    self.outcome_match = true;
                    let record = self.expressions[stmt.expr].ty.unwrap().record().unwrap();
                    self.line(format!("switch (({value}).tv_tag) {{"));
                    self.indent += 1;
                    for arm in &stmt.arms {
                        let variants = self.records[record].variants.as_ref().unwrap();
                        let tag = variants
                            .iter()
                            .position(|(n, _)| n.text == arm.variant.text)
                            .unwrap();
                        self.line(format!("case {tag}: {{"));
                        self.indent += 1;
                        if let Some(binding) = &arm.binding {
                            let ty = self.records[record]
                                .resolved
                                .iter()
                                .find(|(n, _)| *n == arm.variant.text)
                                .unwrap()
                                .1;
                            self.line(format!(
                                "{} tv_v_{} = ({value}).tv_payload.tv_m_{};",
                                ty.c(self.records),
                                binding.text,
                                arm.variant.text
                            ));
                            self.line(format!("(void)tv_v_{};", binding.text));
                        }
                        self.block(&arm.body);
                        self.line("break;");
                        self.indent -= 1;
                        self.line("}");
                    }
                    self.line("default: { talven_trap(); }");
                    self.indent -= 1;
                    self.line("}");
                }
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
        .map(|((name, _), ty)| format!("{} tv_v_{}", ty.c(&program.records), name.text))
        .collect::<Vec<_>>()
        .join(", ");
    let params = if params.is_empty() {
        "void".into()
    } else {
        params
    };
    format!(
        "{} tv_f_{}({params})",
        result.c(&program.records),
        f.name.text
    )
}
pub fn emit_c(program: &Program, console: bool) -> Result<String> {
    emit_c_mode(program, console, false)
}
fn emit_c_mode(program: &Program, console: bool, library: bool) -> Result<String> {
    if program.console && !console {
        return Err(error(
            "E0404",
            "print requires hosted POSIX console support; enable --console",
            0..0,
        ));
    }
    let main = program.functions.iter().find(|f| f.name.text == "main");
    if !library && !main.is_some_and(|f| f.params.is_empty() && f.result.text == "i32") {
        return Err(error(
            "E0401",
            "A hosted executable requires fn main() -> i32",
            main.map_or(0..0, |f| f.name.span.clone()),
        ));
    }
    let mut emitter = Emitter {
        expressions: &program.expressions,
        records: &program.records,
        output: String::new(),
        indent: 0,
        counter: 0,
        used: [false; 7],
        outcome_match: false,
    };
    let mut records: Vec<_> = program.records.iter().collect();
    records.sort_by_key(|r| r.variants.is_some());
    for record in records {
        emitter.line(format_args!("struct tv_s_{} {{", record.name.text));
        if record.variants.is_some() {
            emitter.line("    uint32_t tv_tag;");
            emitter.line("    union {");
            for (name, ty) in &record.resolved {
                emitter.line(format!("        {} tv_m_{name};", ty.c(&program.records)));
            }
            if record.resolved.is_empty() {
                emitter.line("        uint8_t tv_empty;");
            }
            emitter.line("    } tv_payload;");
        } else {
            for (name, ty) in &record.resolved {
                let ctype = ty.c(&program.records);
                emitter.line(format_args!("    {ctype} tv_m_{name};"));
            }
        }
        emitter.line("};");
    }
    for f in &program.functions {
        emitter.line(format_args!("{};", signature(program, f)));
    }
    for f in &program.functions {
        emitter.line(format_args!("{} {{", signature(program, f)));
        emitter.indent += 1;
        for (name, _) in &f.params {
            emitter.line(format_args!("(void)tv_v_{};", name.text));
        }
        emitter.block(&f.body);
        emitter.indent -= 1;
        emitter.line("}");
    }
    if !library {
        emitter.line("int main(void) { return (int)tv_f_main(); }");
    }
    let mut used = emitter.used;
    // add, sub, mul, and neg narrow through tv_narrow.
    used[0] = used[1..5].iter().any(|u| *u);
    let definitions = helper_definitions();
    let needs_trap = emitter.outcome_match || used.iter().any(|u| *u);
    let prefix_bytes = HEADER.iter().map(|line| line.len() + 1).sum::<usize>()
        + if program.console {
            console_definition().len() + 1
        } else {
            0
        }
        + if needs_trap { HOSTED_TRAP.len() + 1 } else { 0 }
        + definitions
            .iter()
            .zip(used)
            .filter(|(_, used)| *used)
            .map(|(definition, _)| definition.len() + 1)
            .sum::<usize>();
    let mut output = String::with_capacity(prefix_bytes + emitter.output.len());
    for line in HEADER {
        output.push_str(line);
        output.push('\n');
    }
    if program.console {
        output.push_str(console_definition());
        output.push('\n');
    }
    if needs_trap {
        output.push_str(HOSTED_TRAP);
        output.push('\n');
    }
    for (definition, used) in definitions.iter().zip(used) {
        if used {
            output.push_str(definition);
            output.push('\n');
        }
    }
    output.push_str(&emitter.output);
    Ok(output)
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
    fn nesting_limit_is_defined_not_interpreter_dependent() {
        let parens = |n: usize| {
            format!(
                "fn f() -> i32 {{ return {}1{}; }}",
                "(".repeat(n),
                ")".repeat(n)
            )
        };
        // Body block 1 + return expression 2 + one level per parenthesis.
        assert!(analyze(&parens(254)).is_ok());
        let (code, message, span) = failure(&parens(255));
        assert_eq!("E0005", code);
        assert!(message.contains("256-level"));
        assert_eq!(278..279, span);
    }

    #[test]
    fn let_mut_and_record_syntax_follow_the_reference_without_records() {
        assert!(analyze("fn f() -> i32 { let mut x = 1; x = x + 1; return x; }").is_ok());
        let (code, _, span) = failure("fn f() -> i32 { let mut x = \"text\"; return 0; }");
        assert_eq!(("E0305", 24..25), (code, span));
        assert!(analyze("struct A { x: i32 }").is_ok());
        assert_eq!("E0101", failure("fn f(x: i32) -> i32 { return x.y; }").0);
        assert_eq!("E0101", failure("fn f(x: &A) -> i32 { return 0; }").0);
        let (code, message, _) = failure("fn f() -> i32 { return P { x: 1 }; }");
        assert_eq!(("E0101", "Unknown record P"), (code, message.as_str()));
    }

    const POINT: &str = "struct P { x: i32, y: bool }\n";

    #[test]
    fn call_borrows_check_permissions_conflicts_and_escapes() {
        let helpers = "fn read(p: &P) -> i32 { return p.x; } fn bump(p: &mut P) -> i32 { p.x = p.x + 1; return p.x; } fn value(p: &mut P, x: i32) -> i32 { return x; } fn shared(a: &P, b: &P) -> i32 { return a.x + b.x; }";
        for body in [
            "let mut p = P { x: 1, y: false }; bump(&mut p); return read(&p);",
            "let p = P { x: 1, y: false }; return shared(&p, &p);",
            "let mut p = P { x: 1, y: false }; p.x = bump(&mut p) + 1; return p.x;",
            "let mut p = P { x: 1, y: false }; return value(&mut p, 0);",
        ] {
            assert!(analyze(&format!("{POINT}{helpers}fn main() -> i32 {{ {body} }}")).is_ok());
        }
        for (body, expected) in [
            (
                "let p = P { x: 1, y: false }; return bump(&mut p);",
                "E0303",
            ),
            (
                "let mut p = P { x: 1, y: false }; return value(&mut p, p.x);",
                "E0302",
            ),
            (
                "let mut p = P { x: 1, y: false }; return value(&mut p, read(&p));",
                "E0302",
            ),
            ("let mut p = P { x: 1, y: false }; return read(p);", "E0304"),
            (
                "let mut p = P { x: 1, y: false }; let q = p; return read(&p);",
                "E0301",
            ),
            (
                "let mut p = P { x: 1, y: false }; p.x = read(p); return 0;",
                "E0304",
            ),
            (
                "let mut p = P { x: 1, y: false }; return read(&mut p);",
                "E0201",
            ),
        ] {
            assert_eq!(
                expected,
                failure(&format!("{POINT}{helpers}fn main() -> i32 {{ {body} }}")).0
            );
        }
        assert!(
            analyze(&format!(
                "{POINT}{helpers}fn forward(p: &mut P) -> i32 {{ bump(&mut p); return read(&p); }}"
            ))
            .is_ok()
        );
        assert_eq!(
            "E0303",
            failure(&format!(
                "{POINT}{helpers}fn f(p: &P) -> i32 {{ return bump(&mut p); }}"
            ))
            .0
        );
        assert_eq!(
            "E0304",
            failure(&format!("{POINT}fn f(p: P) -> &P {{ return p; }}")).0
        );
        assert_eq!(
            "E0304",
            failure(&format!(
                "{POINT}fn f(p: &P) -> i32 {{ let q = p; return 0; }}"
            ))
            .0
        );
        assert_eq!(
            "E0305",
            failure(&format!("{POINT}fn f(p: &i32) -> i32 {{ return 0; }}")).0
        );
        assert_eq!("E0204", failure("struct Q { p: &Q }").0);
    }

    #[test]
    fn record_declarations_follow_the_reference_order() {
        let (code, message, span) = failure("fn f() -> i32 { return 0; }\nstruct f { x: i32 }");
        assert_eq!(("E0102", 3..4), (code, span.clone()));
        assert_eq!("Duplicate or reserved declaration f", message);
        let checks = [
            (
                "struct E {}",
                "E0204",
                "Prototype records must have at least one scalar field",
            ),
            ("struct P { x: i32, x: str }", "E0102", "Duplicate field x"),
            (
                "struct P { x: str }",
                "E0204",
                "Prototype record fields must be i32 or bool",
            ),
            (
                "struct print { x: i32 }",
                "E0102",
                "Duplicate or reserved declaration print",
            ),
        ];
        for (source, code, message) in checks {
            assert_eq!((code, message.to_string()), {
                let f = failure(source);
                (f.0, f.1)
            });
        }
    }

    #[test]
    fn record_literals_and_fields() {
        let program = |body: &str| format!("{POINT}fn f() -> i32 {{ {body} }}");
        assert!(analyze(&program("return P { y: true, x: 1, }.x;")).is_ok());
        let cases = [
            (
                "return P { x: 1, x: 2, y: true }.x;",
                "E0203",
                "Duplicate or unknown field x",
            ),
            (
                "return P { x: 1, z: 2 }.x;",
                "E0203",
                "Duplicate or unknown field z",
            ),
            ("return P { }.x;", "E0203", "Missing fields: x, y"),
            (
                "return P { x: true, y: true }.x;",
                "E0201",
                "Expected i32, found bool; implicit conversions are not supported",
            ),
            (
                "return P { x: 1, y: true }.z;",
                "E0101",
                "Type P has no field z",
            ),
            (
                "return P { x: 1, y: true }.x.y;",
                "E0101",
                "Type i32 has no field y",
            ),
            ("return Q { x: 1 }.x;", "E0101", "Unknown record Q"),
            ("return P(1);", "E0101", "Unknown function P"),
            (
                "let p = P { x: 1, y: true }; return p;",
                "E0201",
                "Expected i32, found P; implicit conversions are not supported",
            ),
            (
                "let p = P { x: 1, y: true }; let q = P { x: 1, y: true }; if (p == q) { return 1; } return 0;",
                "E0204",
                "Equality currently supports only i32 and bool",
            ),
        ];
        for (body, code, message) in cases {
            let (actual, text, _) = failure(&program(body));
            assert_eq!((code, message), (actual, text.as_str()), "{body}");
        }
    }

    #[test]
    fn moves_follow_the_reference_paths() {
        let prelude = format!("{POINT}fn take(p: P) -> bool {{ return p.y; }}\n");
        let program = |body: &str| format!("{prelude}fn f(p: P, c: bool) -> i32 {{ {body} }}");
        let accepted = [
            "let q = p; return q.x;",
            "if (c) { let q = p; return q.x; } return p.x;",
            "if (c) { return 1; } else { take(p); } return 0;",
            "let v = p.x; if (take(p)) { return v; } return 0;",
        ];
        for body in accepted {
            assert!(analyze(&program(body)).is_ok(), "{body}");
        }
        let moved = [
            "let q = p; return p.x;",
            "p; return p.x;",
            "if (c) { take(p); } return p.x;",
            "if (c) { return 1; } else { take(p); } return p.x;",
            "if (false && take(p)) { return 1; } return p.x;",
            "if (true || take(p)) { return 1; } return p.x;",
            "if (p == p) { return 1; } return 0;",
        ];
        for body in moved {
            let (code, message, _) = failure(&program(body));
            assert_eq!("E0301", code, "{body}");
            assert_eq!(
                "p was moved on a possible path and cannot be used again",
                message
            );
        }
    }

    #[test]
    fn records_emit_definitions_temporaries_and_order() {
        let source = format!(
            "{POINT}fn make(v: i32) -> P {{ return P {{ y: v > 0, x: v + 1 }}; }}\n\
             fn main() -> i32 {{ let p = make(2); return p.x + make(3).x; }}"
        );
        let c = emit_c(&analyze(&source).unwrap(), false).unwrap();
        let definition = "struct tv_s_P {\n    int32_t tv_m_x;\n    bool tv_m_y;\n};\n";
        let at = c.find(definition).expect("record definition");
        assert!(
            c.find(HOSTED_TRAP).unwrap() < at
                && at < c.find("struct tv_s_P tv_f_make(int32_t tv_v_v);").unwrap()
        );
        assert!(c.contains(
            "struct tv_s_P tv_tmp_5 = (struct tv_s_P){.tv_m_y = tv_tmp_2, .tv_m_x = tv_tmp_4};"
        ));
        assert!(c.contains("struct tv_s_P tv_v_p = tv_tmp_6;"));
        assert!(c.contains("int32_t tv_tmp_7 = (tv_v_p).tv_m_x;"));
        assert!(c.contains("int32_t tv_tmp_9 = (tv_tmp_8).tv_m_x;"));
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

    #[test]
    fn compact_context_preserves_parameter_field_and_sorted_declaration_order() {
        let program = analyze(
            "struct Z { z: bool, a: i32 } fn z(p: &mut Z, s: &Z, owned: A, text: str) -> A { p.a = s.a; print(text); return owned; } struct A { v: i32 } fn a() -> bool { return true; }",
        )
        .unwrap();
        assert_eq!(
            agent_context(&program),
            "{\"functions\":[\"fn a() -> bool\",\"fn z(p: &mut Z, s: &Z, owned: A, text: str) -> A\"],\"records\":[\"struct A { v: i32 } (moves when passed by value)\",\"struct Z { z: bool, a: i32 } (moves when passed by value)\"],\"schema\":\"talven.agent-context.v2\"}\n"
        );
        assert_eq!(
            agent_context(&analyze("").unwrap()),
            "{\"functions\":[],\"records\":[],\"schema\":\"talven.agent-context.v2\"}\n"
        );
    }

    #[test]
    fn measured_analysis_preserves_checked_emission_and_rejections() {
        for source in [
            "fn main() -> i32 { let mut x = 1; x = x + 2; return x; }",
            "struct P { x: i32 } fn bump(p: &mut P) -> i32 { p.x = p.x + 1; return p.x; } fn main() -> i32 { let mut p = P { x: 1 }; return bump(&mut p); }",
            "fn main() -> i32 { return print(\"hé🙂\\n\"); }",
        ] {
            let ordinary = analyze(source).unwrap();
            let (measured, _) = analyze_measured(source).unwrap();
            assert_eq!(
                emit_c(&ordinary, true).unwrap(),
                emit_c(&measured, true).unwrap()
            );
        }
        for source in [
            "fn main() -> i32 { return false; }",
            "fn main() -> i32 { return @; }",
            "struct P { x: i32 } fn f(p: P) -> i32 { let q = p; return p.x; }",
            "struct P { x: i32 } fn f(p: &P) -> i32 { p.x = 1; return p.x; }",
        ] {
            let ordinary = analyze(source).unwrap_err();
            let measured = analyze_measured(source).unwrap_err();
            assert_eq!(
                (ordinary.code, ordinary.message, ordinary.span),
                (measured.code, measured.message, measured.span)
            );
        }
    }

    #[test]
    fn outcome_profile_preserves_bounds_and_must_handle_paths() {
        assert!(analyze("fn outcome(match:i32)->i32{return match;}").is_ok());
        assert!(analyze("outcome R{A}").is_err());
        assert!(analyze_outcomes("outcome R{A(i32),B} fn f(r:R)->R{return r;}").is_ok());
        assert_eq!(
            analyze_outcomes("outcome R{A} fn f(r:R)->i32{return 0;}")
                .unwrap_err()
                .code,
            "E0311"
        );
        let nested = |count| {
            format!(
                "outcome R{{A}} fn main()->i32{{{}{}return 0;}}",
                "match(R::A){R::A{".repeat(count),
                "}}".repeat(count)
            )
        };
        assert!(analyze_outcomes(&nested(127)).is_ok());
        assert_eq!(analyze_outcomes(&nested(128)).unwrap_err().code, "E0005");
    }
}
