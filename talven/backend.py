"""C11 lowering with checked i32 arithmetic and explicit evaluation order."""

import re

from .frontend import Analysis, CompileError, Expr, Function, Span, Statement, base_type, borrow_mode, require_entry


def ctype(typ: str) -> str:
    mode = borrow_mode(typ)
    if mode:
        return ("const " if mode == "shared" else "") + f"struct tv_s_{base_type(typ)} *"
    return {"i32": "int32_t", "bool": "bool", "str": "tv_str"}.get(typ, f"struct tv_s_{typ}")


# Emitted only when referenced, so generated C stays warning-free on compilers
# that report unused static functions (clang -Wunused-function).
HELPERS = {
    "tv_narrow": """static inline int32_t tv_narrow(int64_t value) {
    if (value < INT32_MIN || value > INT32_MAX) { talven_trap(); }
    return (int32_t)value;
}""",
    "tv_add": "static inline int32_t tv_add(int32_t a, int32_t b) { return tv_narrow((int64_t)a + b); }",
    "tv_sub": "static inline int32_t tv_sub(int32_t a, int32_t b) { return tv_narrow((int64_t)a - b); }",
    "tv_mul": "static inline int32_t tv_mul(int32_t a, int32_t b) { return tv_narrow((int64_t)a * b); }",
    "tv_neg": "static inline int32_t tv_neg(int32_t a) { return tv_narrow(-(int64_t)a); }",
    "tv_div": """static inline int32_t tv_div(int32_t a, int32_t b) {
    if (b == 0 || (a == INT32_MIN && b == -1)) { talven_trap(); }
    return a / b;
}""",
    "tv_mod": """static inline int32_t tv_mod(int32_t a, int32_t b) {
    if (b == 0 || (a == INT32_MIN && b == -1)) { talven_trap(); }
    return a % b;
}""",
}
HOSTED_TRAP = "static _Noreturn void talven_trap(void) { abort(); }"


def used_helpers(code: str) -> list[str]:
    """Referenced helpers plus their dependencies, in definition order."""
    used = {name for name in HELPERS if re.search(rf"\b{name}\(", code)}
    if used & {"tv_add", "tv_sub", "tv_mul", "tv_neg"}:
        used.add("tv_narrow")
    return [name for name in HELPERS if name in used]


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


MAX_C_UNITS = 256
MAX_C_UNIT_BYTES = 16 * 1024 * 1024


def emission_options(analysis, freestanding, console):
    needs_console = any("print" in fn.calls for fn in analysis.program.functions)
    if console and freestanding:
        raise CompileError("E0404", "Console output requires hosted POSIX emission; --console and --freestanding cannot be combined", Span(0, 0))
    if needs_console and (freestanding or not console):
        raise CompileError("E0404", "print requires hosted POSIX console support; enable --console", Span(0, 0))
    if not freestanding:
        require_entry(analysis)
    return needs_console


def emit_prefix(emitter, analysis, freestanding, needs_console):
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
    if needs_console:
        emitter.lines.append(CONSOLE)
    helpers_at = len(emitter.lines)
    for record in analysis.program.records:
        emitter.line(f"struct tv_s_{record.name.text} {{")
        for name, typ in record.fields:
            emitter.line(f"    {ctype(typ.text)} tv_m_{name.text};")
        emitter.line("};")
    for fn in analysis.program.functions:
        emitter.line(signature(fn) + ";")
    return helpers_at


def emit_function(emitter, fn):
    emitter.line(signature(fn) + " {")
    emitter.indent += 1
    for name, _ in fn.params:
        emitter.line(f"(void)tv_v_{name.text};")
    emitter.block(fn.body)
    emitter.indent -= 1
    emitter.line("}")


def finish_c(emitter, helpers_at, freestanding=False):
    helpers = [HELPERS[name] for name in used_helpers("\n".join(emitter.lines[helpers_at:]))]
    if helpers and not freestanding:
        helpers.insert(0, HOSTED_TRAP)
    emitter.lines[helpers_at:helpers_at] = helpers
    return "\n".join(emitter.lines) + "\n"


def emit_c(analysis: Analysis, freestanding: bool = False, *, console: bool = False) -> str:
    needs_console = emission_options(analysis, freestanding, console)
    emitter = Emitter()
    helpers_at = emit_prefix(emitter, analysis, freestanding, needs_console)
    for fn in analysis.program.functions:
        emit_function(emitter, fn)
    if not freestanding:
        emitter.line("int main(void) { return (int)tv_f_main(); }")
    return finish_c(emitter, helpers_at, freestanding)


def emit_c_units(analysis: Analysis, *, console: bool = False) -> dict[str, str]:
    """Hosted experimental units, sharing checked lowering with ordinary emission.

    Every unit repeats current record layouts and all function declarations.
    Temporary numbering is local to its function; cross-unit calls are external.
    This emits text only, not compiled objects or a reuse/acceptance receipt.
    """
    emission_options(analysis, False, console)
    if len(analysis.program.functions) > MAX_C_UNITS:
        raise CompileError("E0005", "Hosted C units exceed the 256-function experiment limit", Span(0, 0))
    units = {}
    size = 0
    for fn in [*analysis.program.functions, None]:
        emitter = Emitter()
        helpers_at = emit_prefix(emitter, analysis, False, fn is not None and "print" in fn.calls)
        if fn is None:
            identity = "entry"
            emitter.line("int main(void) { return (int)tv_f_main(); }")
        else:
            identity = "fn:" + fn.name.text
            emit_function(emitter, fn)
        generated = finish_c(emitter, helpers_at)
        size += len(generated.encode("utf-8"))
        if size > MAX_C_UNIT_BYTES:
            raise CompileError("E0005", "Hosted C unit text exceeds the 16 MiB experiment limit", Span(0, 0))
        units[identity] = generated
    return units


def emit_preprocess_units(analysis: Analysis, *, console: bool = False) -> tuple[str, list[str]]:
    """One preprocessing input with reserved boundaries, not a C translation unit.

    Repeated static definitions are separated after preprocessing. Common headers
    expand once; every resulting C unit receives the same expanded contracts.
    """
    needs_console = emission_options(analysis, False, console)
    if len(analysis.program.functions) > MAX_C_UNITS:
        raise CompileError("E0005", "Hosted C units exceed the 256-function experiment limit", Span(0, 0))
    prefix = Emitter()
    headers_at = emit_prefix(prefix, analysis, False, False)
    if needs_console:
        prefix.lines[headers_at:headers_at] = ['#include <errno.h>', '#include <unistd.h>']
    prefix.line('extern int tv_unit_header_boundary;')
    segments, identities = ['\n'.join(prefix.lines) + '\n'], []
    for index, fn in enumerate([*analysis.program.functions, None]):
        emitter = Emitter()
        if fn is None:
            identity = 'entry'
            emitter.line('int main(void) { return (int)tv_f_main(); }')
        else:
            identity = 'fn:' + fn.name.text
            if 'print' in fn.calls:
                emitter.lines.append(CONSOLE[CONSOLE.index('static int32_t tv_console_print'):])
            emit_function(emitter, fn)
        segments.append(finish_c(emitter, 0))
        segments.append(f'extern int tv_unit_boundary_{index};\n')
        identities.append(identity)
    result = ''.join(segments)
    if len(result.encode('utf-8')) > MAX_C_UNIT_BYTES:
        raise CompileError('E0005', 'C unit preprocessing input exceeds the 16 MiB experiment limit', Span(0, 0))
    return result, identities
