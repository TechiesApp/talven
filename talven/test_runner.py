"""Bounded trusted hosted tests; no new source syntax or public C ABI."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import tempfile
import time

from . import PROFILE
from .backend import emit_c
from .c_command import BoundedCommand
from .context import compiler_hash, encode, source_hash
from .frontend import CompileError, MAX_SOURCE_BYTES, Span, analyze
from .preprocessed_units import executable_hash
from .source_edit import read_regular
from .unit_build import OBJECT_FLAGS, artifact_bytes

MAX_CASES = 128
MAX_OUTPUT = 64 * 1024
MAX_REPORT = 2 * 1024 * 1024
MARKER = b'\0talven.test.i32:'
DRIVER = ('#include <stdint.h>\n#include <inttypes.h>\n#include <stdio.h>\n'
          'extern int32_t tv_f_main(void);\n'
          'int main(void) {\n'
          '    int32_t result = tv_f_main();\n'
          '    static const unsigned char marker[] = {' + ','.join(map(str, MARKER)) + '};\n'
          '    if (fwrite(marker, 1, sizeof marker, stdout) != sizeof marker) return 2;\n'
          '    if (fprintf(stdout, "%" PRId32 "\\n", result) < 0) return 2;\n'
          '    return fflush(stdout) == 0 ? 0 : 2;\n}\n').encode()


def manifest_error(message):
    return CompileError('E0801', message, Span(0, 0))


def read_text(path):
    data, _ = read_regular(path)
    if len(data) > MAX_SOURCE_BYTES:
        raise CompileError('E0005', 'Test input exceeds the 256 KiB limit', Span(0, 0))
    return data.decode('utf-8')


@dataclass(frozen=True)
class Case:
    id: str
    source: str
    console: bool
    result: int
    stdout: bytes
    stderr: bytes
    diagnostic: str | None


def load_manifest(source):
    def utf8(value):
        try:
            return value.encode('utf-8')
        except UnicodeError:
            raise manifest_error('Test paths and expected outputs must contain valid UTF-8 text') from None

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise manifest_error('Duplicate test manifest key')
            result[key] = value
        return result

    def constant(_):
        raise manifest_error('Test manifest requires standard JSON values')

    try:
        data = json.loads(source, object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, RecursionError):
        raise manifest_error('Invalid test manifest JSON') from None
    if (not isinstance(data, dict) or set(data) != {'schema', 'cases'}
            or data['schema'] != 'talven.test-manifest.v1'):
        raise manifest_error('Expected talven.test-manifest.v1 with schema and cases only')
    if not isinstance(data['cases'], list) or not 1 <= len(data['cases']) <= MAX_CASES:
        raise manifest_error('Test manifest requires 1..128 cases')
    cases, names = [], set()
    allowed = {'id', 'source', 'console', 'result', 'stdout', 'stderr', 'diagnostic'}
    for item in data['cases']:
        if not isinstance(item, dict) or set(item) - allowed or not {'id', 'source'} <= set(item):
            raise manifest_error('Test cases require id/source and only documented fields')
        name, path = item['id'], item['source']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name) or name in names:
            raise manifest_error('Test IDs must be unique 1..64-character ASCII names')
        if (not isinstance(path, str) or not path or '\0' in path or len(utf8(path)) > 1024
                or Path(path).is_absolute() or '..' in Path(path).parts or Path(path).suffix != '.tal'):
            raise manifest_error('Test sources must be bounded relative .tal paths without parent traversal')
        console, expected = item.get('console', False), item.get('result', 0)
        if type(console) is not bool or type(expected) is not int or not -(2**31) <= expected < 2**31:
            raise manifest_error('Console must be boolean and result a signed i32 integer')
        outputs = []
        for label in ('stdout', 'stderr'):
            value = item.get(label, '')
            if not isinstance(value, str):
                raise manifest_error('Expected outputs must be UTF-8 strings')
            value = utf8(value)
            if len(value) > MAX_OUTPUT:
                raise manifest_error('Expected output exceeds 64 KiB')
            outputs.append(value)
        diagnostic = item.get('diagnostic')
        if diagnostic is not None and (not isinstance(diagnostic, str) or not re.fullmatch(r'E[0-9]{4}', diagnostic)
                                       or set(item) & {'result', 'stdout', 'stderr'}):
            raise manifest_error('Diagnostic expectations require one error code and no runtime expectations')
        if 'diagnostic' in item and diagnostic is None:
            raise manifest_error('Diagnostic expectation cannot be null')
        cases.append(Case(name, path, console, expected, *outputs, diagnostic))
        names.add(name)
    return cases


def stream_receipt(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'preview': data[:1024].decode('utf-8', errors='replace'), 'truncated': len(data) > 1024}


def diagnostic_receipt(error, source):
    result = error.diagnostic(source)
    result['message_truncated'] = len(result['message']) > 1024
    result['message'] = result['message'][:1024]
    return result


def decode_result(output):
    stdout, marker, value = output.rpartition(MARKER)
    if not marker or not re.fullmatch(rb'(?:0|-?[1-9][0-9]{0,9})\n', value) or len(stdout) > MAX_OUTPUT:
        raise CompileError('E0802', 'Native test result protocol is missing or malformed', Span(0, 0))
    result = int(value)
    if not -(2**31) <= result < 2**31:
        raise CompileError('E0802', 'Native test result is outside i32', Span(0, 0))
    return result, stdout


def run_tests(manifest, *, cc='cc', timeout=30):
    if type(timeout) not in (int, float) or not 0.01 <= timeout <= 60:
        raise ValueError('Native test timeout must be finite and within 0.01..60 seconds')
    pinned = compiler_hash()
    report = {'schema': 'talven.test-report.v1', 'profile': 'hosted-i32-tests-v1', 'language_profile': PROFILE,
              'compiler_hash': pinned, 'manifest_hash': None, 'complete': False, 'ok': False,
              'cases': [], 'summary': {'passed': 0, 'failed': 0}, 'driver': None,
              'flags': list(OBJECT_FLAGS), 'timeout_seconds': timeout, 'diagnostic': None}
    report['host'] = {'system': platform.system(), 'machine': platform.machine(), 'python': platform.python_version()}
    report['harness_hash'] = hashlib.sha256(DRIVER).hexdigest()
    manifest_source = ''
    environment = {**os.environ, 'LC_ALL': 'C'}
    report['environment_hash'] = source_hash(json.dumps(environment, sort_keys=True))
    try:
        manifest = Path(manifest)
        manifest_source = read_text(manifest)
        report['manifest_hash'] = source_hash(manifest_source)
        cases = load_manifest(manifest_source)
        root = manifest.parent.resolve()
        driver = None
        for case in cases:
            started = time.monotonic()
            row = {'id': case.id, 'source': case.source, 'source_hash': None, 'console': case.console,
                   'ok': False, 'phase': 'input', 'diagnostic': None, 'expected_diagnostic': case.diagnostic,
                   'expected_result': case.result if case.diagnostic is None else None, 'runtime': None}
            row['expected_output'] = None if case.diagnostic else {
                'stdout': stream_receipt(case.stdout), 'stderr': stream_receipt(case.stderr)}
            report['cases'].append(row)
            source = ''
            try:
                path = (root / case.source).resolve()
                if not path.is_relative_to(root):
                    raise manifest_error('Test source resolves outside the manifest directory')
                source = read_text(path)
                row['source_hash'] = source_hash(source)
                row['phase'] = 'frontend'
                try:
                    generated = emit_c(analyze(source), console=case.console)
                except CompileError as error:
                    row['diagnostic'] = diagnostic_receipt(error, source)
                    row['ok'] = case.diagnostic == error.code
                    continue
                if case.diagnostic is not None:
                    row['diagnostic'] = diagnostic_receipt(manifest_error('Expected compiler diagnostic was not produced'), source)
                    continue
                row['c_hash'] = source_hash(generated)
                with tempfile.TemporaryDirectory(prefix='talven-test-') as directory:
                    work = Path(directory)
                    row['working_directory_hash'] = source_hash(str(work))

                    def command(argv, data=b'', stdout_limit=MAX_OUTPUT):
                        remaining = timeout - (time.monotonic() - started)
                        if remaining <= 0:
                            raise CompileError('E0402', 'Native test command budget exhausted', Span(0, 0))
                        with BoundedCommand(argv, data, environment, remaining, stdout_limit, cwd=work) as operation:
                            try:
                                while True:
                                    result = operation.poll(wait=0.01)
                                    if result is not None:
                                        return result, bytes(operation.output['stderr'])
                            except CompileError:
                                row['failed_command'] = {'returncode': operation.process.returncode,
                                    'stdout': stream_receipt(bytes(operation.output['stdout'])),
                                    'stderr': stream_receipt(bytes(operation.output['stderr']))}
                                raise

                    row['phase'] = 'toolchain'
                    resolved = shutil.which(cc)
                    if resolved is None:
                        raise CompileError('E0901', 'Native test compiler is unavailable', Span(0, 0))
                    executable = Path(resolved).resolve()
                    identity = executable_hash(executable)
                    if driver is None:
                        version, _ = command([str(executable), '--version'])
                        target, _ = command([str(executable), '-dumpmachine'])
                        if not version.strip() or not target.strip():
                            raise CompileError('E0901', 'Native test compiler metadata is empty', Span(0, 0))
                        driver = (str(executable), identity)
                        report['driver'] = {'executable_hash': identity, 'version': stream_receipt(version),
                                            'target': stream_receipt(target)}
                    elif driver != (str(executable), identity):
                        raise CompileError('E0501', 'Native test compiler changed during the suite', Span(0, 0))
                    row['phase'] = 'compile'
                    subject, harness, program = work/'subject.o', work/'driver.o', work/'program'
                    command([str(executable), *OBJECT_FLAGS, '-Dmain=tv_test_entry', '-x', 'c', '-c', '-', '-o', str(subject)],
                            generated.encode('utf-8'))
                    row['subject_hash'] = hashlib.sha256(artifact_bytes(subject)).hexdigest()
                    command([str(executable), *OBJECT_FLAGS, '-x', 'c', '-c', '-', '-o', str(harness)], DRIVER)
                    row['driver_object_hash'] = hashlib.sha256(artifact_bytes(harness)).hexdigest()
                    row['phase'] = 'link'
                    command([str(executable), *OBJECT_FLAGS, str(subject), str(harness), '-o', str(program)])
                    row['executable_hash'] = hashlib.sha256(artifact_bytes(program)).hexdigest()
                    if (row['subject_hash'] != hashlib.sha256(artifact_bytes(subject)).hexdigest()
                            or row['driver_object_hash'] != hashlib.sha256(artifact_bytes(harness)).hexdigest()
                            or identity != executable_hash(executable) or pinned != compiler_hash()):
                        raise CompileError('E0501', 'Native test inputs changed before execution', Span(0, 0))
                    row['phase'] = 'run'
                    output, stderr = command([str(program)], stdout_limit=MAX_OUTPUT + 64)
                    actual, stdout = decode_result(output)
                    row['runtime'] = {'result': actual, 'stdout': stream_receipt(stdout), 'stderr': stream_receipt(stderr),
                                      'result_matches': actual == case.result, 'stdout_matches': stdout == case.stdout,
                                      'stderr_matches': stderr == case.stderr}
                    if (row['executable_hash'] != hashlib.sha256(artifact_bytes(program)).hexdigest()
                            or identity != executable_hash(executable) or pinned != compiler_hash()):
                        raise CompileError('E0501', 'Native test inputs changed during execution', Span(0, 0))
                    row['ok'] = all(row['runtime'][key] for key in ('result_matches', 'stdout_matches', 'stderr_matches'))
                    row['phase'] = 'complete'
            except CompileError as error:
                row['diagnostic'] = diagnostic_receipt(error, source)
            except (OSError, UnicodeError, ValueError, RuntimeError) as error:
                row['diagnostic'] = diagnostic_receipt(CompileError('E0901', str(error), Span(0, 0)), source)
            finally:
                row['elapsed_seconds'] = time.monotonic() - started
                report['summary']['passed' if row['ok'] else 'failed'] += 1
        if compiler_hash() != pinned:
            raise CompileError('E0501', 'Compiler inputs changed during native tests; repeat with stable inputs', Span(0, 0))
        report['complete'] = True
        report['ok'] = report['summary']['failed'] == 0
    except CompileError as error:
        report['diagnostic'] = diagnostic_receipt(error, manifest_source)
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        report['diagnostic'] = diagnostic_receipt(CompileError('E0901', str(error), Span(0, 0)), manifest_source)
    if len(encode(report).encode('utf-8')) > MAX_REPORT:
        return {**report, 'cases': [], 'complete': False, 'ok': False,
                'diagnostic': diagnostic_receipt(CompileError('E0005', 'Test report exceeds 2 MiB', Span(0, 0)), '')}
    return report
