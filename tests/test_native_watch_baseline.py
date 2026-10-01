import argparse
import copy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_watch_measurement', ROOT / 'scripts/measure-native-watch.py')
measurement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurement)


def args(out):
    return argparse.Namespace(out=str(out), cc='cc', repetitions=1, warmups=0, timeout=20,
                              expect_arch=None, environment_note='test; not benchmark evidence',
                              stable_toolchain=True, poll_interval=0.01, debounce=0.01)


class NativeWatchBaselineTests(unittest.TestCase):
    def test_local_contract_watcher_measurement_rebuilds_only_renamed_definition(self):
        selected = [measurement.workloads()[0]]
        with tempfile.TemporaryDirectory() as temporary, patch.object(measurement, 'workloads', return_value=selected):
            out = Path(temporary) / 'local'
            options = args(out)
            options.local_contracts = True
            self.assertEqual(0, measurement.run(options))
            report = json.loads((out / 'report.json').read_text())
            self.assertTrue(report['passed'] and report['complete'] and report['local_contracts'])
            rows = measurement.read_events(out / report['sessions'][1]['path'] / 'events.jsonl')
            contract = next(row for row in rows if row['event'] == 'compiled' and row['revision'] == 4)
            self.assertEqual('hosted-object-local-contracts-v1', contract['profile'])
            self.assertEqual(['fn:step_0'], contract['compiled'])
            self.assertEqual(33, len(contract['reused']))

    def test_real_sessions_archive_current_tasks_reuse_rejections_and_clean_shutdown(self):
        selected = [measurement.workloads()[-1]]
        with tempfile.TemporaryDirectory() as temporary, patch.object(measurement, 'workloads', return_value=selected):
            out = Path(temporary) / 'report'
            self.assertEqual(0, measurement.run(args(out)))
            report = json.loads((out / 'report.json').read_text())
            self.assertTrue(report['complete'] and report['passed'])
            self.assertEqual(12, len(report['samples']))
            self.assertTrue(all(sample['verified'] for sample in report['samples']))
            self.assertEqual(2, len(report['sessions']))
            self.assertTrue(all(session['clean_shutdown'] and session['returncode'] == 143 for session in report['sessions']))
            for session in report['sessions']:
                directory = out / session['path']
                self.assertEqual(measurement.MARKER * 5, (directory / 'stdout').read_bytes())
                for name in ('stdout', 'stderr', 'events.jsonl'):
                    self.assertEqual(session[name], measurement.base.fingerprint(directory / name))
            for relative, identity in report['inputs'].items():
                self.assertEqual(identity, measurement.base.fingerprint(out / 'inputs' / relative))
            self.assertIn('examples/hello.tal', report['inputs'])
            self.assertEqual(report['summary'], measurement.summarize(report['samples'], selected, 1))
            units = {sample['revision']: sample for sample in report['samples'] if sample['mode'] == 'units'}
            self.assertEqual('started', units['trivia']['terminal_receipt']['event'])
            rows = measurement.read_events(out / report['sessions'][1]['path'] / 'events.jsonl')
            self.assertEqual([], next(row for row in rows if row['event'] == 'compiled' and row['revision'] == 2)['compiled'])
            self.assertEqual([], next(row for row in rows if row['event'] == 'compiled' and row['revision'] == 6)['compiled'])
            with self.assertRaises(measurement.base.MeasurementError):
                measurement.summarize(report['samples'][:-1], selected, 1)
            broken = copy.deepcopy(report['samples'])
            broken[0]['verified'] = False
            with self.assertRaises(measurement.base.MeasurementError):
                measurement.summarize(broken, selected, 1)
            broken[0]['verified'] = True
            broken[0]['parent_to_receipt_ns'] = -1
            with self.assertRaises(measurement.base.MeasurementError):
                measurement.summarize(broken, selected, 1)
            with self.assertRaises(measurement.base.MeasurementError):
                measurement.run(args(out))

    def test_wrong_watched_task_with_forged_receipt_identity_fails_native_acceptance(self):
        selected = [measurement.workloads()[-1]]
        actual = measurement.measure_session
        verifier = measurement.verify_events
        def wrong_task(recorder, options, workload, *rest):
            changed = copy.deepcopy(workload)
            changed['revisions'][0]['source'] = changed['revisions'][0]['source'].replace('p.x + 1', 'p.x + 99')
            return actual(recorder, options, changed, *rest)
        def forged_identity(rows, sample, *rest):
            # Source metadata cannot substitute for executing the embedded independent checks.
            sample['source_hash'] = measurement.source_hash(selected[0]['revisions'][0]['source'])
            for row in rows:
                if row.get('revision') == sample['revision_number']:
                    row['source_hash'] = sample['source_hash']
            return verifier(rows, sample, *rest)
        with tempfile.TemporaryDirectory() as temporary, patch.object(measurement, 'workloads', return_value=selected), \
                patch.object(measurement, 'measure_session', side_effect=wrong_task), \
                patch.object(measurement, 'verify_events', side_effect=forged_identity), contextlib.redirect_stderr(io.StringIO()):
            out = Path(temporary) / 'report'
            self.assertEqual(1, measurement.run(args(out)))
            report = json.loads((out / 'report.json').read_text())
            self.assertFalse(report['complete'] or report['passed'])
            self.assertIsNone(report['summary'])
            self.assertEqual(1, len(report['samples']))
            self.assertFalse(report['samples'][0]['verified'])
            self.assertIn('parent_to_receipt_ns', report['samples'][0])
            self.assertEqual(1, report['samples'][0]['exit_receipt']['returncode'])
            self.assertTrue(report['sessions'][0]['clean_shutdown'])
            self.assertIn('native task checks', report['error'])

    def test_preflight_rejects_unacknowledged_toolchain_and_invalid_measurement_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / 'report'
            for field, value in [('stable_toolchain', False), ('timeout', 61), ('poll_interval', 0),
                                 ('debounce', float('nan'))]:
                selected = args(out)
                setattr(selected, field, value)
                with self.subTest(field=field), self.assertRaises(measurement.base.MeasurementError):
                    measurement.run(selected)
                self.assertFalse(out.exists())

    def test_event_identity_and_limits_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events'
            path.write_text('{"event":"observed"}\n{"partial":')
            self.assertEqual([{'event': 'observed'}], measurement.read_events(path))
            with patch.object(measurement, 'MAX_LOG_BYTES', 1), self.assertRaises(measurement.base.MeasurementError):
                measurement.read_events(path)
        rows = [{'schema': 'talven.dev.v1', 'event': 'observed', 'revision': 1, 'source_hash': 'stale'}]
        with self.assertRaises(measurement.base.MeasurementError):
            measurement.verify_events(rows, {'revision_number': 1, 'source_hash': 'current'}, None, [], 'compiler', b'', 0)
