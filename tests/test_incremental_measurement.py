import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from talven.incremental import IncrementalFrontend

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("measure_incremental", ROOT / "scripts/measure-incremental.py")
measurement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measurement)


class IncrementalMeasurementTests(unittest.TestCase):
    def test_body_syntax_runner_verifies_selected_parsing_work_and_current_facts(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / 'run'
            args = argparse.Namespace(out=str(out), cc='cc', repetitions=1, warmups=0, timeout=10,
                                      expect_arch=None, environment_note='fixture measurement',
                                      call_type_contracts=True, reuse_body_syntax=True)
            with patch.object(measurement, 'workloads', return_value=[measurement.workloads()[0]]):
                self.assertEqual(0, measurement.run(args))
            report = json.loads((out/'report.json').read_text())
            self.assertTrue(report['complete'] and report['passed'] and report['reuse_body_syntax'])
            initial = next(s for s in report['samples'] if s['mode']=='incremental' and s['revision']=='initial')
            trivia = next(s for s in report['samples'] if s['mode']=='incremental' and s['revision']=='trivia')
            self.assertEqual([], initial['parsing']['reused'])
            self.assertEqual([], trivia['parsing']['parsed'])
            self.assertEqual(trivia['reuse']['reused'], trivia['parsing']['reused'])

    def test_call_type_runner_retains_selected_mode_and_complete_input_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / 'run'
            args = argparse.Namespace(out=str(out), cc='cc', repetitions=1, warmups=0, timeout=10,
                                      expect_arch=None, environment_note='fixture measurement', call_type_contracts=True)
            with patch.object(measurement, 'workloads', return_value=[measurement.workloads()[0]]):
                self.assertEqual(0, measurement.run(args))
            report = json.loads((out/'report.json').read_text())
            self.assertTrue(report['complete'] and report['passed'] and report['call_type_contracts'])
            self.assertIn('experiments/__init__.py', report['inputs'])
            self.assertIn('examples/borrowing.tal', report['inputs'])
            selected = next(s for s in report['samples'] if s['mode']=='incremental' and s['revision']=='contract')
            self.assertEqual(['step_0'], selected['reuse']['checked'])

    def test_call_type_workloads_reuse_renamed_caller_with_current_full_facts(self):
        for workload in measurement.workloads():
            frontend = IncrementalFrontend(call_type_contracts=True)
            for revision in workload['revisions']:
                with self.subTest(workload=workload['id'], revision=revision['id']):
                    actual, error = measurement.checked(frontend.analyze, revision['source'])
                    expected, full_error = measurement.checked(measurement.analyze, revision['source'])
                    self.assertEqual((expected, full_error), (actual, error))
                    if revision['id'] == 'contract':
                        self.assertEqual(['step_0'], frontend.stats['checked'])
                        self.assertIn('step_1', frontend.stats['reused'])
                    elif revision['id'] == 'schema':
                        self.assertEqual(['read', 'bump', 'main'], frontend.stats['checked'])

    def test_workload_edits_have_expected_reuse_and_current_full_results(self):
        self.assertEqual(['chain-32', 'chain-128', 'stores-128', 'borrowing'],
                         [w['id'] for w in measurement.workloads()])
        for workload in measurement.workloads():
            frontend = IncrementalFrontend()
            for revision in workload['revisions']:
                with self.subTest(workload=workload['id'], revision=revision['id']):
                    actual, diagnostic = measurement.checked(frontend.analyze, revision['source'])
                    expected, full_error = measurement.checked(measurement.analyze, revision['source'])
                    self.assertEqual(expected, actual)
                    self.assertEqual(full_error, diagnostic)
                    self.assertEqual(revision['expected_error'], diagnostic['code'] if diagnostic else None)
                    if revision['id'] in ('trivia', 'repair'):
                        self.assertEqual([], frontend.stats['checked'])
                        self.assertEqual(list(actual.functions), frontend.stats['reused'])
                    elif revision['id'] == 'body':
                        self.assertEqual(['bump', 'main'] if workload['id'] == 'borrowing' else ['step_0', 'main'],
                                         frontend.stats['checked'])
                    elif revision['id'] == 'contract':
                        self.assertEqual(['step_0', 'step_1'], frontend.stats['checked'])
                    elif revision['id'] == 'schema':
                        self.assertEqual(['read', 'bump', 'main'], frontend.stats['checked'])

    def test_summary_excludes_warmups_and_rejects_missing_or_unverified_samples(self):
        samples = []
        for workload in measurement.workloads():
            for revision in workload['revisions']:
                for mode in ('full', 'incremental'):
                    for duration in (10, 30, 20):
                        samples.append(dict(phase='measured', workload=workload['id'], revision=revision['id'],
                                            mode=mode, elapsed_ns=duration, verified=True))
        samples.append({**samples[0], 'phase': 'warmup', 'elapsed_ns': 1000000})
        result = measurement.summarize(samples, 3)
        self.assertEqual(48, len(result))
        self.assertTrue(all(row['median_ns'] == 20 for row in result))
        with self.assertRaises(measurement.base.MeasurementError):
            measurement.summarize(samples[1:], 3)
        samples[0]['verified'] = False
        with self.assertRaises(measurement.base.MeasurementError):
            measurement.summarize(samples, 3)

    def test_missing_successful_analysis_retains_failed_report_without_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / 'new'
            args = argparse.Namespace(out=str(out), cc='cc', repetitions=1, warmups=0, timeout=5,
                                      expect_arch=None, environment_note='test-only command doubles')
            with patch.object(measurement.base, 'preflight', return_value=(out, '/fake/cc', 'aarch64')), \
                 patch.object(measurement.base, 'fingerprint', return_value={'bytes': 1, 'sha256': 'test'}), \
                 patch.object(measurement.base.Recorder, 'command', return_value=(b'test', {})), \
                 patch.object(measurement.base, 'cpu_model', return_value='test'), \
                 patch.object(measurement, 'checked', return_value=(None, None)):
                self.assertEqual(1, measurement.run(args))
            report = json.loads((out / 'report.json').read_text())
            self.assertFalse(report['passed'])
            self.assertFalse(report['complete'])
            self.assertIsNone(report['summary'])
            self.assertIn('analysis is missing', report['error'])
