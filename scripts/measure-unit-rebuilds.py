#!/usr/bin/env python3
"""Compare whole C builds and private object reuse with actual native acceptance."""

import argparse
from datetime import datetime, timezone
import gc
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('unit_edits', ROOT / 'scripts/measure-incremental.py')
edits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edits)
base = edits.base
from talven import PROFILE, VERSION
from talven.backend import emit_c
from talven.context import compiler_hash, encode, source_hash
from talven.frontend import CompileError, analyze
from talven.preprocessed_units import run_bounded
from talven.unit_build import OBJECT_FLAGS, UnitBuildSession

MODES = ('full', 'units')


def input_files():
    return sorted([*ROOT.joinpath('talven').glob('*.py'), Path(__file__).resolve(),
                   ROOT / 'scripts/measure-incremental.py', ROOT / 'scripts/measure-tooling.py',
                   ROOT / 'experiments/tooling_workloads.py', ROOT / 'experiments/__init__.py',
                   *ROOT.joinpath('examples').glob('*.tal')])


def full_build(source, cc, program, timeout):
    started = time.monotonic()
    generated = emit_c(analyze(source))
    remaining = timeout - (time.monotonic() - started)
    base.require(remaining > 0, 'full build exhausted its subprocess time budget')
    run_bounded([cc, *OBJECT_FLAGS, '-x', 'c', '-', '-o', str(program)],
                generated.encode(), dict(os.environ), remaining, 64 * 1024)
    return source_hash(generated)


def validate_work(receipt, source, pinned, identifiers, *, local_contracts=False):
    base.require(isinstance(receipt, dict) and receipt.get('schema') == 'talven.unit-build.v1'
                 and receipt.get('profile') == ('hosted-object-local-contracts-v1' if local_contracts
                                                else 'hosted-object-reuse-v1'), 'unexpected build receipt')
    base.require(receipt.get('source_hash') == source_hash(source) and receipt.get('compiler_hash') == pinned,
                 'unit receipt describes a different source/compiler')
    base.require(receipt.get('language_profile') == PROFILE and receipt.get('console') is False
                 and receipt.get('flags') == list(OBJECT_FLAGS)
                 and receipt.get('stable_toolchain_required') is True, 'unit build configuration mismatch')
    objects = receipt.get('objects')
    base.require(isinstance(objects, list) and all(isinstance(row, dict) for row in objects)
                 and [row.get('id') for row in objects] == identifiers,
                 'unit receipt has missing/unordered objects')
    for row in objects:
        base.require(all(isinstance(row.get(key), str) and len(row[key]) == 64
                         and all(c in '0123456789abcdef' for c in row[key])
                         for key in ('key', 'c_hash', 'object_hash')), 'malformed object byte identity')
    compiled, reused = receipt.get('compiled'), receipt.get('reused')
    base.require(isinstance(compiled, list) and isinstance(reused, list)
                 and all(isinstance(value, str) for value in compiled + reused), 'invalid work lists')
    base.require(len(compiled + reused) == len(identifiers) and len(set(compiled + reused)) == len(identifiers)
                 and set(compiled + reused) == set(identifiers), 'unit work does not partition current objects')


def summarize(samples, repetitions):
    result = []
    for workload in edits.workloads():
        for revision in workload['revisions']:
            for mode in MODES:
                group = [s for s in samples if s['phase'] == 'measured' and s['workload'] == workload['id']
                         and s['revision'] == revision['id'] and s['mode'] == mode]
                base.require(len(group) == repetitions and all(s.get('verified') for s in group),
                             'incomplete verified unit rebuild samples')
                base.require(all(type(s.get('elapsed_ns')) is int and s['elapsed_ns'] >= 0 for s in group),
                             'invalid rebuild timing')
                values = [s['elapsed_ns'] for s in group]
                result.append({'workload': workload['id'], 'revision': revision['id'], 'mode': mode,
                               'samples': len(group), 'min_ns': min(values),
                               'median_ns': statistics.median(values), 'max_ns': max(values),
                               'compiled_counts': [len(s['receipt']['compiled']) for s in group] if mode == 'units'
                               and revision['expected_error'] is None else None,
                               'reused_counts': [len(s['receipt']['reused']) for s in group] if mode == 'units'
                               and revision['expected_error'] is None else None})
    return result


