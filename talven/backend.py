"""C11 lowering with checked i32 arithmetic and explicit evaluation order."""

import re

from .frontend import Analysis, CompileError, Expr, Function, Outcome, Span, Statement, base_type, borrow_mode, require_entry


def ctype(typ: str, *, resources: bool = False) -> str:
    mode = borrow_mode(typ)
    if resources and base_type(typ) == "Block":
        return ("const " if mode == "shared" else "") + "tv_block" + (" *" if mode else "")
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
    def __init__(self, *, resources: bool = False):
        self.resources = resources
        self.lines: list[str] = []
        self.indent = 0
        self.counter = 0
        self.outcomes: dict[str, Outcome] = {}

    def ctype(self, typ: str) -> str:
        return ctype(typ, resources=self.resources)

    def line(self, text: str):
        self.lines.append("    " * self.indent + text)

    def temp(self, typ: str, value: str) -> str:
        self.counter += 1
        name = f"tv_tmp_{self.counter}"
        self.line(f"{self.ctype(typ)} {name} = {value};")
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
        if kind == "outcome":
            owner, variant = value.split("::")
            variants = self.outcomes[owner].variants
            tag = next(i for i, (name, _) in enumerate(variants) if name.text == variant)
            payload = f", .tv_payload.tv_m_{variant} = {self.expr(expr.args[0])}" if expr.args else ""
            return self.temp(expr.typ, f"(struct tv_s_{owner}){{.tv_tag = {tag}{payload}}}")
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
            if self.resources and expr.typ == "region":
                return f"&tv_region_{value}"
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
            if self.resources and value in ("reserve", "release", "read_byte", "write_byte"):
                callee = {"reserve": "tv_source_reserve", "release": "tv_source_release",
                          "read_byte": "tv_source_read", "write_byte": "tv_source_write"}[value]
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
            if self.resources and stmt.kind == "region":
                name, capacity = stmt.name.text, int(stmt.expr.value.lstrip("0") or "0")
                self.line("{")
                self.indent += 1
                self.line(f"_Alignas(16) uint8_t tv_storage_{name}[{capacity}];")
                self.line(f"tv_region tv_region_{name};")
                self.line(f"tv_source_init(&tv_region_{name}, tv_storage_{name}, {capacity});")
                self.block(stmt.then)
                self.indent -= 1
                self.line("}")
                continue
            value = self.expr(stmt.expr)
            if stmt.kind == "let":
                self.line(f"{self.ctype(stmt.expr.typ)} tv_v_{stmt.name.text} = {value};")
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
            elif stmt.kind == "match":
                outcome = self.outcomes[stmt.expr.typ]
                variants = {name.text: (i, payload) for i, (name, payload) in enumerate(outcome.variants)}
                self.line(f"switch (({value}).tv_tag) {{")
                self.indent += 1
                for arm in stmt.arms:
                    tag, payload = variants[arm.variant.text]
                    self.line(f"case {tag}: {{")
                    self.indent += 1
                    if payload:
                        self.line(f"{self.ctype(payload.text)} tv_v_{arm.binding.text} = ({value}).tv_payload.tv_m_{arm.variant.text};")
                        self.line(f"(void)tv_v_{arm.binding.text};")
                    self.block(arm.body)
                    self.line("break;")
                    self.indent -= 1
                    self.line("}")
                self.line("default: { talven_trap(); }")
                self.indent -= 1
                self.line("}")


def signature(fn: Function, *, parameter_names: bool = True, resources: bool = False) -> str:
    params = ", ".join(f"{ctype(t.text, resources=resources)} tv_v_{n.text}" if parameter_names else ctype(t.text, resources=resources)
                       for n, t in fn.params) or "void"
    return f"{ctype(fn.result.text, resources=resources)} tv_f_{fn.name.text}({params})"


MAX_C_UNITS = 256
MAX_C_UNIT_BYTES = 16 * 1024 * 1024


def emission_options(analysis, freestanding, console, *, library=False):
    if analysis.resources and freestanding:
        raise CompileError("E0404", "Supplied blocks require hosted C11 emission", Span(0, 0))
    needs_console = any("print" in fn.calls for fn in analysis.program.functions)
    if console and freestanding:
        raise CompileError("E0404", "Console output requires hosted POSIX emission; --console and --freestanding cannot be combined", Span(0, 0))
    if needs_console and (freestanding or not console):
        raise CompileError("E0404", "print requires hosted POSIX console support; enable --console", Span(0, 0))
    if library and freestanding:
        raise CompileError("E1001", "C API emission requires hosted C11", Span(0, 0))
    if not freestanding and not library:
        require_entry(analysis)
    return needs_console


