import argparse
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('unit_rebuild_measurement', ROOT / 'scripts/measure-unit-rebuilds.py')
measurement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurement)


def args(path):
    return argparse.Namespace(out=str(path), cc='cc', repetitions=1, warmups=0, timeout=30,
                              expect_arch=None, stable_toolchain=True, environment_note='test-only')


class UnitRebuildBaselineTests(unittest.TestCase):
    def test_verified_native_run_archives_inputs_samples_and_invalid_repair(self):
        workload = measurement.edits.workloads()[-1]
        with tempfile.TemporaryDirectory() as temporary, patch.object(measurement.edits, 'workloads', return_value=[workload]):
            out = Path(temporary) / 'report'
            self.assertEqual(0, measurement.run(args(out)))
            report = json.loads((out / 'report.json').read_text())
            self.assertTrue(report['complete'] and report['passed'])
            self.assertEqual(12, len(report['samples']))
            self.assertTrue(all(s['verified'] for s in report['samples']))
            unit_samples = {s['revision']: s for s in report['samples'] if s['mode'] == 'units'}
            self.assertEqual([], unit_samples['trivia']['receipt']['compiled'])
            self.assertEqual(['fn:bump', 'fn:main'], unit_samples['body']['receipt']['compiled'])
            self.assertEqual([], unit_samples['repair']['receipt']['compiled'])
            self.assertEqual('E0201', unit_samples['invalid']['diagnostic']['code'])
            for relative, identity in report['inputs'].items():
                self.assertEqual(identity, measurement.base.fingerprint(out / 'inputs' / relative))
            self.assertIn('experiments/__init__.py', report['inputs'])
            self.assertIn('examples/hello.tal', report['inputs'])
            self.assertEqual(report['summary'], measurement.summarize(report['samples'], 1))
            with self.assertRaises(measurement.base.MeasurementError):
                measurement.summarize(report['samples'][:-1], 1)
            broken = copy.deepcopy(report['samples'])
            broken[0]['verified'] = False
            with self.assertRaises(measurement.base.MeasurementError):
                measurement.summarize(broken, 1)
            receipt = unit_samples['initial']['receipt']
            identities = [row['id'] for row in receipt['objects']]
            for field, value in [('source_hash', 'wrong'), ('flags', []), ('objects', [None]),
                                 ('compiled', receipt['compiled'] + [receipt['compiled'][0]])]:
                changed = copy.deepcopy(receipt)
                changed[field] = value
                with self.subTest(field=field), self.assertRaises(measurement.base.MeasurementError):
                    measurement.validate_work(changed, workload['revisions'][0]['source'], report['compiler_hash'], identities)
            with self.assertRaises(measurement.base.MeasurementError):
                measurement.run(args(out))

    def test_wrong_actual_objects_fail_independent_oracle_with_partial_samples_retained(self):
        workload = measurement.edits.workloads()[-1]
        original = measurement.UnitBuildSession.build
        def wrong_objects(session, source):
            wrong = source.replace('p.x + 1', 'p.x + 999').replace('bump(&mut p) - 2', 'bump(&mut p) - 1000')
            result = original(session, wrong)
            # Deliberately forged metadata proves the native oracle is an independent gate.
            result.receipt['source_hash'] = measurement.source_hash(source)
            return result
        with tempfile.TemporaryDirectory() as temporary, patch.object(measurement.edits, 'workloads', return_value=[workload]), \
                patch.object(measurement.UnitBuildSession, 'build', wrong_objects), contextlib.redirect_stderr(io.StringIO()):
            out = Path(temporary) / 'report'
            self.assertEqual(1, measurement.run(args(out)))
            report = json.loads((out / 'report.json').read_text())
            self.assertFalse(report['complete'] or report['passed'])
            self.assertIsNone(report['summary'])
            self.assertTrue(report['samples'][0]['verified'])
            self.assertFalse(report['samples'][-1]['verified'])
            self.assertIn('elapsed_ns', report['samples'][-1])
            self.assertEqual(1, report['commands'][-1]['returncode'])
            self.assertEqual('units', report['samples'][-1]['mode'])

    def test_preflight_requires_new_output_and_stable_toolchain_acknowledgement(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / 'new'
            selected = args(out)
            selected.stable_toolchain = False
            with self.assertRaises(measurement.base.MeasurementError):
                measurement.run(selected)
            self.assertFalse(out.exists())
            selected.stable_toolchain = True
            selected.timeout = 61
            with self.assertRaises(measurement.base.MeasurementError):
                measurement.run(selected)
            self.assertFalse(out.exists())
