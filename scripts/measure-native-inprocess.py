#!/usr/bin/env python3
"""Retain native in-process phase timings behind reference and native acceptance."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


comparison = module('native_comparison', 'scripts/measure-native-prototype.py')
edits = module('incremental_comparison', 'scripts/measure-incremental.py')
base = comparison.base
from talven.backend import emit_c
from talven.frontend import CompileError, analyze

OPERATIONS = ('parse_ns', 'check_ns', 'analysis_ns', 'emit_ns')


def workloads():
    result = [comparison.selected_workloads()[0]]
    for workload in edits.workloads():
        initial = workload['revisions'][0]
        criteria = ('Exact native/reference C; read preserves three owners, bump stores/returns input + 1; main returns zero.'
                    if workload['id'] == 'borrowing' else
                    'Exact native/reference C; three full-i32 chain results; main returns zero.')
        result.append({'id': workload['id'], 'origin': 'generated: fixed initial edit-baseline source',
                       'source': initial['source'].encode(), 'oracle': initial['oracle'],
                       'console': True, 'stdout': b'', 'criteria': criteria})
    return result


def validate_receipt(receipt, workload, repetitions, warmups, expected_c):
    base.require(isinstance(receipt, dict), 'native measurement receipt must be an object')
    base.require(receipt.get('schema') == 'talven.native-inprocess.v1' and receipt.get('complete') is True,
                 'native measurement receipt is incomplete or has the wrong schema')
    base.require(receipt.get('profile') == 'native-call-borrows-v1' and receipt.get('console') is True,
                 'unexpected measurement profile/options')
    base.require(type(receipt.get('preflight_analysis')) is int and receipt['preflight_analysis'] == 1,
                 'unmeasured preflight count mismatch')
    base.require(receipt.get('source') == workload['source'].decode()
                 and type(receipt.get('source_bytes')) is int
                 and receipt['source_bytes'] == len(workload['source']), 'measurement source mismatch')
    base.require(type(receipt.get('iterations')) is int and type(receipt.get('warmups')) is int
                 and receipt['iterations'] == repetitions and receipt['warmups'] == warmups,
                 'measurement repetition count mismatch')
    base.require(receipt.get('generated_c') == expected_c, 'measured C differs from independently accepted reference')
    samples = receipt.get('samples')
    base.require(isinstance(samples, list) and len(samples) == repetitions + warmups, 'incomplete native samples')
    for index, sample in enumerate(samples):
        base.require(isinstance(sample, dict), 'invalid native sample')
        phase = 'warmup' if index < warmups else 'measured'
        base.require(sample.get('phase') == phase, 'native sample ordering/phase mismatch')
        base.require(all(type(sample.get(key)) is int and sample[key] >= 0 for key in OPERATIONS),
                     'native timing must be a nonnegative integer in nanoseconds')
        base.require(sample['analysis_ns'] >= sample['parse_ns'] + sample['check_ns'], 'overlapping/inconsistent analysis timing')
    return samples


def summarize(samples, repetitions):
    result = []
    for workload in workloads():
        group = [s for s in samples if s['workload'] == workload['id'] and s['phase'] == 'measured']
        base.require(len(group) == repetitions and all(s['verified'] for s in group), 'incomplete verified native samples')
        for operation in OPERATIONS:
            values = [s[operation] for s in group]
            result.append({'workload': workload['id'], 'operation': operation, 'samples': len(values),
                           'min_ns': min(values), 'median_ns': statistics.median(values), 'max_ns': max(values)})
    return result


def run(args):
    out, cc, arch = base.preflight(args.out, args.repetitions, args.warmups, args.timeout, args.cc, args.expect_arch)
    binary = Path(args.native).resolve()
    base.require(binary.is_file(), '--native must name a built compiler executable')
    out.mkdir(parents=True)
    (out / 'commands').mkdir()
    report = {'schema': 'talven.native-phase-baseline.v1', 'complete': False, 'passed': False,
              'summary': None, 'samples': [], 'commands': [], 'workloads': [], 'inputs': {},
              'started_at': datetime.now(timezone.utc).isoformat(), 'repetitions': args.repetitions,
              'warmups': args.warmups, 'unmeasured_native_preflight_per_workload': 1,
              'timeout_seconds': args.timeout, 'machine': arch, 'system': platform.system(),
              'os_release': platform.release(), 'python': platform.python_version(),
              'python_executable': base.fingerprint(Path(sys.executable)), 'c_executable': base.fingerprint(Path(cc)),
              'native': base.fingerprint(binary), 'native_path': str(binary), 'compiler_hash': base.compiler_hash(),
              'c_flags': [*base.FLAGS, '-fno-lto'], 'environment_overrides': base.ENVIRONMENT,
              'environment_note': args.environment_note, 'clock': 'Rust std::time::Instant; nanoseconds',
              'timed_boundary': 'Native full lex/parse/depth checks; declaration/body checking; total instrumented analysis; C emission. Source I/O, verification, destruction of returned Program/C, serialization, process startup and C builds excluded.',
              'unmeasured': ['startup comparison', 'cold caches', 'memory', 'incremental reuse', 'C builds', 'save-to-running latency', 'model/token/dollar effectiveness']}
    recorder = base.Recorder(out, report, args.timeout)
    recorder.save()
    try:
        native = ROOT / 'experiments/native-compiler'
        inputs = sorted([*ROOT.joinpath('talven').glob('*.py'), *native.joinpath('src').glob('*'),
                         native / 'build.rs', native / 'Cargo.toml', native / 'Cargo.lock',
                         Path(__file__).resolve(), ROOT / 'scripts/measure-native-prototype.py',
                         ROOT / 'scripts/measure-incremental.py', ROOT / 'scripts/measure-tooling.py',
                         ROOT / 'experiments/tooling_workloads.py', ROOT / 'examples/hello.tal'])
        for path in inputs:
            relative = path.relative_to(ROOT)
            archived = out / 'inputs' / relative
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_bytes(path.read_bytes())
            report['inputs'][str(relative)] = base.fingerprint(archived)
        archived_binary = out / 'inputs' / 'native-executable'
        archived_binary.write_bytes(binary.read_bytes())
        archived_binary.chmod(0o755)
        base.require(base.fingerprint(archived_binary) == report['native'], 'native executable changed during archive')
        for key, command in {'git_revision': ['git', 'rev-parse', 'HEAD'], 'git_status': ['git', 'status', '--porcelain'],
                             'c_version': [cc, '--version'], 'c_target': [cc, '-dumpmachine'],
                             'native_build_info': [str(binary), '--build-info'], 'native_version': [str(binary), '--version']}.items():
            output, _ = recorder.command(command, phase='provenance')
            report[key] = json.loads(output) if key == 'native_build_info' else output.decode().strip()
        comparison.verify_build_sources(report['native_build_info'], native)
        base.require(report['native_build_info']['target'].split('-')[0] == arch, 'native target does not match measurement host')
        report['native_build_sources_verified'] = True
        report['cpu_model'] = base.cpu_model(recorder)
        for workload in workloads():
            directory = out / 'workloads' / workload['id']
            directory.mkdir(parents=True)
            source = directory / 'source.tal'
            source.write_bytes(workload['source'])
            expected = emit_c(analyze(workload['source'].decode()), console=True)
            generated, entry = recorder.command([str(binary), 'emit-c', str(source), '--console'],
                                                phase='preflight', workload=workload['id'], operation='emit-c')
            base.require(generated == expected.encode(), 'native preflight differs from reference C')
            entry['verified'] = True
            row = {key: workload[key] for key in ('id', 'origin', 'criteria')}
            row.update(source=base.fingerprint(source), native_acceptance=comparison.verify_c(recorder, cc, directory, generated, workload))
            report['workloads'].append(row)
            output, entry = recorder.command([str(binary), 'measure', str(source), '--iterations', str(args.repetitions),
                                              '--warmups', str(args.warmups)], phase='core-measurement',
                                             workload=workload['id'], operation='native-phases')
            receipt = json.loads(output)
            samples = validate_receipt(receipt, workload, args.repetitions, args.warmups, expected)
            for sample in samples:
                report['samples'].append({**sample, 'workload': workload['id'], 'verified': True})
            entry['verified'] = True
            recorder.save()
        for relative, identity in report['inputs'].items():
            base.require(base.fingerprint(ROOT / relative) == identity, f'input changed: {relative}')
        for path, identity in ((binary, report['native']), (Path(sys.executable), report['python_executable']),
                               (Path(cc), report['c_executable'])):
            base.require(base.fingerprint(path) == identity, f'executable changed: {path}')
        base.require(base.compiler_hash() == report['compiler_hash'], 'reference compiler changed')
        report['summary'] = summarize(report['samples'], args.repetitions)
        report.update(complete=True, passed=True)
        return 0
    except (base.MeasurementError, OSError, ValueError, CompileError) as error:
        report['error'] = str(error)
        print(str(error), file=sys.stderr)
        return 1
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        recorder.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--repetitions', type=int, default=20)
    parser.add_argument('--warmups', type=int, default=2)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--expect-arch', choices=('aarch64', 'x86_64'))
    parser.add_argument('--environment-note', default='unspecified')
    try:
        return run(parser.parse_args())
    except (base.MeasurementError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