def emit_prefix(emitter, analysis, freestanding, needs_console, *, functions=None, parameter_names=True):
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
    records = sorted(analysis.program.records, key=lambda r: isinstance(r, Outcome))
    if analysis.resources:
        from .resources import runtime_sources
        header, adapter = runtime_sources()
        emitter.lines.append(header.rstrip("\n"))
        scalar_records = [r for r in records if not isinstance(r, Outcome)]
        user_outcomes = [r for r in records if isinstance(r, Outcome)]
        records = [*scalar_records, *(analysis.records[n] for n in ("Allocation", "ByteRead", "ByteWrite")), *user_outcomes]
    for record in records:
        emitter.line(f"struct tv_s_{record.name.text} {{")
        if isinstance(record, Outcome):
            emitter.outcomes[record.name.text] = record
            emitter.line("    uint32_t tv_tag;")
            emitter.line("    union {")
            for name, payload in record.variants:
                if payload:
                    emitter.line(f"        {emitter.ctype(payload.text)} tv_m_{name.text};")
            if not any(payload for _, payload in record.variants):
                emitter.line("        uint8_t tv_empty;")
            emitter.line("    } tv_payload;")
        else:
            for name, typ in record.fields:
                emitter.line(f"    {emitter.ctype(typ.text)} tv_m_{name.text};")
        emitter.line("};")
    if analysis.resources:
        emitter.lines.append(adapter.rstrip("\n"))
    for fn in (analysis.program.functions if functions is None else functions):
        emitter.line(signature(fn, parameter_names=parameter_names, resources=analysis.resources) + ";")
    return helpers_at


def emit_function(emitter, fn):
    emitter.line(signature(fn, resources=emitter.resources) + " {")
    emitter.indent += 1
    for name, _ in fn.params:
        emitter.line(f"(void)tv_v_{name.text};")
    emitter.block(fn.body)
    emitter.indent -= 1
    emitter.line("}")


def finish_c(emitter, helpers_at, freestanding=False):
    helpers = [HELPERS[name] for name in used_helpers("\n".join(emitter.lines[helpers_at:]))]
    if not freestanding and (helpers or any("talven_trap();" in line for line in emitter.lines[helpers_at:])):
        helpers.insert(0, HOSTED_TRAP)
    emitter.lines[helpers_at:helpers_at] = helpers
    return "\n".join(emitter.lines) + "\n"


def emit_c(analysis: Analysis, freestanding: bool = False, *, console: bool = False, library: bool = False) -> str:
    needs_console = emission_options(analysis, freestanding, console, library=library)
    emitter = Emitter(resources=analysis.resources)
    helpers_at = emit_prefix(emitter, analysis, freestanding, needs_console)
    for fn in analysis.program.functions:
        emit_function(emitter, fn)
    if not freestanding and not library:
        emitter.line("int main(void) { return (int)tv_f_main(); }")
    return finish_c(emitter, helpers_at, freestanding)


def local_function_contracts(analysis, fn):
    names = {fn.name.text, *fn.calls} if fn is not None else {'main'}
    return [analysis.functions[name] for name in sorted(names) if name in analysis.functions]


def emit_c_units(analysis: Analysis, *, console: bool = False, local_contracts: bool = False) -> dict[str, str]:
    """Hosted experimental units, sharing checked lowering with ordinary emission.

    Every unit repeats current record layouts; selected prototypes are opt-in.
    Temporary numbering is local to its function; cross-unit calls are external.
    This emits text only, not compiled objects or a reuse/acceptance receipt.
    """
    if analysis.resources:
        raise CompileError("E0502", "Supplied blocks do not support hosted C units", Span(0, 0))
    if type(local_contracts) is not bool:
        raise ValueError('Local contracts must be an explicit boolean')
    emission_options(analysis, False, console)
    if len(analysis.program.functions) > MAX_C_UNITS:
        raise CompileError("E0005", "Hosted C units exceed the 256-function experiment limit", Span(0, 0))
    units = {}
    size = 0
    for fn in [*analysis.program.functions, None]:
        emitter = Emitter()
        helpers_at = emit_prefix(emitter, analysis, False, fn is not None and "print" in fn.calls,
                                 functions=local_function_contracts(analysis, fn) if local_contracts else None,
                                 parameter_names=not local_contracts)
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


def emit_preprocess_units(analysis: Analysis, *, console: bool = False,
                          local_contracts: bool = False) -> tuple[str, list[str]]:
    """One preprocessing input with reserved boundaries, not a C translation unit.

    Repeated static definitions are separated after preprocessing. Common headers
    expand once; layouts remain global and selected prototypes are opt-in.
    """
    if analysis.resources:
        raise CompileError("E0502", "Supplied blocks do not support hosted C units", Span(0, 0))
    if type(local_contracts) is not bool:
        raise ValueError('Local contracts must be an explicit boolean')
    needs_console = emission_options(analysis, False, console)
    if len(analysis.program.functions) > MAX_C_UNITS:
        raise CompileError("E0005", "Hosted C units exceed the 256-function experiment limit", Span(0, 0))
    prefix = Emitter()
    headers_at = emit_prefix(prefix, analysis, False, False, functions=[] if local_contracts else None)
    if needs_console:
        prefix.lines[headers_at:headers_at] = ['#include <errno.h>', '#include <unistd.h>']
    prefix.line('extern int tv_unit_header_boundary;')
    segments, identities = ['\n'.join(prefix.lines) + '\n'], []
    for index, fn in enumerate([*analysis.program.functions, None]):
        emitter = Emitter()
        if local_contracts:
            for declared in local_function_contracts(analysis, fn):
                emitter.line(signature(declared, parameter_names=False) + ';')
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
