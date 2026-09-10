//! A bounded scalar/static-text compiler experiment. Records and loans are unsupported.
use std::collections::BTreeMap;
use std::ops::Range;

pub const PROFILE: &str = "native-scalar-text-v1";
pub const MAX_SOURCE: usize = 256 * 1024;
const MAX_TOKENS: usize = 16384;
const MAX_DEPTH: usize = 128;

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
fn position(source: &str, offset: usize) -> String {
    let prefix = &source[..offset];
    let line = prefix.bytes().filter(|ch| *ch == b'\n').count();
    let column = prefix
        .rsplit('\n')
        .next()
        .unwrap_or("")
        .encode_utf16()
        .count();
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

#[derive(Clone, Debug, PartialEq)]
enum Kind {
    Word,
    Number,
    Text(String),
    Symbol,
    End,
}
#[derive(Clone, Debug)]
struct Token {
    kind: Kind,
    text: String,
    span: Range<usize>,
}
fn lex(source: &str) -> Result<Vec<Token>> {
    if source.len() > MAX_SOURCE {
        return Err(error("E0005", "Source exceeds 256 KiB", 0..0));
    }
    let mut tokens = Vec::new();
    let mut at = 0;
    while at < source.len() {
        let start = at;
        let ch = source[at..].chars().next().unwrap();
        if ch.is_whitespace() || matches!(ch, '\u{1c}'..='\u{1f}') {
            at += ch.len_utf8();
            continue;
        }
        if source[at..].starts_with("//") {
            at += source[at..].find('\n').unwrap_or(source.len() - at);
            continue;
        }
        let kind;
        if ch == '"' {
            at += 1;
            let mut value = String::new();
            let mut closed = false;
            while at < source.len() {
                let ch = source[at..].chars().next().unwrap();
                at += ch.len_utf8();
                if ch == '"' {
                    closed = true;
                    break;
                }
                if ch < ' ' || ch == '\u{7f}' {
                    return Err(error(
                        "E0006",
                        "Escape controls in text literals",
                        start..at,
                    ));
                }
                if ch == '\\' {
                    if at == source.len() {
                        break;
                    }
                    let escaped = source[at..].chars().next().unwrap();
                    at += escaped.len_utf8();
                    value.push(match escaped {
                        '"' => '"',
                        '\\' => '\\',
                        'n' => '\n',
                        'r' => '\r',
                        't' => '\t',
                        '0' => '\0',
                        _ => return Err(error("E0006", "Unsupported text escape", start..at)),
                    });
                } else {
                    value.push(ch);
                }
            }
            if !closed {
                return Err(error("E0006", "Unterminated text literal", start..at));
            }
            kind = Kind::Text(value);
        } else if ch.is_ascii_digit() {
            at += source[at..].bytes().take_while(u8::is_ascii_digit).count();
            kind = Kind::Number;
        } else if ch.is_ascii_alphabetic() || ch == '_' {
            at += source[at..]
                .bytes()
                .take_while(|c| c.is_ascii_alphanumeric() || *c == b'_')
                .count();
            kind = Kind::Word;
        } else if ["->", "==", "!=", "<=", ">=", "&&", "||"]
            .iter()
            .any(|op| source[at..].starts_with(op))
        {
            at += 2;
            kind = Kind::Symbol;
        } else if "{}():;,.+*/%<>=!&-".contains(ch) {
            at += 1;
            kind = Kind::Symbol;
        } else {
            return Err(error(
                "E0001",
                "Unexpected character",
                start..start + ch.len_utf8(),
            ));
        }
        tokens.push(Token {
            kind,
            text: source[start..at].into(),
            span: start..at,
        });
        if tokens.len() > MAX_TOKENS {
            return Err(error("E0005", "Source exceeds token limit", start..at));
        }
    }
    tokens.push(Token {
        kind: Kind::End,
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
    Unary(String, usize),
    Binary(String, usize, usize),
}
#[derive(Clone, Debug)]
struct Expr {
    kind: ExprKind,
    span: Range<usize>,
    height: usize,
    ty: Option<Ty>,
}
#[derive(Debug)]
enum StmtKind {
    Let(Token, Option<Ty>, usize),
    Return(usize),
    Expr(usize),
    If(usize, Vec<Stmt>, Vec<Stmt>),
}
#[derive(Debug)]
struct Stmt {
    kind: StmtKind,
    span: Range<usize>,
}
#[derive(Debug)]
struct Function {
    name: Token,
    params: Vec<(Token, Ty)>,
    result: Ty,
    body: Vec<Stmt>,
}
#[derive(Debug)]
pub struct Program {
    functions: Vec<Function>,
    expressions: Vec<Expr>,
    console: bool,
}
struct Parser {
    tokens: Vec<Token>,
    at: usize,
    expressions: Vec<Expr>,
}
impl Parser {
    fn current(&self) -> &Token {
        &self.tokens[self.at]
    }
    fn take(&mut self, text: &str) -> Result<Token> {
        if self.current().text != text {
            return Err(error(
                "E0002",
                format!("Expected {text}"),
                self.current().span.clone(),
            ));
        }
        let token = self.current().clone();
        self.at += 1;
        Ok(token)
    }
    fn accept(&mut self, text: &str) -> bool {
        if self.current().text == text && self.current().kind != Kind::End {
            self.at += 1;
            true
        } else {
            false
        }
    }
    fn identifier(&mut self) -> Result<Token> {
        let token = self.current().clone();
        if token.kind != Kind::Word
            || [
                "fn", "struct", "let", "mut", "return", "if", "else", "true", "false",
            ]
            .contains(&token.text.as_str())
        {
            return Err(error("E0002", "Expected identifier", token.span));
        }
        self.at += 1;
        Ok(token)
    }
    fn unsupported(&self) -> Error {
        error(
            "E0801",
            "Native experiment does not support records, borrowing, or mutation",
            self.current().span.clone(),
        )
    }
    fn ty(&mut self) -> Result<Ty> {
        if self.current().text == "&" {
            return Err(self.unsupported());
        }
        let token = self.identifier()?;
        match token.text.as_str() {
            "i32" => Ok(Ty::Int),
            "bool" => Ok(Ty::Bool),
            "str" => Ok(Ty::Text),
            _ => Err(error(
                "E0801",
                "Native experiment supports only i32, bool, and str types",
                token.span,
            )),
        }
    }
    fn depth(&self, depth: usize) -> Result<()> {
        if depth > MAX_DEPTH {
            Err(error(
                "E0005",
                "Syntax exceeds native nesting limit",
                self.current().span.clone(),
            ))
        } else {
            Ok(())
        }
    }
    fn program(mut self) -> Result<Program> {
        let mut functions = Vec::new();
        while self.current().kind != Kind::End {
            if self.current().text == "struct" {
                return Err(self.unsupported());
            }
            self.take("fn")?;
            let name = self.identifier()?;
            self.take("(")?;
            let mut params = Vec::new();
            while self.current().text != ")" {
                let param = self.identifier()?;
                self.take(":")?;
                let ty = self.ty()?;
                params.push((param, ty));
                if !self.accept(",") {
                    break;
                }
            }
            self.take(")")?;
            self.take("->")?;
            let result = self.ty()?;
            let body = self.block(1)?;
            functions.push(Function {
                name,
                params,
                result,
                body,
            });
        }
        Ok(Program {
            functions,
            expressions: self.expressions,
            console: false,
        })
    }
    fn block(&mut self, depth: usize) -> Result<Vec<Stmt>> {
        self.depth(depth)?;
        self.take("{")?;
        let mut body = Vec::new();
        while self.current().text != "}" {
            let start = self.current().span.start;
            let kind = if self.accept("let") {
                if self.current().text == "mut" {
                    return Err(self.unsupported());
                }
                let name = self.identifier()?;
                let annotation = if self.accept(":") {
                    Some(self.ty()?)
                } else {
                    None
                };
                self.take("=")?;
                let expr = self.expression(0, depth + 1)?;
                self.take(";")?;
                StmtKind::Let(name, annotation, expr)
            } else if self.accept("return") {
                let expr = self.expression(0, depth + 1)?;
                self.take(";")?;
                StmtKind::Return(expr)
            } else if self.accept("if") {
                self.take("(")?;
                let expr = self.expression(0, depth + 1)?;
                self.take(")")?;
                let yes = self.block(depth + 1)?;
                let no = if self.accept("else") {
                    self.block(depth + 1)?
                } else {
                    Vec::new()
                };
                StmtKind::If(expr, yes, no)
            } else {
                let expr = self.expression(0, depth + 1)?;
                self.take(";")?;
                StmtKind::Expr(expr)
            };
            body.push(Stmt {
                kind,
                span: start..self.tokens[self.at - 1].span.end,
            });
        }
        self.take("}")?;
        Ok(body)
    }
    fn add(&mut self, kind: ExprKind, span: Range<usize>, depth: usize) -> Result<usize> {
        let height = 1 + match &kind {
            ExprKind::Unary(_, x) => self.expressions[*x].height,
            ExprKind::Binary(_, a, b) => {
                self.expressions[*a].height.max(self.expressions[*b].height)
            }
            ExprKind::Call(_, args) => args
                .iter()
                .map(|i| self.expressions[*i].height)
                .max()
                .unwrap_or(0),
            _ => 0,
        };
        if height + depth > MAX_DEPTH {
            return Err(error("E0005", "Syntax exceeds native tree limit", span));
        }
        let index = self.expressions.len();
        self.expressions.push(Expr {
            kind,
            span,
            height,
            ty: None,
        });
        Ok(index)
    }
    fn expression(&mut self, minimum: u8, depth: usize) -> Result<usize> {
        self.depth(depth)?;
        let token = self.current().clone();
        let mut left;
        if token.text == "&" {
            return Err(self.unsupported());
        }
        if token.text == "-" || token.text == "!" {
            self.at += 1;
            let child = self.expression(7, depth + 1)?;
            left = self.add(
                ExprKind::Unary(token.text, child),
                token.span.start..self.expressions[child].span.end,
                depth,
            )?;
        } else if self.accept("(") {
            left = self.expression(0, depth + 1)?;
            self.take(")")?;
        } else if let Kind::Text(value) = token.kind {
            self.at += 1;
            left = self.add(ExprKind::Text(value), token.span, depth)?;
        } else if token.kind == Kind::Number {
            self.at += 1;
            left = self.add(ExprKind::Int(token.text), token.span, depth)?;
        } else if token.text == "true" || token.text == "false" {
            self.at += 1;
            left = self.add(ExprKind::Bool(token.text == "true"), token.span, depth)?;
        } else {
            let name = self.identifier()?;
            if self.accept("(") {
                let mut args = Vec::new();
                while self.current().text != ")" {
                    args.push(self.expression(0, depth + 1)?);
                    if !self.accept(",") {
                        break;
                    }
                }
                let end = self.take(")")?.span.end;
                left = self.add(ExprKind::Call(name.text, args), name.span.start..end, depth)?;
            } else {
                if self.current().text == "{" {
                    return Err(self.unsupported());
                }
                left = self.add(ExprKind::Name(name.text), name.span, depth)?;
            }
        }
        loop {
            if self.current().text == "." {
                return Err(self.unsupported());
            }
            let priority = match self.current().text.as_str() {
                "||" => 1,
                "&&" => 2,
                "==" | "!=" => 3,
                "<" | ">" | "<=" | ">=" => 4,
                "+" | "-" => 5,
                "*" | "/" | "%" => 6,
                _ => break,
            };
            if priority < minimum {
                break;
            }
            let op = self.current().text.clone();
            self.at += 1;
            let right = self.expression(priority + 1, depth + 1)?;
            left = self.add(
                ExprKind::Binary(op, left, right),
                self.expressions[left].span.start..self.expressions[right].span.end,
                depth,
            )?;
        }
        Ok(left)
    }
}
fn same(actual: Ty, expected: Ty, span: Range<usize>) -> Result<()> {
    if actual == expected {
        Ok(())
    } else {
        Err(error(
            "E0201",
            "Type mismatch; implicit conversions are unsupported",
            span,
        ))
    }
}
type Signatures = BTreeMap<String, (Vec<Ty>, Ty)>;
fn check_expr(
    index: usize,
    expressions: &mut [Expr],
    bindings: &BTreeMap<String, Ty>,
    signatures: &Signatures,
    console: &mut bool,
) -> Result<Ty> {
    let expr = expressions[index].clone();
    let ty = match expr.kind {
        ExprKind::Int(ref value) => {
            let digits = value.trim_start_matches('0');
            if digits.len() > 10
                || (!digits.is_empty()
                    && digits.parse::<u64>().unwrap_or(u64::MAX) > i32::MAX as u64)
            {
                return Err(error(
                    "E0202",
                    "Integer literal outside i32 range",
                    expr.span,
                ));
            }
            Ty::Int
        }
        ExprKind::Bool(_) => Ty::Bool,
        ExprKind::Text(_) => Ty::Text,
        ExprKind::Name(name) => *bindings.get(&name).ok_or_else(|| {
            error(
                "E0101",
                format!("Unknown binding {name}"),
                expr.span.clone(),
            )
        })?,
        ExprKind::Call(name, args) => {
            let signature = if name == "print" {
                (vec![Ty::Text], Ty::Int)
            } else {
                signatures
                    .get(&name)
                    .ok_or_else(|| {
                        error(
                            "E0101",
                            format!("Unknown function {name}"),
                            expr.span.clone(),
                        )
                    })?
                    .clone()
            };
            if args.len() != signature.0.len() {
                return Err(error("E0203", "Wrong argument count", expr.span));
            }
            for (arg, expected) in args.iter().zip(&signature.0) {
                let actual = check_expr(*arg, expressions, bindings, signatures, console)?;
                same(actual, *expected, expressions[*arg].span.clone())?;
            }
            if name == "print" {
                *console = true;
            }
            signature.1
        }
        ExprKind::Unary(op, child) => {
            if op == "-"
                && matches!(&expressions[child].kind, ExprKind::Int(v) if v.trim_start_matches('0') == "2147483648")
            {
                expressions[child].ty = Some(Ty::Int);
                Ty::Int
            } else {
                let actual = check_expr(child, expressions, bindings, signatures, console)?;
                let expected = if op == "-" { Ty::Int } else { Ty::Bool };
                same(actual, expected, expressions[child].span.clone())?;
                expected
            }
        }
        ExprKind::Binary(op, a, b) => {
            let left = check_expr(a, expressions, bindings, signatures, console)?;
            let right = check_expr(b, expressions, bindings, signatures, console)?;
            if op == "==" || op == "!=" {
                if left == Ty::Text {
                    return Err(error(
                        "E0204",
                        "Equality supports only i32 and bool",
                        expr.span,
                    ));
                }
                same(right, left, expressions[b].span.clone())?;
                Ty::Bool
            } else {
                let expected = if op == "&&" || op == "||" {
                    Ty::Bool
                } else {
                    Ty::Int
                };
                same(left, expected, expressions[a].span.clone())?;
                same(right, expected, expressions[b].span.clone())?;
                if ["+", "-", "*", "/", "%"].contains(&op.as_str()) {
                    Ty::Int
                } else {
                    Ty::Bool
                }
            }
        }
    };
    expressions[index].ty = Some(ty);
    Ok(ty)
}
fn check_block(
    body: &[Stmt],
    expressions: &mut [Expr],
    bindings: &mut BTreeMap<String, Ty>,
    signatures: &Signatures,
    result: Ty,
    console: &mut bool,
) -> Result<bool> {
    let mut live = true;
    for stmt in body {
        if !live {
            return Err(error("E0206", "Unreachable statement", stmt.span.clone()));
        }
        let expr = match &stmt.kind {
            StmtKind::Let(_, _, e)
            | StmtKind::Return(e)
            | StmtKind::Expr(e)
            | StmtKind::If(e, _, _) => *e,
        };
        let actual = check_expr(expr, expressions, bindings, signatures, console)?;
        match &stmt.kind {
            StmtKind::Let(name, expected, _) => {
                if let Some(expected) = expected {
                    same(actual, *expected, expressions[expr].span.clone())?;
                }
                if bindings.insert(name.text.clone(), actual).is_some() {
                    return Err(error(
                        "E0102",
                        "Duplicate or shadowed binding",
                        name.span.clone(),
                    ));
                }
            }
            StmtKind::Return(_) => {
                same(actual, result, expressions[expr].span.clone())?;
                live = false;
            }
            StmtKind::If(_, yes, no) => {
                same(actual, Ty::Bool, expressions[expr].span.clone())?;
                let yes_live = check_block(
                    yes,
                    expressions,
                    &mut bindings.clone(),
                    signatures,
                    result,
                    console,
                )?;
                let no_live = check_block(
                    no,
                    expressions,
                    &mut bindings.clone(),
                    signatures,
                    result,
                    console,
                )?;
                live = yes_live || no_live;
            }
            StmtKind::Expr(_) => (),
        }
    }
    Ok(live)
}
pub fn analyze(source: &str) -> Result<Program> {
    let mut program = Parser {
        tokens: lex(source)?,
        at: 0,
        expressions: Vec::new(),
    }
    .program()?;
    let mut signatures = BTreeMap::new();
    for f in &program.functions {
        if ["i32", "bool", "str", "print"].contains(&f.name.text.as_str())
            || signatures
                .insert(
                    f.name.text.clone(),
                    (f.params.iter().map(|p| p.1).collect(), f.result),
                )
                .is_some()
        {
            return Err(error(
                "E0102",
                "Duplicate or reserved declaration",
                f.name.span.clone(),
            ));
        }
    }
    for f in &program.functions {
        let mut bindings = BTreeMap::new();
        for (name, ty) in &f.params {
            if bindings.insert(name.text.clone(), *ty).is_some() {
                return Err(error("E0102", "Duplicate parameter", name.span.clone()));
            }
        }
        if check_block(
            &f.body,
            &mut program.expressions,
            &mut bindings,
            &signatures,
            f.result,
            &mut program.console,
        )? {
            return Err(error(
                "E0205",
                "Function must return on every path",
                f.name.span.clone(),
            ));
        }
    }
    Ok(program)
}
struct Emitter<'a> {
    expressions: &'a [Expr],
    out: String,
    counter: usize,
}
impl Emitter<'_> {
    fn line(&mut self, s: impl AsRef<str>) {
        self.out.push_str(s.as_ref());
        self.out.push('\n');
    }
    fn temp(&mut self, ty: Ty, value: String) -> String {
        self.counter += 1;
        let name = format!("tv_tmp_{}", self.counter);
        self.line(format!("{} {name} = {value};", ty.c()));
        name
    }
    fn expr(&mut self, index: usize) -> String {
        let expr = &self.expressions[index];
        let ty = expr.ty.unwrap();
        match &expr.kind {
            ExprKind::Int(value) => format!("INT32_C({})", value.parse::<u64>().unwrap_or(0)),
            ExprKind::Bool(value) => value.to_string(),
            ExprKind::Name(name) => self.temp(ty, format!("tv_v_{name}")),
            ExprKind::Text(value) => {
                self.counter += 1;
                let name = format!("tv_text_{}", self.counter);
                let bytes = if value.is_empty() {
                    "0".into()
                } else {
                    value
                        .bytes()
                        .map(|b| format!("0x{b:02x}"))
                        .collect::<Vec<_>>()
                        .join(",")
                };
                self.line(format!("static const uint8_t {name}[] = {{{bytes}}};"));
                self.temp(Ty::Text, format!("(tv_str){{{name},{}}}", value.len()))
            }
            ExprKind::Call(name, args) => {
                let values = args
                    .iter()
                    .map(|a| self.expr(*a))
                    .collect::<Vec<_>>()
                    .join(",");
                let callee = if name == "print" {
                    "tv_console_print".into()
                } else {
                    format!("tv_f_{name}")
                };
                self.temp(ty, format!("{callee}({values})"))
            }
            ExprKind::Unary(op, child) => {
                if op == "-"
                    && matches!(&self.expressions[*child].kind, ExprKind::Int(v) if v.trim_start_matches('0') == "2147483648")
                {
                    return "INT32_MIN".into();
                }
                let value = self.expr(*child);
                self.temp(
                    ty,
                    if op == "-" {
                        format!("tv_neg({value})")
                    } else {
                        format!("!({value})")
                    },
                )
            }
            ExprKind::Binary(op, a, b) => {
                let left = self.expr(*a);
                if op == "&&" || op == "||" {
                    let result = self.temp(Ty::Bool, left);
                    self.line(format!(
                        "if ({}{result}) {{",
                        if op == "||" { "!" } else { "" }
                    ));
                    let right = self.expr(*b);
                    self.line(format!("{result} = {right};\n}}"));
                    result
                } else {
                    let right = self.expr(*b);
                    let helper = match op.as_str() {
                        "+" => Some("add"),
                        "-" => Some("sub"),
                        "*" => Some("mul"),
                        "/" => Some("div"),
                        "%" => Some("mod"),
                        _ => None,
                    };
                    let value = helper
                        .map(|h| format!("tv_{h}({left},{right})"))
                        .unwrap_or_else(|| format!("({left}) {op} ({right})"));
                    self.temp(ty, value)
                }
            }
        }
    }
    fn block(&mut self, body: &[Stmt]) {
        for stmt in body {
            match &stmt.kind {
                StmtKind::Let(name, _, expr) => {
                    let value = self.expr(*expr);
                    self.line(format!(
                        "{} tv_v_{} = {value};\n(void)tv_v_{};",
                        self.expressions[*expr].ty.unwrap().c(),
                        name.text,
                        name.text
                    ));
                }
                StmtKind::Return(expr) => {
                    let value = self.expr(*expr);
                    self.line(format!("return {value};"));
                }
                StmtKind::Expr(expr) => {
                    let value = self.expr(*expr);
                    self.line(format!("(void)({value});"));
                }
                StmtKind::If(expr, yes, no) => {
                    let value = self.expr(*expr);
                    self.line(format!("if ({value}) {{"));
                    self.block(yes);
                    self.line("} else {");
                    self.block(no);
                    self.line("}");
                }
            }
        }
    }
}
fn signature(f: &Function) -> String {
    let params = if f.params.is_empty() {
        "void".into()
    } else {
        f.params
            .iter()
            .map(|(name, ty)| format!("{} tv_v_{}", ty.c(), name.text))
            .collect::<Vec<_>>()
            .join(",")
    };
    format!("{} tv_f_{}({params})", f.result.c(), f.name.text)
}
pub fn emit_c(program: &Program, console: bool) -> Result<String> {
    if program.console && !console {
        return Err(error("E0404", "print requires --console", 0..0));
    }
    if !program
        .functions
        .iter()
        .any(|f| f.name.text == "main" && f.params.is_empty() && f.result == Ty::Int)
    {
        return Err(error(
            "E0401",
            "Hosted entry requires fn main() -> i32",
            0..0,
        ));
    }
    let mut emitter = Emitter {
        expressions: &program.expressions,
        out: String::from(include_str!("runtime.c")),
        counter: 0,
    };
    if program.console {
        emitter.line(include_str!("console.c"));
    }
    for f in &program.functions {
        emitter.line(format!("{};", signature(f)));
    }
    for f in &program.functions {
        emitter.line(format!("{} {{", signature(f)));
        for (name, _) in &f.params {
            emitter.line(format!("(void)tv_v_{};", name.text));
        }
        emitter.block(&f.body);
        emitter.line("}");
    }
    emitter.line("int main(void) { return (int)tv_f_main(); }");
    Ok(emitter.out)
}
