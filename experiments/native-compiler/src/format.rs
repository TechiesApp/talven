//! Canonical syntax-only layout. No filesystem writes, configuration or subprocesses.

use crate::{MAX_SOURCE, Result, Token, error, lex_with_comments, parse_program};

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Paren,
    Function,
    Record,
    Block,
    Literal,
}

#[derive(Clone, Copy)]
struct Group {
    kind: Kind,
    multiline: bool,
}

fn groups(tokens: &[Token]) -> Vec<Option<Group>> {
    let mut result = vec![None; tokens.len()];
    let mut stack = Vec::new();
    let mut comments = 0;
    let mut declaration = None;
    let mut previous = None;
    for (index, token) in tokens.iter().enumerate() {
        let kind = token.kind();
        if kind == "comment" {
            comments += 1;
            continue;
        }
        match kind {
            "fn" => declaration = Some(Kind::Function),
            "struct" => declaration = Some(Kind::Record),
            "(" | "{" => {
                let group_kind = if kind == "(" {
                    Kind::Paren
                } else if let Some(declared) = declaration.take() {
                    declared
                } else if matches!(previous, Some(")" | "else")) {
                    Kind::Block
                } else {
                    Kind::Literal
                };
                stack.push((index, group_kind, comments));
            }
            ")" | "}" => {
                let (start, group_kind, initial_comments) = stack.pop().expect("parsed delimiter");
                let group = Group {
                    kind: group_kind,
                    multiline: matches!(group_kind, Kind::Function | Kind::Record | Kind::Block)
                        || comments > initial_comments,
                };
                result[start] = Some(group);
                result[index] = Some(group);
            }
            _ => {}
        }
        previous = Some(kind);
    }
    result
}

#[derive(Default)]
struct Writer {
    lines: Vec<String>,
    line: String,
    indent: usize,
    blank_pending: bool,
    bytes: usize,
}

impl Writer {
    fn account(&mut self, bytes: usize) -> Result<()> {
        self.bytes += bytes;
        if self.bytes > MAX_SOURCE {
            return Err(error(
                "E0602",
                "Formatted source exceeds the 256 KiB prototype limit",
                0..0,
            ));
        }
        Ok(())
    }

    fn write(&mut self, text: &str, space: bool) -> Result<()> {
        let prefix = if self.line.is_empty() {
            if self.blank_pending {
                self.account(1)?;
                self.lines.push(String::new());
                self.blank_pending = false;
            }
            "    ".repeat(self.indent)
        } else if space {
            " ".into()
        } else {
            String::new()
        };
        self.account(prefix.len() + text.len())?;
        self.line.push_str(&prefix);
        self.line.push_str(text);
        Ok(())
    }

    fn newline(&mut self) -> Result<()> {
        if !self.line.is_empty() {
            self.account(1)?;
            self.lines.push(std::mem::take(&mut self.line));
        }
        Ok(())
    }

    fn comment(&mut self, text: &str, inline: bool) -> Result<()> {
        if inline && self.line.is_empty() && !self.lines.is_empty() {
            self.account(1 + text.len())?;
            let line = self.lines.last_mut().expect("preceding line");
            line.push(' ');
            line.push_str(text);
        } else {
            if !inline {
                self.newline()?;
            }
            self.write(text, inline)?;
            self.newline()?;
        }
        Ok(())
    }

    fn finish(mut self) -> Result<String> {
        self.newline()?;
        let mut result = String::with_capacity(self.bytes);
        for line in self.lines {
            result.push_str(&line);
            result.push('\n');
        }
        Ok(result)
    }
}

fn same_tokens(original: &[Token], formatted: &[Token]) -> bool {
    fn text(token: &Token) -> &str {
        if token.kind() == "comment" {
            token.text.strip_suffix('\r').unwrap_or(&token.text)
        } else {
            &token.text
        }
    }
    original.len() == formatted.len()
        && original
            .iter()
            .zip(formatted)
            .all(|(a, b)| a.kind() == b.kind() && text(a) == text(b))
}

