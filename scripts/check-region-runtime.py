#!/usr/bin/env python3
"""Verify the C runtime prototype with an independent ledger; no Talven grammar."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('experiments/supplied-storage/runtime.h', 'tests/fixtures/region-runtime-driver.c',
           'scripts/check-region-runtime.py')


def run(command, *, timeout=30):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Trusted tool failed: {result.stderr or result.stdout}')
    return result.stdout


def verify():
    if platform.system() not in ('Linux', 'Darwin'):
        raise RuntimeError('This prototype requires the declared Linux/macOS hosted test boundary')
    if not shutil.which('cc') or not shutil.which('nm'):
        raise RuntimeError('The runtime gate requires cc and nm; skipping is not evidence')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    inputs = {name: (ROOT / name).read_bytes() for name in SOURCES}
    flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic-errors']
    sanitizers = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
    records = []
    with tempfile.TemporaryDirectory(prefix='talven-regions-') as temporary:
        directory = Path(temporary)
        # Compile the exact captured input bytes, then reject observed changes.
        (directory / 'runtime.h').write_bytes(inputs[SOURCES[0]])
        (directory / 'driver.c').write_bytes(inputs[SOURCES[1]])
        executable = directory / 'check'
        for capacity in (1, 32, 4096):
            for optimization in ('-O0', '-O2'):
                for fault in (False, True):
                    settings = [*flags, optimization, *sanitizers, f'-DCAPACITY={capacity}']
                    if fault:
                        settings.append('-DTV_REGION_TEST_FAULT')
                    run(['cc', *settings, str(directory / 'driver.c'), '-o', str(executable)])
                    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
                    if result.returncode or result.stderr:
                        raise RuntimeError('Independent runtime ledger failed: ' + result.stderr)
                    layout = json.loads(result.stdout)
                    if set(layout) != {'capacity', 'descriptor_bytes', 'block_bytes', 'allocation_bytes'} or layout['capacity'] != capacity:
                        raise RuntimeError('Unexpected runtime layout receipt')
                    for key in ('descriptor_bytes', 'block_bytes', 'allocation_bytes'):
                        if type(layout[key]) is not int or layout[key] <= 0:
                            raise RuntimeError('Invalid measured C layout')
                    probes = []
                    for probe in ('stale', 'double', 'length', 'alignment', 'instance', 'read-released'):
                        result = subprocess.run([str(executable), probe], capture_output=True, text=True, timeout=5)
                        if result.returncode != -signal.SIGABRT:
                            raise RuntimeError('Contract probe did not abort: ' + probe)
                        if 'AddressSanitizer' in result.stderr or 'runtime error:' in result.stderr:
                            raise RuntimeError('Contract probe caused a sanitizer failure: ' + probe)
                        probes.append(probe)
                    records.append({'flags': settings, 'fault_injection': fault, 'layout': layout,
                                    'ledger_passed': True, 'abort_probes': probes})
        wrapper = directory / 'production.c'
        wrapper.write_text('''#include "runtime.h"
void init(tv_region *r, uint8_t *s, size_t n) { tv_region_init(r,s,n); }
tv_allocation reserve(tv_region *r, int32_t n, int32_t a) { return tv_region_reserve(r,n,a); }
int32_t release(tv_block b) { return tv_region_release(b); }
tv_byte_read read_byte(const tv_block *b, int32_t i) { return tv_region_read(b,i); }
uint32_t write_byte(tv_block *b, int32_t i, int32_t v) { return tv_region_write(b,i,v); }
''')
        obj = directory / 'production.o'
        run(['cc', *flags, '-O2', '-c', str(wrapper), '-o', str(obj)])
        undefined = run(['nm', '-u', str(obj)])
        symbols = sorted(line.split()[-1].lstrip('_') for line in undefined.splitlines() if line.split())
        permitted = {'abort', 'memset', 'memcpy', 'memmove', 'stack_chk_fail',
                     'stack_chk_guard', 'GLOBAL_OFFSET_TABLE_'}
        if set(symbols) - permitted:
            raise RuntimeError('Production object has an unapproved dependency: ' +
                               ', '.join(sorted(set(symbols) - permitted)))
        # The generated wrapper is retained so dependency inspection can be repeated.
        production_wrapper = wrapper.read_text()
    if any((ROOT / name).read_bytes() != data for name, data in inputs.items()):
        raise RuntimeError('Observed runtime gate input change; rerun with stable sources')
    return {'schema': 'talven.region-runtime-check.v1', 'profile': 'c11-single-slot-regions-v1',
            'validation': 'C-runtime-only; no Talven lifetime checking', 'ok': True,
            'environment': {'system': platform.system(), 'release': platform.release(),
                            'machine': platform.machine(), 'logical_cpus': os.cpu_count(),
                            'c_target': run(['cc', '-dumpmachine']).strip(),
                            'c_version': run(['cc', '--version']).splitlines()[0]},
            'inputs': [{'path': name, 'sha256': hashlib.sha256(data).hexdigest(),
                        'text': data.decode('utf-8')} for name, data in inputs.items()],
            'executions': records, 'positive_executions': len(records),
            'negative_trap_executions': sum(len(r['abort_probes']) for r in records),
            'production': {'flags': [*flags, '-O2'], 'wrapper': production_wrapper,
                           'undefined_symbols': symbols,
                           'permitted_symbols': sorted(permitted),
                           'dependency_scope': 'this object; excludes hosted startup/libc internals'},
            'limits': ['C callers must keep aligned storage and live descriptors valid',
                       'no source move, loan, scope-exit or consume-and-release checking',
                       'layout excludes backing capacity, live temporaries and test ledger',
                       'no latency, total stack, executable-size or agent-benefit measurement']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='Create a new JSON evidence file; default stdout')
    args = parser.parse_args()
    if args.out and args.out.exists():
        parser.error('--out must be a new file')
    report = verify()
    data = json.dumps(report, sort_keys=True, indent=2) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x', encoding='utf-8') as output:
            output.write(data)
    else:
        print(data, end='')


if __name__ == '__main__':
    main()
