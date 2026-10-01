#!/usr/bin/env python3
"""Measure real watch/restart edits with retained inputs and native task checks."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('watch_edits', ROOT / 'scripts/measure-incremental.py')
edits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edits)
base = edits.base
from talven import PROFILE, VERSION
from talven.backend import emit_c
from talven.context import compiler_hash, source_hash
from talven.frontend import analyze
from talven.unit_build import OBJECT_FLAGS

MODES = ('full', 'units')
MARKER = b'accepted\n'
MAX_LOG_BYTES = 16 * 1024 * 1024


def workloads():
    """Place independent full-value/owner checks in the program actually watched."""
    result = edits.workloads()
    for workload in result:
        for revision in workload['revisions']:
            changed = revision['id'] not in ('initial', 'trivia')
            declarations = revision['source'].split('fn main()', 1)[0]
            checks = []
            if workload['id'] == 'borrowing':
                schema = revision['id'] in ('schema', 'invalid', 'repair')
                for index, value in enumerate((-1000, 0, 1000000)):
                    name = f'p_{index}'
                    checks.append(f'let mut {name} = P {{ x: {value}' + (', y: true' if schema else '') + ' };')
                    checks.append(f'if (read(&{name}) != {value}) {{ return 1; }}')
                    checks.append(f'if (bump(&mut {name}) != {value + (2 if changed else 1)}) {{ return 1; }}')
                    checks.append(f'if ({name}.x != {value + (2 if changed else 1)}) {{ return 1; }}')
                    if schema:
                        checks.append(f'if (!{name}.y) {{ return 1; }}')
            else:
                count = int(workload['id'].rsplit('-', 1)[1])
                for value in (-1000, 0, 1000000):
                    checks.append(f'if (step_{count - 1}({value}) != {value + count + int(changed)}) {{ return 1; }}')
            source = declarations + 'fn main() -> i32 {\n    ' + '\n    '.join(checks) + '\n    return print("accepted\\n");\n}\n'
            if revision['expected_error'] and workload['id'] == 'borrowing':
                source = source.replace('bump(&mut p_0)', 'bump(&p_0)', 1)
            revision['source'] = source
        workload['criteria'] = ('Watched main independently checks three full-i32 results; borrowing also checks owner updates '
                                'and preservation of added fields; exact accepted newline output and exit zero. '
                                'Separate ordinary-C oracle verifies helper results before measurement. Invalid edits are current E0201.')
    return result


def input_files():
    return sorted([*ROOT.joinpath('talven').glob('*.py'), Path(__file__).resolve(),
                   ROOT / 'scripts/measure-incremental.py', ROOT / 'scripts/measure-tooling.py',
                   ROOT / 'experiments/tooling_workloads.py', ROOT / 'experiments/__init__.py',
                   *ROOT.joinpath('examples').glob('*.tal')])


def read_events(path):
    if not path.exists():
        return []
    base.require(path.stat().st_size <= MAX_LOG_BYTES, 'watch event log exceeded measurement limit')
    rows = [json.loads(line) for line in path.read_text().splitlines(keepends=True) if line.endswith('\n')]
    base.require(all(isinstance(row, dict) for row in rows), 'watch event is not an object')
    return rows


def wait_event(process, path, name, revision, deadline):
    while time.monotonic() < deadline:
        rows = read_events(path)
        for row in rows:
            if row.get('event') == name and row.get('revision') == revision:
                return row, time.perf_counter_ns()
        base.require(process.poll() is None, 'watcher exited before expected receipt')
        if name != 'rejected':
            base.require(not any(row.get('revision') == revision and row.get('event') in ('rejected', 'superseded')
                                 for row in rows), 'watcher rejected/superseded expected current program')
        time.sleep(0.001)
    raise base.MeasurementError(f'timed out waiting for {name} revision {revision}')


def verify_events(rows, sample, expected, identities, pinned, output, accepted):
    current = [row for row in rows if row.get('revision') == sample['revision_number']]
    base.require(current and all(row.get('schema') == 'talven.dev.v1' and row.get('source_hash') == sample['source_hash']
                                 for row in current), 'watch events describe a different source revision')
    names = [row['event'] for row in current]
    base.require('observed' in names and 'superseded' not in names, 'missing current observation or stale publication')
    sessions = [row for row in rows if row.get('event') == 'session_started']
    base.require(len(sessions) == 1 and sessions[0].get('compiler_hash') == pinned
                 and sessions[0].get('build_mode') == sample['mode'] and sessions[0].get('frontend_mode') == 'full'
                 and sessions[0].get('stable_toolchain_required') == (sample['mode'] == 'units'), 'watch configuration mismatch')
    if expected:
        rejected = [row for row in current if row['event'] == 'rejected']
        base.require(len(rejected) == 1 and rejected[0].get('diagnostic') == expected
                     and not any(name in names for name in ('building', 'compiled', 'started', 'exited')),
                     'invalid edit was not the expected current frontend rejection')
    else:
        base.require(names.count('started') == names.count('exited') == 1 and 'rejected' not in names,
                     'current program did not start and exit exactly once')
        exited = next(row for row in current if row['event'] == 'exited')
        base.require(exited.get('returncode') == 0, 'actual watched program failed native task checks')
        if sample['mode'] == 'units':
            compiled = [row for row in current if row['event'] == 'compiled']
            base.require(len(compiled) == 1, 'missing native candidate receipt')
            receipt = compiled[0]
            base.require(all(isinstance(receipt.get(key), list) and all(isinstance(value, str) for value in receipt[key])
                             for key in ('compiled', 'reused')), 'invalid candidate work lists')
            work = receipt.get('compiled', []) + receipt.get('reused', [])
            base.require(len(work) == len(identities) and len(set(work)) == len(work) and set(work) == set(identities),
                         'native candidate work does not partition current units')
            base.require(type(receipt.get('driver_probe_reused')) is bool
                         and type(receipt.get('object_bytes')) is int and receipt['object_bytes'] > 0
                         and isinstance(receipt.get('executable_hash'), str) and len(receipt['executable_hash']) == 64
                         and all(char in '0123456789abcdef' for char in receipt['executable_hash']),
                         'missing candidate work identities')
            if sample['revision'] in ('trivia', 'repair'):
                base.require(receipt['compiled'] == [] and receipt['driver_probe_reused'], 'unchanged current units were not reused')
    base.require(output == MARKER * accepted, 'actual watched output differs from accepted current revisions')


def summarize(samples, selected, repetitions):
    result = []
    for workload in selected:
        for revision in workload['revisions']:
            for mode in MODES:
                group = [s for s in samples if s['phase'] == 'measured' and s['workload'] == workload['id']
                         and s['revision'] == revision['id'] and s['mode'] == mode]
                base.require(len(group) == repetitions and all(s.get('verified') for s in group), 'incomplete verified watcher samples')
                values = [s['parent_to_receipt_ns'] for s in group]
                base.require(all(type(value) is int and value >= 0 for value in values), 'invalid watcher durations')
                result.append({'workload': workload['id'], 'revision': revision['id'], 'mode': mode, 'samples': len(group),
                               'min_ns': min(values), 'median_ns': statistics.median(values), 'max_ns': max(values),
                               'terminal': 'rejected' if revision['expected_error'] else 'started'})
    return result


def measure_session(recorder, args, workload, expected, mode, phase, repetition, position, pinned, cc):
    directory = recorder.out / 'sessions' / phase / str(repetition) / workload['id'] / mode
    directory.mkdir(parents=True)
    source, events = directory / 'source.tal', directory / 'events.jsonl'
    argv = [sys.executable, '-m', 'talven', 'dev', str(source), '--console', '--cc', cc, '--events', str(events),
            '--poll-interval', str(args.poll_interval), '--debounce', str(args.debounce), '--build-timeout', str(args.timeout)]
    if mode == 'units':
        argv.extend(['--incremental-build', '--stable-toolchain'])
    session = {'workload': workload['id'], 'mode': mode, 'phase': phase, 'repetition': repetition, 'argv': argv,
               'path': str(directory.relative_to(recorder.out)), 'returncode': None, 'clean_shutdown': False}
    recorder.report['sessions'].append(session)
    process, accepted = None, 0
    with (directory / 'stdout').open('w+b') as stdout, (directory / 'stderr').open('w+b') as stderr:
        try:
            for number, revision in enumerate(workload['revisions'], 1):
                staged = directory / 'save.pending'
                staged.write_text(revision['source'], encoding='utf-8')
                sample = {'phase': phase, 'repetition': repetition, 'order': position, 'workload': workload['id'],
                          'revision': revision['id'], 'revision_number': number, 'mode': mode,
                          'source_hash': source_hash(revision['source']), 'verified': False}
                recorder.report['samples'].append(sample)
                recorder.save()
                if number == 1:
                    staged.replace(source)
                started = time.perf_counter_ns()
                try:
                    if process is None:
                        process = subprocess.Popen(argv, cwd=ROOT, env={**os.environ, **base.ENVIRONMENT},
                                                   stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
                    else:
                        staged.replace(source)
                    deadline = time.monotonic() + args.timeout + 5
                    terminal = 'rejected' if revision['expected_error'] else 'started'
                    row, received = wait_event(process, events, terminal, number, deadline)
                    sample.update(parent_to_receipt_ns=received - started, terminal_receipt=row)
                finally:
                    if 'parent_to_receipt_ns' not in sample:
                        sample['attempt_to_failure_ns'] = time.perf_counter_ns() - started
                    recorder.save()
                if not revision['expected_error']:
                    sample['exit_receipt'], _ = wait_event(process, events, 'exited', number, deadline)
                    accepted += 1
                stdout.seek(0)
                output = stdout.read(len(MARKER) * accepted + 1)
                base.require(stderr.seek(0, 2) <= MAX_LOG_BYTES, 'watch stderr exceeded measurement limit')
                rows = read_events(events)
                diagnostic, identifiers = expected[revision['id']]
                verify_events(rows, sample, diagnostic, identifiers, pinned, output, accepted)
                sample['verified'] = True
                recorder.save()
        finally:
            if process is not None:
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                session['returncode'] = process.returncode
                session['clean_shutdown'] = process.returncode == 128 + signal.SIGTERM and any(
                    row.get('event') == 'session_stopped' for row in read_events(events))
            for name in ('stdout', 'stderr', 'events.jsonl'):
                path = directory / name
                session[name] = base.fingerprint(path) if path.exists() else None
            recorder.save()
    base.require(session['clean_shutdown'], 'watcher did not cleanly terminate its owned session')


def run(args):
    out, cc, arch = base.preflight(args.out, args.repetitions, args.warmups, args.timeout, args.cc, args.expect_arch)
    base.require(args.stable_toolchain is True, 'assert --stable-toolchain for this trusted local experiment')
    base.require(0.01 <= args.timeout <= 60, 'native watch timeout must be 0.01..60 seconds')
    base.require(all(math.isfinite(value) and 0.01 <= value <= 1 for value in (args.poll_interval, args.debounce)),
                 'measurement polling/debounce must be 0.01..1 second')
    out.mkdir(parents=True)
    (out / 'commands').mkdir()
    selected = workloads()
    report = {'schema': 'talven.native-watch-baseline.v1', 'complete': False, 'passed': False, 'summary': None,
              'samples': [], 'sessions': [], 'commands': [], 'inputs': {}, 'workloads': [],
              'started_at': datetime.now(timezone.utc).isoformat(), 'compiler_hash': compiler_hash(),
              'language_profile': PROFILE, 'compiler_version': VERSION, 'repetitions': args.repetitions, 'warmups': args.warmups,
              'machine': arch, 'system': platform.system(), 'os_release': platform.release(), 'python': platform.python_version(),
              'python_executable': base.fingerprint(Path(sys.executable)), 'c_executable': base.fingerprint(Path(cc)),
              'poll_interval_seconds': args.poll_interval, 'debounce_seconds': args.debounce, 'timeout_seconds': args.timeout,
              'stable_toolchain_required': True, 'environment_note': args.environment_note,
              'child_environment_overrides': base.ENVIRONMENT,
              'flags': {'full': list(base.FLAGS), 'units': list(OBJECT_FLAGS), 'preflight': [*base.FLAGS, '-fno-lto']},
              'child_environment_hash': source_hash(json.dumps({**os.environ, **base.ENVIRONMENT}, sort_keys=True)),
              'clock': {'implementation': time.get_clock_info('perf_counter').implementation,
                        'resolution_seconds': time.get_clock_info('perf_counter').resolution},
              'timed_boundary': 'Initial: parent before watcher Popen to receipt read. Edits: parent before atomic source replace to receipt read. Valid terminal is process started, invalid terminal is rejected. Includes receipt-reader polling/JSON overhead; event is not readiness. Source staging/report writes before timing; exit/output and task verification afterward.',
              'unmeasured': ['application readiness', 'cold OS caches', 'memory', 'concurrent edits/cancellation latency',
                             'live long-running application shutdown', 'state preservation', 'model/token/dollar benefit']}
    recorder = base.Recorder(out, report, args.timeout)
    recorder.save()
    try:
        for path in input_files():
            relative = path.relative_to(ROOT)
            archived = out / 'inputs' / relative
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_bytes(path.read_bytes())
            report['inputs'][str(relative)] = base.fingerprint(archived)
        for key, command in {'git_revision': ['git', 'rev-parse', 'HEAD'], 'git_status': ['git', 'status', '--porcelain'],
                             'c_version': [cc, '--version'], 'c_target': [cc, '-dumpmachine']}.items():
            output, _ = recorder.command(command, phase='provenance')
            report[key] = output.decode().strip()
        report['cpu_model'] = base.cpu_model(recorder)
        for workload in selected:
            expected = {}
            row = {'id': workload['id'], 'criteria': workload['criteria'], 'revisions': []}
            report['workloads'].append(row)
            for revision in workload['revisions']:
                directory = out / 'workloads' / workload['id'] / revision['id']
                directory.mkdir(parents=True)
                source = directory / 'source.tal'
                source.write_text(revision['source'], encoding='utf-8')
                analysis, diagnostic = edits.checked(analyze, revision['source'])
                base.require((diagnostic['code'] if diagnostic else None) == revision['expected_error'], 'workload diagnostic differs from acceptance')
                identities = ['fn:' + f.name.text for f in analysis.program.functions] + ['entry'] if analysis else None
                expected[revision['id']] = diagnostic, identities
                record = {'id': revision['id'], 'source': base.fingerprint(source), 'diagnostic': diagnostic}
                if analysis:
                    generated = directory / 'generated.c'
                    generated.write_text(emit_c(analysis, console=True))
                    oracle = directory / 'oracle.c'
                    oracle.write_bytes(revision['oracle'])
                    subject, program = directory / 'subject.o', directory / 'acceptance'
                    recorder.command([cc, *base.FLAGS, '-fno-lto', '-Dmain=talven_benchmark_main', '-c', str(generated), '-o', str(subject)])
                    recorder.command([cc, *base.FLAGS, '-fno-lto', str(subject), str(oracle), '-o', str(program)])
                    output, entry = recorder.command([str(program)])
                    base.require(output == MARKER and entry['stderr']['bytes'] == 0, 'independent current native oracle failed')
                    record.update(generated_c=base.fingerprint(generated), oracle=base.fingerprint(oracle), executable=base.fingerprint(program))
                row['revisions'].append(record)
            for phase, count in (('warmup', args.warmups), ('measured', args.repetitions)):
                for repetition in range(1, count + 1):
                    for position, mode in enumerate(MODES if repetition % 2 else tuple(reversed(MODES))):
                        measure_session(recorder, args, workload, expected, mode, phase, repetition, position,
                                        report['compiler_hash'], cc)
        for relative, identity in report['inputs'].items():
            base.require(base.fingerprint(ROOT / relative) == identity, 'measurement input changed: ' + relative)
        for path, identity in ((Path(sys.executable), report['python_executable']), (Path(cc), report['c_executable'])):
            base.require(base.fingerprint(path) == identity, 'measurement executable changed')
        base.require(compiler_hash() == report['compiler_hash'], 'compiler changed during measurement')
        report['summary'] = summarize(report['samples'], selected, args.repetitions)
        report.update(complete=True, passed=True)
        return 0
    except (base.MeasurementError, OSError, UnicodeError, ValueError) as error:
        report['error'] = str(error)
        print(str(error), file=sys.stderr)
        return 1
    except BaseException as error:
        report['error'] = type(error).__name__
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        recorder.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--expect-arch', choices=('aarch64', 'x86_64'))
    parser.add_argument('--environment-note', default='unspecified')
    parser.add_argument('--stable-toolchain', action='store_true')
    parser.add_argument('--poll-interval', type=float, default=0.05)
    parser.add_argument('--debounce', type=float, default=0.1)
    try:
        return run(parser.parse_args())
    except (base.MeasurementError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