/// Format valid grammar even when types, return paths or ownership are invalid.
pub fn format_source(source: &str) -> Result<String> {
    parse_program(source)?;
    let mut tokens = lex_with_comments(source, true)?;
    tokens.pop(); // EOF is not a layout token.
    let delimiters = groups(&tokens);
    let mut writer = Writer::default();
    let mut stack = Vec::new();
    let mut previous = None;
    let mut previous_unary = false;
    let mut ends_expression = false;
    for (index, token) in tokens.iter().enumerate() {
        let kind = token.kind();
        if kind == "comment" {
            let inline =
                index > 0 && !source[tokens[index - 1].span.end..token.span.start].contains('\n');
            writer.comment(token.text.strip_suffix('\r').unwrap_or(&token.text), inline)?;
            continue;
        }
        let unary = matches!(kind, "!" | "&") || (kind == "-" && !ends_expression);
        let mut after_word = !matches!(previous, None | Some("(" | ".")) && !previous_unary;
        if kind == "&" && previous == Some("&") {
            after_word = true; // Preserve two separate borrow tokens rather than &&.
        }
        match kind {
            "(" | "{" => {
                let group = delimiters[index].expect("parsed opening delimiter");
                writer.write(
                    &token.text,
                    kind == "{" || (kind == "(" && previous != Some("id") && after_word),
                )?;
                stack.push(group);
                if group.multiline {
                    writer.newline()?;
                    writer.indent += 1;
                }
            }
            ")" | "}" => {
                let group = stack.pop().expect("parsed closing delimiter");
                if group.multiline {
                    writer.newline()?;
                    writer.indent -= 1;
                }
                writer.write(
                    &token.text,
                    kind == "}" && !group.multiline && previous != Some("{"),
                )?;
                if matches!(group.kind, Kind::Function | Kind::Record | Kind::Block) {
                    let following = tokens.get(index + 1).map(Token::kind);
                    if following != Some("else") {
                        writer.newline()?;
                    }
                    if matches!(group.kind, Kind::Function | Kind::Record) {
                        writer.blank_pending = true;
                    }
                }
            }
            ";" | "," | ":" | "." => {
                writer.write(&token.text, false)?;
                if kind == ";" || (kind == "," && stack.last().is_some_and(|g| g.multiline)) {
                    writer.newline()?;
                }
            }
            _ => writer.write(&token.text, after_word)?,
        }
        ends_expression = if matches!(kind, ")" | "}") {
            matches!(
                delimiters[index].expect("parsed delimiter").kind,
                Kind::Paren | Kind::Literal
            )
        } else {
            matches!(kind, "id" | "int" | "true" | "false" | "text")
        };
        previous = Some(kind);
        previous_unary = unary;
    }
    let formatted = writer.finish()?;
    let mut formatted_tokens = lex_with_comments(&formatted, true)?;
    formatted_tokens.pop();
    if !same_tokens(&tokens, &formatted_tokens) {
        return Err(error(
            "E0604",
            "Formatter could not preserve source tokens; no edit was produced",
            0..0,
        ));
    }
    Ok(formatted)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn syntax_only_comments_and_exact_layout_are_idempotent() {
        let source = "// heading\r\nstruct Empty{} fn f( // params\r\nx:i32,)->i32{return false;// error\r\n}";
        let expected = "// heading\nstruct Empty {\n}\n\nfn f( // params\n    x: i32,\n) -> i32 {\n    return false; // error\n}\n";
        assert_eq!(expected, format_source(source).unwrap());
        assert_eq!(expected, format_source(expected).unwrap());
        assert!(crate::analyze(source).is_err());
        assert_eq!("", format_source(" \t\r\n").unwrap());
    }

    #[test]
    fn comments_and_expanded_output_share_reference_limits() {
        assert_eq!(
            "E0005",
            format_source(&"//\n".repeat(16385)).unwrap_err().code
        );
        let source = format!("//{}", "x".repeat(MAX_SOURCE - 2));
        assert_eq!("E0602", format_source(&source).unwrap_err().code);
        let source = format!("//{}", "x".repeat(MAX_SOURCE - 3));
        assert_eq!(MAX_SOURCE, format_source(&source).unwrap().len());
    }
}
