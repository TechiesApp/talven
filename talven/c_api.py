"""Bounded named C11 scalar exports; no foreign imports, writes or execution."""
import re

from . import PROFILE
from .backend import emit_c
from .context import compiler_hash, encode, source_hash
from .frontend import Analysis, CompileError, Span

SCHEMA = 'talven.c-api.v1'
ABI_PROFILE = 'hosted-c11-scalars-v1'
MAX_BYTES = 16 * 1024 * 1024
MAX_EXPORTS = 128
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9]{0,63}\Z')


def emit_c_api(analysis: Analysis, module: str, exports: list[str], *, console=False,
               max_bytes=MAX_BYTES) -> dict:
    if not isinstance(module, str) or not IDENTIFIER.fullmatch(module):
        raise CompileError('E1001', 'C API module must be an ASCII identifier of 1 through 64 bytes', Span(0, 0))
    if not isinstance(exports, list) or not 1 <= len(exports) <= MAX_EXPORTS or any(not isinstance(n, str) for n in exports) or len(set(exports)) != len(exports):
        raise CompileError('E1001', 'C API requires 1 through 128 distinct function exports', Span(0, 0))
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1 <= max_bytes <= MAX_BYTES:
        raise CompileError('E1002', 'C API budget must be between 1 byte and 16 MiB', Span(0, 0))
    # Length-framed module names prevent collisions between a_b/c and a/b_c.
    prefix = f'm{len(module)}_{module}'
    facts, declarations, wrappers = [], [], []
    types = {'i32': 'int32_t', 'bool': 'bool'}
    for name in sorted(exports):
        if name not in analysis.functions:
            raise CompileError('E1001', f'Unknown C API function {name}', Span(0, 0))
        fn = analysis.functions[name]
        if fn.result.text not in types or any(t.text not in types for _, t in fn.params):
            raise CompileError('E1001', f'C API function {name} must use only i32/bool parameters and result', fn.name.span)
        symbol = f'talven_{prefix}_f_{name}'
        params = ', '.join(f'{types[t.text]} tv_v_{n.text}' for n, t in fn.params) or 'void'
        signature = f'{types[fn.result.text]} {symbol}({params})'
        declarations.append(signature + ';')
        args = ', '.join(f'tv_v_{n.text}' for n, _ in fn.params)
        wrappers.append(signature + f' {{\n    return tv_{prefix}_f_{name}({args});\n}}\n')
        facts.append({'name': name, 'symbol': symbol, 'parameters': [{'name': n.text, 'type': t.text} for n, t in fn.params], 'returns': fn.result.text})
    code = emit_c(analysis, console=console, library=True)
    # Generated string data is emitted as numeric bytes; source comments never
    # enter C. Rewrite only complete compiler-owned identifier tokens.
    code = re.sub(r'\btv_([fs])_([A-Za-z_0-9]+)\b', lambda m: f'tv_{prefix}_{m[1]}_{m[2]}', code)
    code += ''.join(wrappers)
    guard = f'TALVEN_C_API_{prefix}_V1_INCLUDED'
    header = (f'/* Talven {ABI_PROFILE}; module {module}. */\n#ifndef {guard}\n#define {guard}\n'
              '#include <stdint.h>\n#include <stdbool.h>\n' + '\n'.join(declarations) + '\n#endif\n')
    result = {'schema': SCHEMA, 'abi_profile': ABI_PROFILE, 'language_profile': PROFILE,
              'compiler_hash': compiler_hash(), 'source_hash': source_hash(analysis.source),
              'target': 'c11-hosted', 'validation': 'frontend-only', 'module': module, 'console': console,
              'exports': facts, 'header': header, 'header_hash': source_hash(header), 'c': code, 'c_hash': source_hash(code)}
    if len(encode(result).encode()) > max_bytes:
        raise CompileError('E1002', 'C API receipt exceeds byte budget', Span(0, 0))
    return result
