"""C11 lowering with checked i32 arithmetic and explicit evaluation order."""

from .frontend import Analysis, CompileError, Expr, Function, Span, Statement, base_type, borrow_mode, require_entry


def ctype(typ: str) -> str:
    mode = borrow_mode(typ)
    if mode:
        return ("const " if mode == "shared" else "") + f"struct tv_s_{base_type(typ)} *"
    return {"i32": "int32_t", "bool": "bool", "str": "tv_str"}.get(typ, f"struct tv_s_{typ}")


HELPERS = """
static inline int32_t tv_narrow(int64_t value) {
    if (value < INT32_MIN || value > INT32_MAX) { talven_trap(); }
    return (int32_t)value;
}
static inline int32_t tv_add(int32_t a, int32_t b) { return tv_narrow((int64_t)a + b); }
static inline int32_t tv_sub(int32_t a, int32_t b) { return tv_narrow((int64_t)a - b); }
static inline int32_t tv_mul(int32_t a, int32_t b) { return tv_narrow((int64_t)a * b); }
static inline int32_t tv_neg(int32_t a) { return tv_narrow(-(int64_t)a); }
static inline int32_t tv_div(int32_t a, int32_t b) {
    if (b == 0 || (a == INT32_MIN && b == -1)) { talven_trap(); }
    return a / b;
}
static inline int32_t tv_mod(int32_t a, int32_t b) {
    if (b == 0 || (a == INT32_MIN && b == -1)) { talven_trap(); }
    return a % b;
}
"""


CONSOLE = """
#include <errno.h>
#include <unistd.h>
static int32_t tv_console_print(tv_str text) {
    size_t offset = 0;
    while (offset < text.len) {
        size_t count = text.len - offset;
        if (count > 16384) { count = 16384; }
        ssize_t written = write(STDOUT_FILENO, text.data + offset, count);
        if (written < 0) {
            if (errno == EINTR) { continue; }
            return INT32_C(1);
        }
        if (written == 0) { return INT32_C(1); }
        offset += (size_t)written;
    }
    return INT32_C(0);
}
"""


class Emitter:
    def __init__(self):
        self.lines: list[str] = []
        self.indent = 0
        self.counter = 0

    def line(self, text: str):
        self.lines.append("    " * self.indent + text)

    def temp(self, typ: str, value: str) -> str:
        self.counter += 1
        name = f"tv_tmp_{self.counter}"
        self.line(f"{ctype(typ)} {name} = {value};")
        return name

    def place(self, expr: Expr) -> str:
        """A checked addressable location, without copying its record."""
        if expr.kind == "name":
            name = f"tv_v_{expr.value}"
            return f"(*{name})" if borrow_mode(expr.typ) else name
        if expr.kind == "field":
            return f"({self.place(expr.args[0])}).tv_m_{expr.value}"
        raise AssertionError(expr.kind)

    def expr(self, expr: Expr) -> str:
        kind, value = expr.kind, expr.value
        if kind == "int":
            return f"INT32_C({int(value.lstrip('0') or '0')})"
        if kind == "bool":
            return value
        if kind == "text":
            data = value.encode("utf-8")
            self.counter += 1
            name = f"tv_text_{self.counter}"
            self.line(f"static const uint8_t {name}[] = {{")
            for offset in range(0, len(data), 16):
                self.line("    " + ", ".join(f"0x{byte:02x}" for byte in data[offset:offset + 16]) + ",")
            if not data:
                self.line("    0")
            self.line("};")
            return self.temp("str", f"(tv_str){{{name}, {len(data)}}}")
        if kind == "name":
            return self.temp(expr.typ, f"tv_v_{value}")
        if kind == "field":
            base = expr.args[0]
            record = self.place(base) if base.kind == "name" else self.expr(base)
            # Capture scalar reads now, before later operands/arguments can
            # mutate their source through an exclusive borrow.
            return self.temp(expr.typ, f"({record}).tv_m_{value}")
        if kind == "borrow":
            return self.temp(expr.typ, f"&({self.place(expr.args[0])})")
        if kind == "record":
            fields = [f".tv_m_{name.text} = {self.expr(child)}" for name, child in expr.fields]
            return self.temp(expr.typ, f"(struct tv_s_{value}){{{', '.join(fields)}}}")
        if kind == "call":
            args = [self.expr(child) for child in expr.args]
            callee = "tv_console_print" if value == "print" else f"tv_f_{value}"
            return self.temp(expr.typ, f"{callee}({', '.join(args)})")
        if kind == "unary":
            child = expr.args[0]
            if value == "-" and child.kind == "int" and (child.value.lstrip("0") or "0") == "2147483648":
                return "INT32_MIN"
            operand = self.expr(child)
            return self.temp(expr.typ, f"tv_neg({operand})" if value == "-" else f"!({operand})")
        if kind == "binary":
            left = self.expr(expr.args[0])
            if value in ("&&", "||"):
                result = self.temp("bool", left)
                self.line(f"if ({result if value == '&&' else '!' + result}) {{")
                self.indent += 1
                right = self.expr(expr.args[1])
                self.line(f"{result} = {right};")
                self.indent -= 1
                self.line("}")
                return result
            right = self.expr(expr.args[1])
            helper = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod"}.get(value)
            expression = f"tv_{helper}({left}, {right})" if helper else f"({left}) {value} ({right})"
            return self.temp(expr.typ, expression)
        raise AssertionError(kind)

    def block(self, body: list[Statement]):
        for stmt in body:
            value = self.expr(stmt.expr)
            if stmt.kind == "let":
                self.line(f"{ctype(stmt.expr.typ)} tv_v_{stmt.name.text} = {value};")
                self.line(f"(void)tv_v_{stmt.name.text};")
            elif stmt.kind == "return":
                self.line(f"return {value};")
            elif stmt.kind == "expr":
                self.line(f"(void)({value});")
            elif stmt.kind == "assign":
                self.line(f"{self.place(stmt.target)} = {value};")
            elif stmt.kind == "if":
                self.line(f"if ({value}) {{")
                self.indent += 1
                self.block(stmt.then)
                self.indent -= 1
                self.line("} else {")
                self.indent += 1
                self.block(stmt.otherwise)
                self.indent -= 1
                self.line("}")


