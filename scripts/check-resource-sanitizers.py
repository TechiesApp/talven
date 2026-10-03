#!/usr/bin/env python3
"""Independent supplied-block source ledger under O0/O2 ASan/UBSan."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from talven.backend import emit_c
from talven.context import compiler_hash
from talven.resources import analyze_resources, runtime_identity

SOURCES = ('tests/fixtures/resources/workload.tal', 'tests/fixtures/resources/driver.c',
           'experiments/supplied-storage/runtime.h', 'experiments/supplied-storage/source-runtime.c',
           'scripts/check-resource-sanitizers.py')

# Fixed public manifest: never follow arbitrary paths supplied by a producer.
NATIVE_SOURCES = ('Cargo.toml', 'Cargo.lock', 'build.rs', 'src/main.rs', 'src/lib.rs',
                  'src/format.rs', 'src/context.rs', 'src/input.rs', 'src/edit.rs',
                  'src/c_api.rs', 'src/runtime.c', 'src/console.c', 'src/resources.rs',
                  '../supplied-storage/runtime.h', '../supplied-storage/source-runtime.c')


def command(args, timeout=30):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode or result.stderr:
        raise RuntimeError('Source acceptance failed: ' + (result.stderr or result.stdout).decode(errors='replace'))
    return result.stdout


def verify(native=None):
    if platform.system() not in ('Linux', 'Darwin') or not shutil.which('cc') or not shutil.which('nm'):
        raise RuntimeError('Source resource gate requires declared Linux/macOS C11 tools; no skips')
    captured = {name: (ROOT / name).read_bytes() for name in SOURCES}
    reference_hash = compiler_hash()
    native_info = json.loads(command([str(native), '--build-info'])) if native else None
    native_digest = hashlib.sha256(native.read_bytes()).hexdigest() if native else None
    if native:
        embedded = native_info.get('source_files', {})
        if set(embedded) != set(NATIVE_SOURCES):
            raise RuntimeError('Native producer source manifest does not match resource gate')
        for name in NATIVE_SOURCES:
            current = (ROOT / 'experiments/native-compiler' / name).read_bytes()
            if not isinstance(embedded[name], str) or embedded[name].encode() != current:
                raise RuntimeError('Native producer embeds stale source: ' + name)
        if not isinstance(native_info.get('compiler_hash'), str):
            raise RuntimeError('Native producer lacks compiler identity')
    records, units = [], []
    flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic-errors']
    with tempfile.TemporaryDirectory(prefix='talven-resource-source-') as temporary:
        directory = Path(temporary)
        (directory / 'driver.c').write_bytes(captured[SOURCES[1]])
        source_path = directory / 'source.tal'
        for capacity in (1, 32, 4096):
            source = captured[SOURCES[0]].decode().replace('storage(32)', f'storage({capacity})')
            # Native producer receives original Talven source, never a resolved/reference AST.
            if native:
                source_path.write_text(source)
                generated = command([str(native), 'emit-c', str(source_path), '--resources']).decode()
            else:
                generated = emit_c(analyze_resources(source))
            (directory / 'generated.c').write_text(generated)
            units.append({'capacity': capacity, 'source': source,
                          'source_hash': hashlib.sha256(source.encode()).hexdigest(),
                          'c_hash': hashlib.sha256(generated.encode()).hexdigest()})
            for optimization in ('-O0', '-O2'):
                for fault in (False, True):
                    settings = [*flags, optimization, '-fsanitize=address,undefined',
                                '-fno-sanitize-recover=all', '-DTV_REGION_SOURCE_TEST',
                                f'-DTEST_CAPACITY={capacity}']
                    if fault:
                        settings.append('-DTV_REGION_TEST_FAULT')
                    binary = directory / 'program'
                    command(['cc', *settings, str(directory / 'driver.c'), '-o', str(binary)])
                    output = command([str(binary)], timeout=30)
                    if output:
                        raise RuntimeError('Unexpected source ledger output')
                    records.append({'capacity': capacity, 'flags': settings,
                                    'fault_injection': fault, 'ledger_passed': True})
        production = directory / 'production.o'
        command(['cc', *flags, '-O2', '-c', str(directory / 'generated.c'), '-o', str(production)])
        symbols = sorted(line.split()[-1].lstrip('_') for line in
                         command(['nm', '-u', str(production)]).decode().splitlines() if line.split())
        permitted = {'abort', 'memset', 'bzero', 'memcpy', 'memmove', 'stack_chk_fail',
                     'stack_chk_guard', 'chkstk_darwin', 'GLOBAL_OFFSET_TABLE_'}
        if set(symbols) - permitted:
            raise RuntimeError('Resource production object has an unapproved dependency: ' +
                               ', '.join(sorted(set(symbols) - permitted)))
    if compiler_hash() != reference_hash or any((ROOT / name).read_bytes() != data for name, data in captured.items()):
        raise RuntimeError('Resource gate inputs changed; rerun with stable source/compiler')
    if native and (hashlib.sha256(native.read_bytes()).hexdigest() != native_digest or
                   json.loads(command([str(native), '--build-info'])) != native_info):
        raise RuntimeError('Native producer changed during resource gate; rebuild and rerun')
    if native and any((ROOT / 'experiments/native-compiler' / name).read_bytes() !=
                      native_info['source_files'][name].encode() for name in NATIVE_SOURCES):
        raise RuntimeError('Native producer source inputs changed during resource gate')
    return {'schema': 'talven.resource-source-check.v1', 'profile': 'm2-supplied-blocks-v1',
            'ok': True, 'producer': 'native' if native else 'reference',
            'compiler_hash': native_info['compiler_hash'] if native else reference_hash,
            'native_build_info': native_info, 'native_binary_hash': native_digest,
            'reference_comparison_hash': reference_hash, 'runtime_inputs': runtime_identity(),
            'environment': {'system': platform.system(), 'release': platform.release(),
                            'machine': platform.machine(), 'python': platform.python_version(),
                            'logical_cpus': os.cpu_count(),
                            'c_target': command(['cc', '-dumpmachine']).decode().strip(),
                            'c_version': command(['cc', '--version']).decode().splitlines()[0]},
            'inputs': [{'path': name, 'sha256': hashlib.sha256(data).hexdigest(),
                        'text': data.decode()} for name, data in captured.items()],
            'units': units, 'executions': records,
            'positive_executions': len(records), 'production': {'flags': [*flags, '-O2'],
                'capacity': 4096, 'undefined_symbols': symbols, 'permitted_symbols': sorted(permitted),
                'dependency_scope': 'generated workload object; excludes hosted startup/libc'},
            'limits': ['sequential source profile; no heap containers or concurrency',
                       'trusted ledger/fault hooks excluded from production',
                       'no latency, stack/binary size or live-agent benefit measured']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, help='Independent already-built native compiler')
    parser.add_argument('--out', type=Path, help='Create a new JSON receipt, default stdout')
    args = parser.parse_args()
    if args.out and args.out.exists():
        parser.error('--out must be a new file')
    report = json.dumps(verify(args.native.resolve() if args.native else None), indent=2, sort_keys=True) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x', encoding='utf-8') as output:
            output.write(report)
    else:
        print(report, end='')


if __name__ == '__main__':
    main()
