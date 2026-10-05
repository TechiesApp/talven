#!/usr/bin/env python3
"""Verify the C-only supplied byte buffer against an independent request ledger."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('experiments/supplied-storage/runtime.h', 'experiments/byte-buffer/runtime.h',
           'tests/fixtures/byte-buffer-driver.c', 'scripts/check-byte-buffer-runtime.py',
           'tests/test_byte_buffer_runtime.py')
PROBES = ('stale', 'double', 'length', 'block-capacity', 'alignment', 'instance',
          'read-closed', 'write-closed', 'push-closed', 'pop-closed', 'length-closed', 'capacity-closed')
FLAGS = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic-errors']
SANITIZERS = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
PERMITTED = {'abort', 'bzero', 'memcpy', 'memmove', 'memset', 'stack_chk_fail',
             'stack_chk_guard', 'chkstk_darwin', 'GLOBAL_OFFSET_TABLE_'}
WRAPPER = '''#include "experiments/byte-buffer/runtime.h"
void init(tv_region *r, uint8_t *s, size_t n) { tv_region_init(r,s,n); }
tv_buffer_allocation reserve(tv_region *r, int32_t n) { return tv_buffer_reserve(r,n); }
int32_t length(const tv_buffer *b) { return tv_buffer_length(b); }
int32_t capacity(const tv_buffer *b) { return tv_buffer_capacity(b); }
tv_byte_read read_byte(const tv_buffer *b, int32_t i) { return tv_buffer_read(b,i); }
uint32_t write_byte(tv_buffer *b, int32_t i, int32_t v) { return tv_buffer_write(b,i,v); }
uint32_t push(tv_buffer *b, int32_t v) { return tv_buffer_push(b,v); }
tv_buffer_pop_result pop(tv_buffer *b) { return tv_buffer_pop(b); }
int32_t close_buffer(tv_buffer b) { return tv_buffer_close(b); }
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def fingerprint(path):
    data = Path(path).read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def check_bytes(path, expected):
    require(Path(path).read_bytes() == expected, 'Observed gate input change: ' + str(path))


def check_artifacts(artifacts):
    for path, expected in artifacts.items():
        require(fingerprint(path) == expected, 'Observed compiled artifact change: ' + str(path))


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(RuntimeError('Nonfinite JSON value: ' + value)))


def layout(output, capacity):
    result = strict_json(output)
    keys = {'capacity', 'descriptor_bytes', 'block_bytes', 'buffer_bytes', 'allocation_bytes', 'pop_result_bytes'}
    require(type(result) is dict and set(result) == keys, 'Unexpected byte-buffer layout shape')
    require(all(type(result[key]) is int and result[key] > 0 for key in keys), 'Invalid measured C layout')
    require(result['capacity'] == capacity, 'Incorrect layout capacity')
    return result


def undefined_symbols(output, system):
    symbols = []
    # GNU nm emits U symbol; Darwin nm -u also permits a bare underscored symbol.
    linux_names = {name: name for name in PERMITTED}
    linux_names.update({'__stack_chk_fail': 'stack_chk_fail', '__stack_chk_guard': 'stack_chk_guard',
                        '_GLOBAL_OFFSET_TABLE_': 'GLOBAL_OFFSET_TABLE_'})
    darwin_names = {'_' + name: name for name in PERMITTED}
    darwin_names.update({'___stack_chk_fail': 'stack_chk_fail', '___stack_chk_guard': 'stack_chk_guard',
                         '___chkstk_darwin': 'chkstk_darwin'})
    allowed = darwin_names if system == 'Darwin' else linux_names
    for line in output.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*U\s+(\S+)\s*', line)
        if match:
            raw = match.group(1)
        elif system == 'Darwin' and re.fullmatch(r'\s*_[A-Za-z_0-9]+\s*', line):
            raw = line.strip()
        else:
            raise RuntimeError('Unrecognized nm undefined-symbol row: ' + line)
        require(raw in allowed, 'Unapproved production dependency: ' + raw)
        symbols.append(allowed[raw])
    return sorted(set(symbols))


def accept_trap(result, probe):
    require(result['returncode'] == -signal.SIGABRT, 'Contract probe did not SIGABRT: ' + probe)
    require(not result['stdout'], 'Contract probe emitted unexpected stdout: ' + probe)
    require(not any(marker in result['stderr'] for marker in ('oracle:', 'AddressSanitizer', 'UndefinedBehaviorSanitizer', 'runtime error:')),
            'Contract probe had oracle/sanitizer failure: ' + probe)


def arch(value):
    return {'arm64': 'aarch64', 'amd64': 'x86_64'}.get(value.lower(), value.lower())


def verify():
    system = platform.system()
    native_arch = arch(platform.machine())
    require(system in ('Linux', 'Darwin') and native_arch in ('x86_64', 'aarch64'),
            'Unsupported actual host; this gate never skips acceptance')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    captured = {name: (ROOT / name).read_bytes() for name in SOURCES}
    report = {'schema': 'talven.byte-buffer-runtime-check.v1', 'profile': 'c11-supplied-byte-buffer-v1',
              'validation': 'C-runtime-only; no Talven lifetime checking', 'ok': False,
              'complete': False, 'passed': False, 'commands': [], 'executions': [], 'abort_probes': [],
              'inputs': [{'path': name, 'text': data.decode('utf-8'), 'sha256': hashlib.sha256(data).hexdigest()}
                         for name, data in captured.items()], 'tools': {}, 'artifacts': []}
    tools = {}
    for name in ('cc', 'nm', 'uname'):
        value = shutil.which(name)
        require(value is not None, 'Required tool missing: ' + name)
        tools[name] = Path(value).resolve()
    tools['python'] = Path(sys.executable).resolve()
    if system == 'Darwin':
        tools['sysctl'] = Path('/usr/sbin/sysctl').resolve()
    initial = {name: fingerprint(path) for name, path in tools.items()}
    artifacts = {}
    stable = {ROOT / name: data for name, data in captured.items()}

    def run(command, timeout=30, success=True):
        for path, data in stable.items():
            check_bytes(path, data)
        check_artifacts(artifacts)
        used_tool = next((name for name, path in tools.items() if str(path) == str(command[0])), None)
        if used_tool is not None:
            require(fingerprint(tools[used_tool]) == initial[used_tool], 'Tool executable changed before use: ' + used_tool)
        result = subprocess.run([str(part) for part in command], capture_output=True, text=True, timeout=timeout)
        if used_tool is not None:
            require(fingerprint(tools[used_tool]) == initial[used_tool], 'Tool executable changed after use: ' + used_tool)
        record = {'command': [str(part) for part in command], 'stdout': result.stdout,
                  'stderr': result.stderr, 'returncode': result.returncode,
                  'tool': None if used_tool is None else {'name': used_tool, **initial[used_tool]}}
        report['commands'].append(record)
        for path, data in stable.items():
            check_bytes(path, data)
        check_artifacts(artifacts)
        if success:
            require(result.returncode == 0, 'Trusted command failed: ' + result.stderr + result.stdout)
        return record

    dispatch = {}
    sdk = None
    platform_flags = []
    if system == 'Darwin':
        for name in ('cc', 'nm'):
            if tools[name] == Path('/usr/bin') / name:
                resolver = Path('/usr/bin/xcrun')
                require(resolver.is_file(), 'Darwin effective-tool resolver missing')
                if 'xcrun' not in tools:
                    tools['xcrun'] = resolver
                    initial['xcrun'] = fingerprint(resolver)
                value = run([resolver, '--find', name])['stdout'].strip()
                effective = Path(value)
                require('\n' not in value and effective.is_absolute() and effective.is_file() and os.access(effective, os.X_OK),
                        'Invalid Darwin effective tool')
                effective = effective.resolve()
                dispatch[name] = {'invocation': str(tools[name]), 'effective': str(effective)}
                tools[name + '_dispatch_wrapper'] = tools[name]
                initial[name + '_dispatch_wrapper'] = initial[name]
                tools[name] = effective
                initial[name] = fingerprint(effective)
        if 'cc' in dispatch:
            path = run([tools['xcrun'], '--sdk', 'macosx', '--show-sdk-path'])['stdout'].strip()
            version = run([tools['xcrun'], '--sdk', 'macosx', '--show-sdk-version'])['stdout'].strip()
            require('\n' not in path and Path(path).is_dir() and version and '\n' not in version, 'Invalid Darwin SDK selection')
            settings_path = Path(path) / 'SDKSettings.json'
            settings = settings_path.read_bytes() if settings_path.is_file() else None
            sdk = {'path': path, 'version': version, 'settings': None if settings is None else {
                'path': str(settings_path), 'text': settings.decode('utf-8'), 'sha256': hashlib.sha256(settings).hexdigest()},
                'closure_note': 'Full SDK/header/linker closure is not archived or verified'}
            if settings is not None:
                stable[settings_path] = settings
            platform_flags = ['-isysroot', path]
    for name, path in tools.items():
        report['tools'][name] = {'path': str(path), 'initial': initial[name]}
    for name in ('cc', 'nm', 'python'):
        report['tools'][name]['version'] = run([tools[name], '--version'])['stdout']
        require(report['tools'][name]['version'].strip(), 'Empty tool version')
    target = run([tools['cc'], '-dumpmachine'])['stdout'].strip()
    require(target and '\n' not in target and arch(target.split('-')[0]) == native_arch, 'C target differs from native host architecture')
    require(('darwin' in target.lower()) if system == 'Darwin' else ('linux' in target.lower()), 'C target differs from native host system')
    uname = run([tools['uname'], '-m'])['stdout'].strip()
    require(arch(uname) == native_arch, 'Actual uname host differs from declared host')
    if system == 'Darwin':
        underlying_arm = run([tools['sysctl'], '-n', 'hw.optional.arm64'])['stdout'].strip()
        require(underlying_arm in ('0', '1'), 'Unknown Darwin native CPU evidence')
        require(underlying_arm != '1' or native_arch == 'aarch64', 'Emulated Darwin process is not native host evidence')
    report['environment'] = {'system': system, 'release': platform.release(), 'machine': platform.machine(),
                             'native_arch': native_arch, 'uname_machine': uname, 'logical_cpus': os.cpu_count(),
                             'c_target': target, 'platform_flags': platform_flags,
                             'darwin_dispatch': dispatch, 'sdk': sdk}
    with tempfile.TemporaryDirectory(prefix='talven-byte-buffer-') as temporary:
        directory = Path(temporary)
        for name, data in captured.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            stable[path] = data
        driver = directory / SOURCES[2]
        # Compile-time target evidence independently checks the selected tool's macros.
        target_check = directory / 'target.c'
        macro = '__aarch64__' if native_arch == 'aarch64' else '__x86_64__'
        target_check.write_text('#ifndef ' + macro + '\n#error "C target is not actual host"\n#endif\nint target_check(void) { return 0; }\n')
        stable[target_check] = target_check.read_bytes()
        target_obj = directory / 'target.o'
        run([tools['cc'], *FLAGS, *platform_flags, '-c', target_check, '-o', target_obj])
        artifacts[target_obj] = fingerprint(target_obj)
        for capacity in (1, 32, 4096):
            for optimization in ('-O0', '-O2'):
                for fault in (False, True):
                    flags = [*FLAGS, *platform_flags, optimization, *SANITIZERS, f'-DCAPACITY={capacity}']
                    if fault:
                        flags.append('-DTV_REGION_TEST_FAULT')
                    executable = directory / f'check-{capacity}-{optimization[1:]}-{int(fault)}'
                    run([tools['cc'], *flags, driver, '-o', executable])
                    artifacts[executable] = fingerprint(executable)
                    positive = run([executable])
                    require(not positive['stderr'], 'Independent ledger emitted diagnostics')
                    measured = layout(positive['stdout'], capacity)
                    probes = []
                    for probe in PROBES:
                        result = run([executable, probe], timeout=5, success=False)
                        accept_trap(result, probe)
                        report['abort_probes'].append({'probe': probe, 'flags': flags, 'result': result})
                        probes.append(probe)
                    report['executions'].append({'flags': flags, 'fault_injection': fault, 'layout': measured,
                                                 'ledger_passed': True, 'abort_probes': probes})
                    if capacity == 1 and optimization == '-O0' and not fault:
                        unknown = run([executable, 'unknown-probe'], success=False)
                        require(unknown['returncode'] == 42 and not unknown['stdout'] and not unknown['stderr'], 'Unknown probe classification failed')
                        report['unknown_probe'] = unknown
        wrapper = directory / 'production.c'
        wrapper.write_text(WRAPPER)
        stable[wrapper] = WRAPPER.encode('utf-8')
        obj = directory / 'production.o'
        production_flags = [*FLAGS, *platform_flags, '-O2']
        run([tools['cc'], *production_flags, '-c', wrapper, '-o', obj])
        artifacts[obj] = fingerprint(obj)
        symbols = undefined_symbols(run([tools['nm'], '-u', obj])['stdout'], system)
        report['production'] = {'flags': production_flags, 'wrapper': WRAPPER,
                                'wrapper_sha256': hashlib.sha256(WRAPPER.encode()).hexdigest(),
                                'undefined_symbols': symbols, 'permitted_symbols': sorted(PERMITTED),
                                'dependency_scope': 'this object; excludes hosted startup/libc internals'}
        for name, entry in dispatch.items():
            require(str(Path(run([tools['xcrun'], '--find', name])['stdout'].strip()).resolve()) == entry['effective'], 'Effective tool selection changed')
        if sdk is not None:
            require(run([tools['xcrun'], '--sdk', 'macosx', '--show-sdk-path'])['stdout'].strip() == sdk['path'], 'SDK path changed')
            require(run([tools['xcrun'], '--sdk', 'macosx', '--show-sdk-version'])['stdout'].strip() == sdk['version'], 'SDK version changed')
            require(sdk['settings'] is not None or not (Path(sdk['path']) / 'SDKSettings.json').is_file(), 'SDK settings appeared during run')
        for name, path in tools.items():
            final = fingerprint(path)
            require(final == initial[name], 'Tool executable changed: ' + name)
            report['tools'][name]['final'] = final
        for name in ('cc', 'nm', 'python'):
            final_version = run([tools[name], '--version'])['stdout']
            require(final_version == report['tools'][name]['version'], 'Tool version changed: ' + name)
        require(run([tools['cc'], '-dumpmachine'])['stdout'].strip() == target, 'C target changed')
        for path, data in stable.items():
            check_bytes(path, data)
        check_artifacts(artifacts)
        for name, path in tools.items():
            final = fingerprint(path)
            require(final == initial[name], 'Tool executable changed at completion: ' + name)
            report['tools'][name]['final'] = final
        report['artifacts'] = [{'path': str(path.relative_to(directory)), 'initial': identity, 'final': fingerprint(path)}
                               for path, identity in artifacts.items()]
    report.update(ok=True, complete=True, passed=True, positive_executions=len(report['executions']),
                  negative_trap_executions=len(report['abort_probes']))
    report['limits'] = ['C-only experiment; no source move/loan/close enforcement',
                        'Layout excludes backing capacity, padding outside descriptors, live copies and test ledger',
                        'No timing, total RAM, whole-stack, p99, agent-cost or broader container/concurrency claim',
                        'Exact inputs and compiled artifact identities recorded; temporary artifacts are not retained',
                        'Trusted tools and host required; executable hashes do not capture transitive toolchain dependencies']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='Create a new JSON receipt; default stdout')
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