def run(args):
    out, cc, arch = base.preflight(args.out, args.repetitions, args.warmups, args.timeout, args.cc, args.expect_arch)
    base.require(0.01 <= args.timeout <= 60, 'unit build timeout must be 0.01..60 seconds')
    base.require(args.stable_toolchain is True, 'assert --stable-toolchain for this trusted local experiment')
    local_contracts = getattr(args, 'local_contracts', False)
    base.require(type(local_contracts) is bool, 'local contracts must be an explicit boolean')
    out.mkdir(parents=True)
    (out / 'commands').mkdir()
    report = {'schema': 'talven.unit-rebuild-baseline.v1', 'complete': False, 'passed': False,
              'summary': None, 'samples': [], 'commands': [], 'inputs': {}, 'workloads': [],
              'started_at': datetime.now(timezone.utc).isoformat(), 'repetitions': args.repetitions,
              'warmups': args.warmups, 'compiler_hash': compiler_hash(), 'language_profile': PROFILE,
              'compiler_version': VERSION, 'machine': arch, 'system': platform.system(),
              'os_release': platform.release(), 'python': platform.python_version(),
              'python_executable': base.fingerprint(Path(sys.executable)), 'c_executable': base.fingerprint(Path(cc)),
              'flags': list(OBJECT_FLAGS), 'timeout_seconds': args.timeout,
              'stable_toolchain_required': True, 'local_contracts': local_contracts, 'environment_note': args.environment_note,
              'child_environment_overrides': base.ENVIRONMENT,
              'python_hash_seed_at_start': os.environ.get('PYTHONHASHSEED'),
              'garbage_collector': {'enabled': gc.isenabled(), 'thresholds': gc.get_threshold()},
              'clock': {'implementation': time.get_clock_info('perf_counter').implementation,
                        'resolution_seconds': time.get_clock_info('perf_counter').resolution},
              'timed_boundary': 'In-process current analysis/emission and native build. Full uses one whole-C compiler invocation; units includes fresh preprocessing/driver probes, object validation/copy/compilation and link. Initial units includes session construction. Verification, artifact archiving and final session/temporary cleanup excluded; replacement cleanup within build included.',
              'unmeasured': ['frontend process startup', 'cold OS caches', 'memory', 'save-to-running/readiness latency',
                             'watcher cancellation', 'state preservation', 'native Rust reuse', 'model/token/dollar benefit']}
    previous_environment = {key: os.environ.get(key) for key in base.ENVIRONMENT}
    os.environ.update(base.ENVIRONMENT)
    report['effective_environment_hash'] = source_hash(encode(dict(os.environ)))
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
        for workload in edits.workloads():
            expected = {}
            row = {'id': workload['id'], 'criteria': workload['criteria'], 'revisions': []}
            report['workloads'].append(row)
            for revision in workload['revisions']:
                directory = out / 'workloads' / workload['id'] / revision['id']
                directory.mkdir(parents=True)
                source = directory / 'source.tal'
                source.write_text(revision['source'], encoding='utf-8')
                analysis, diagnostic = edits.checked(analyze, revision['source'])
                base.require((diagnostic['code'] if diagnostic else None) == revision['expected_error'],
                             'workload validity differs from its declared acceptance')
                generated = emit_c(analysis) if analysis else None
                identifiers = ['fn:' + f.name.text for f in analysis.program.functions] + ['entry'] if analysis else None
                expected[revision['id']] = diagnostic, source_hash(generated) if generated else None, identifiers
                record = {'id': revision['id'], 'source': base.fingerprint(source), 'diagnostic': diagnostic,
                          'native_acceptance': None}
                if analysis:
                    record['native_acceptance'] = edits.verify_native(recorder, cc, directory, generated, revision['oracle'])
                row['revisions'].append(record)
            for phase, count in (('warmup', args.warmups), ('measured', args.repetitions)):
                for repetition in range(count):
                    session = None
                    with tempfile.TemporaryDirectory(prefix='talven-full-measure-') as temporary:
                        try:
                            for revision in workload['revisions']:
                                order = MODES if repetition % 2 == 0 else tuple(reversed(MODES))
                                for position, mode in enumerate(order):
                                    sample = {'phase': phase, 'repetition': repetition + 1, 'workload': workload['id'],
                                              'revision': revision['id'], 'mode': mode, 'order': position,
                                              'verified': False, 'receipt': None, 'diagnostic': None}
                                    report['samples'].append(sample)
                                    recorder.save()
                                    result, generated_hash = None, None
                                    program = Path(temporary) / 'program'
                                    started = time.perf_counter_ns()
                                    try:
                                        if mode == 'units':
                                            if session is None:
                                                session = UnitBuildSession(stable_toolchain=True, cc=cc, timeout=args.timeout,
                                                                           local_contracts=local_contracts)
                                            result = session.build(revision['source'])
                                            program = result.executable
                                        else:
                                            generated_hash = full_build(revision['source'], cc, program, args.timeout)
                                    except CompileError as error:
                                        sample['diagnostic'] = error.diagnostic(revision['source'])
                                    finally:
                                        sample['elapsed_ns'] = time.perf_counter_ns() - started
                                        recorder.save()
                                    error, wanted_c_hash, identifiers = expected[revision['id']]
                                    base.require(sample['diagnostic'] == error, 'current build diagnostic mismatch')
                                    if error is None:
                                        directory = out / 'samples' / phase / str(repetition + 1) / workload['id'] / revision['id'] / mode
                                        directory.mkdir(parents=True)
                                        retained = directory / 'program'
                                        shutil.copy2(program, retained)
                                        sample['executable'] = base.fingerprint(retained)
                                        output, entry = recorder.command([str(retained)], workload=workload['id'], operation=revision['id'])
                                        base.require(output == b'' and entry['stderr']['bytes'] == 0, 'current program output mismatch')
                                        if mode == 'units':
                                            sample['receipt'] = result.receipt
                                            validate_work(result.receipt, revision['source'], report['compiler_hash'], identifiers,
                                                          local_contracts=local_contracts)
                                            base.require(result.receipt['executable_hash'] == sample['executable']['sha256'],
                                                         'retained candidate bytes differ from build receipt')
                                            oracle = directory / 'oracle.c'
                                            oracle.write_bytes(revision['oracle'])
                                            actual_objects = []
                                            for obj in result.receipt['objects']:
                                                path = session._cache[obj['id']][1]
                                                base.require(base.fingerprint(path)['sha256'] == obj['object_hash'],
                                                             'actual object differs from its current receipt')
                                                if obj['id'] != 'entry':
                                                    actual_objects.append(str(path))
                                            acceptance = directory / 'acceptance'
                                            recorder.command([cc, *OBJECT_FLAGS, *actual_objects, str(oracle), '-o', str(acceptance)])
                                            output, entry = recorder.command([str(acceptance)])
                                            base.require(output == b'' and entry['stderr']['bytes'] == 0,
                                                         'actual reused objects failed independent native acceptance')
                                            sample['oracle'] = base.fingerprint(oracle)
                                        else:
                                            base.require(generated_hash == wanted_c_hash, 'timed whole C differs from accepted input')
                                    sample['verified'] = True
                                    recorder.save()
                        finally:
                            if session is not None:
                                session.close()
        for relative, identity in report['inputs'].items():
            base.require(base.fingerprint(ROOT / relative) == identity, 'measurement input changed: ' + relative)
        for path, identity in ((Path(sys.executable), report['python_executable']), (Path(cc), report['c_executable'])):
            base.require(base.fingerprint(path) == identity, 'measurement executable changed: ' + str(path))
        base.require(compiler_hash() == report['compiler_hash'], 'compiler changed during measurement')
        report['summary'] = summarize(report['samples'], args.repetitions)
        report.update(complete=True, passed=True)
        return 0
    except (base.MeasurementError, CompileError, OSError, UnicodeError, ValueError) as error:
        report['error'] = str(error)
        print(str(error), file=sys.stderr)
        return 1
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        recorder.save()
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--expect-arch', choices=('aarch64', 'x86_64'))
    parser.add_argument('--environment-note', default='unspecified')
    parser.add_argument('--stable-toolchain', action='store_true', help='Assert a trusted toolchain stable throughout this run')
    parser.add_argument('--local-contracts', action='store_true', help='Select the separate local function contract profile for native units')
    try:
        return run(parser.parse_args())
    except (base.MeasurementError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