def signature(fn: Function) -> str:
    params = ", ".join(f"{ctype(t.text)} tv_v_{n.text}" for n, t in fn.params) or "void"
    return f"{ctype(fn.result.text)} tv_f_{fn.name.text}({params})"


def emit_c(analysis: Analysis, freestanding: bool = False, *, console: bool = False) -> str:
    needs_console = any("print" in fn.calls for fn in analysis.program.functions)
    if console and freestanding:
        raise CompileError("E0404", "Console output requires hosted POSIX emission; --console and --freestanding cannot be combined", Span(0, 0))
    if needs_console and (freestanding or not console):
        raise CompileError("E0404", "print requires hosted POSIX console support; enable --console", Span(0, 0))
    if not freestanding:
        require_entry(analysis)
    emitter = Emitter()
    emitter.line("/* Generated by the Talven static-text prototype. */")
    emitter.line("#include <stdint.h>")
    emitter.line("#include <stdbool.h>")
    emitter.line("#include <stddef.h>")
    emitter.line("typedef struct { const uint8_t *data; size_t len; } tv_str;")
    if freestanding:
        emitter.line("extern _Noreturn void talven_trap(void);")
    else:
        emitter.line("#include <stdlib.h>")
        emitter.line("#include <limits.h>")
        emitter.line('_Static_assert(INT_MAX >= INT32_MAX, "Talven hosted entry requires at least 32-bit int");')
        emitter.line("static _Noreturn void talven_trap(void) { abort(); }")
    if needs_console:
        emitter.lines.append(CONSOLE)
    emitter.lines.append(HELPERS)
    for record in analysis.program.records:
        emitter.line(f"struct tv_s_{record.name.text} {{")
        for name, typ in record.fields:
            emitter.line(f"    {ctype(typ.text)} tv_m_{name.text};")
        emitter.line("};")
    for fn in analysis.program.functions:
        emitter.line(signature(fn) + ";")
    for fn in analysis.program.functions:
        emitter.line(signature(fn) + " {")
        emitter.indent += 1
        for name, _ in fn.params:
            emitter.line(f"(void)tv_v_{name.text};")
        emitter.block(fn.body)
        emitter.indent -= 1
        emitter.line("}")
    if not freestanding:
        emitter.line("int main(void) { return (int)tv_f_main(); }")
    return "\n".join(emitter.lines) + "\n"
