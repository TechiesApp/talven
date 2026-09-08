"""A bounded, token-preserving layout shared by CLI and editor formatting.

Comments remain inert text. No configuration, plugin, package, or subprocess
is loaded. Formatting requires syntax, not successful type/ownership checking.
"""

from dataclasses import dataclass

from .frontend import CompileError, MAX_SOURCE_BYTES, Span, Token, lex, parse


@dataclass
class Group:
    kind: str
    multiline: bool


def groups(tokens: list[Token]) -> dict[int, Group]:
    """Classify matched delimiters using the already validated grammar."""
    result = {}
    stack = []
    comments = 0
    declaration = None
    previous = None
    for index, token in enumerate(tokens):
        kind = token.kind
        if kind == "comment":
            comments += 1
            continue
        if kind in ("fn", "struct"):
            declaration = kind
        elif kind in ("(", "{"):
            group_kind = "paren"
            if kind == "{":
                if declaration:
                    group_kind, declaration = declaration, None
                else:
                    group_kind = "block" if previous in (")", "else") else "literal"
            stack.append((index, group_kind, comments))
        elif kind in (")", "}"):
            start, group_kind, initial_comments = stack.pop()
            group = Group(group_kind, group_kind in ("fn", "struct", "block") or comments > initial_comments)
            result[start] = result[index] = group
        previous = kind
    return result


class Writer:
    def __init__(self):
        self.lines: list[str] = []
        self.line = ""
        self.indent = 0
        self.blank_pending = False
        self.bytes = 0

    def account(self, text: str):
        self.bytes += len(text.encode("utf-8"))
        if self.bytes > MAX_SOURCE_BYTES:
            raise CompileError("E0602", "Formatted source exceeds the 256 KiB prototype limit", Span(0, 0))

    def write(self, text: str, space: bool = False):
        if not self.line:
            if self.blank_pending:
                self.lines.append("")
                self.account("\n")
                self.blank_pending = False
            prefix = "    " * self.indent
        else:
            prefix = " " if space else ""
        self.account(prefix + text)
        self.line += prefix + text

    def newline(self):
        if self.line:
            self.lines.append(self.line)
            self.account("\n")
            self.line = ""

    def comment(self, text: str, inline: bool):
        if inline and not self.line and self.lines:
            # A preceding semicolon or block delimiter may have flushed its
            # line. Keep the original trailing comment on that same token.
            self.account(" " + text)
            self.lines[-1] += " " + text
        else:
            if not inline:
                self.newline()
            self.write(text, space=inline)
            self.newline()

    def finish(self) -> str:
        self.newline()
        return "".join(line + "\n" for line in self.lines)


def token_identity(tokens: list[Token]) -> list[tuple[str, str]]:
    # The lexer includes the CR of a CRLF comment in its text. Normalize only
    # that trailing line-ending character; all other comment text is retained.
    return [(t.kind, t.text.removesuffix("\r") if t.kind == "comment" else t.text)
            for t in tokens if t.kind != "eof"]


def format_source(source: str) -> str:
    parse(source)
    tokens = lex(source, include_comments=True)[:-1]
    delimiters = groups(tokens)
    writer = Writer()
    stack: list[Group] = []
    previous = None
    previous_unary = False
    ends_expression = False
    for index, token in enumerate(tokens):
        kind = token.kind
        if kind == "comment":
            before = tokens[index - 1] if index else None
            inline = before is not None and "\n" not in source[before.span.end:token.span.start]
            writer.comment(token.text.removesuffix("\r"), inline)
            continue
        unary = kind in ("!", "&") or (kind == "-" and not ends_expression)
        after_word = previous not in (None, "(", ".") and not previous_unary
        if kind == "&" and previous == "&":
            after_word = True  # Do not merge two borrow tokens into &&.
        if kind in ("(", "{"):
            group = delimiters[index]
            writer.write(token.text, space=(kind == "{" or (kind == "(" and previous != "id" and after_word)))
            stack.append(group)
            if group.multiline:
                writer.newline()
                writer.indent += 1
        elif kind in (")", "}"):
            group = stack.pop()
            if group.multiline:
                writer.newline()
                writer.indent -= 1
            writer.write(token.text, space=kind == "}" and not group.multiline and previous != "{")
            if group.kind in ("fn", "struct", "block"):
                following = tokens[index + 1].kind if index + 1 < len(tokens) else None
                if following != "else":
                    writer.newline()
                if group.kind in ("fn", "struct"):
                    writer.blank_pending = True
        elif kind in (";", ",", ":", "."):
            writer.write(token.text)
            if kind == ";" or (kind == "," and stack and stack[-1].multiline):
                writer.newline()
        else:
            writer.write(token.text, space=after_word)
        if kind in (")", "}"):
            ends_expression = delimiters[index].kind in ("paren", "literal")
        else:
            ends_expression = kind in ("id", "int", "true", "false", "text")
        previous, previous_unary = kind, unary
    formatted = writer.finish()
    if token_identity(lex(formatted, include_comments=True)) != token_identity(tokens):
        raise CompileError("E0604", "Formatter could not preserve source tokens; no edit was produced", Span(0, 0))
    return formatted
