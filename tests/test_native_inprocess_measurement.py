import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('native_inprocess', ROOT / 'scripts/measure-native-inprocess.py')
measurement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measurement)


class NativeInprocessMeasurementTests(unittest.TestCase):
    def receipt(self):
        workload = measurement.workloads()[0]
        return workload, {'schema': 'talven.native-inprocess.v1', 'complete': True,
                          'profile': 'native-call-borrows-v1', 'console': True, 'preflight_analysis': 1,
                          'source': workload['source'].decode(), 'source_bytes': len(workload['source']),
                          'iterations': 1, 'warmups': 0, 'generated_c': 'accepted C',
                          'samples': [{'phase': 'measured', 'parse_ns': 4, 'check_ns': 6,
                                       'analysis_ns': 12, 'emit_ns': 8}]}

    def test_receipts_reject_source_output_counts_phases_and_invalid_clock_values(self):
        workload, receipt = self.receipt()
        self.assertEqual(receipt['samples'], measurement.validate_receipt(receipt, workload, 1, 0, 'accepted C'))
        for invalid in (None, [], True):
            with self.subTest(receipt=invalid), self.assertRaises(measurement.base.MeasurementError):
                measurement.validate_receipt(invalid, workload, 1, 0, 'accepted C')
        for changes in ({'complete': False}, {'schema': 'other'}, {'source': 'different'},
                        {'source_bytes': 1}, {'iterations': True}, {'warmups': False},
                        {'preflight_analysis': True}, {'generated_c': 'wrong C'}, {'samples': []},
                        {'profile': 'other'}, {'console': False}):
            with self.subTest(changes=changes), self.assertRaises(measurement.base.MeasurementError):
                measurement.validate_receipt({**receipt, **changes}, workload, 1, 0, 'accepted C')
        for changes in ({'phase': 'warmup'}, {'check_ns': True}, {'parse_ns': -1},
                        {'emit_ns': 1.5}, {'analysis_ns': 9}):
            changed = copy.deepcopy(receipt)
            changed['samples'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(measurement.base.MeasurementError):
                measurement.validate_receipt(changed, workload, 1, 0, 'accepted C')

    def test_summary_excludes_warmups_and_requires_all_verified_measured_samples(self):
        samples = []
        for workload in measurement.workloads():
            for duration in (10, 30, 20):
                samples.append({'workload': workload['id'], 'phase': 'measured', 'verified': True,
                                **{key: duration for key in measurement.OPERATIONS}})
        samples.append({**samples[0], 'phase': 'warmup', 'analysis_ns': 1000000})
        rows = measurement.summarize(samples, 3)
        self.assertEqual(20, len(rows))
        self.assertTrue(all(row['median_ns'] == 20 for row in rows))
        with self.assertRaises(measurement.base.MeasurementError):
            measurement.summarize(samples[1:], 3)
        samples[0]['verified'] = False
        with self.assertRaises(measurement.base.MeasurementError):
            measurement.summarize(samples, 3)

    def test_failed_native_receipt_retains_no_successful_summary_or_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / 'new'
            command = [sys.executable, str(ROOT / 'scripts/measure-native-inprocess.py'),
                       '--native', sys.executable, '--out', str(out), '--repetitions', '1', '--warmups', '0']
            result = subprocess.run(command, capture_output=True, timeout=15)
            self.assertEqual(1, result.returncode)
            report = json.loads((out / 'report.json').read_text())
            self.assertFalse(report['passed'])
            self.assertFalse(report['complete'])
            self.assertIsNone(report['summary'])
            self.assertIn('error', report)
            # The shared workload factory reads examples even when those cases are
            # filtered out. Replaying the archive must not depend on the checkout.
            replay = subprocess.run([sys.executable, '-I', '-c',
                                     'import importlib.util, sys; '
                                     's = importlib.util.spec_from_file_location("replay", sys.argv[1]); '
                                     'm = importlib.util.module_from_spec(s); s.loader.exec_module(m); '
                                     'print(",".join(w["id"] for w in m.workloads()))',
                                     str(out / 'inputs/scripts/measure-native-inprocess.py')],
                                    capture_output=True, timeout=15)
            self.assertEqual(0, replay.returncode, replay.stderr)
            self.assertEqual(b'hello,chain-32,chain-128,stores-128,borrowing\n', replay.stdout)
            before = (out / 'report.json').read_bytes()
            self.assertEqual(1, subprocess.run(command, capture_output=True, timeout=15).returncode)
            self.assertEqual(before, (out / 'report.json').read_bytes())
