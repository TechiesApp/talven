import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from talven.c_command import BoundedCommand
from talven.c_pipeline import BuildPipeline, CompilerRequest, run_steps
from talven.frontend import CompileError
from talven.unit_build import UnitBuildSession

SOURCE = ('fn value() -> i32 { return 70003; } '
          'fn main() -> i32 { if (value() == 70003) { return 0; } return 1; }')
CHANGED = SOURCE.replace('70003', '70004')


def finish(pipeline):
    while not pipeline.poll():
        time.sleep(0.001)
    return pipeline.result


def execute(path):
    result = subprocess.run([str(path)], capture_output=True, timeout=5)
    return result.returncode, result.stdout, result.stderr


class CompilerPipelineTests(unittest.TestCase):
    def test_polling_and_blocking_builds_share_current_bytes_work_and_native_acceptance(self):
        source = 'fn text() -> str { return "hé🙂\\0\\n"; } fn main() -> i32 { return print(text()); }'
        with UnitBuildSession(stable_toolchain=True, console=True) as blocking, \
                UnitBuildSession(stable_toolchain=True, console=True) as polling:
            for current in (source, source.replace('hé🙂', 'new🙂'), source.replace('hé🙂', 'new🙂') + '\n// current\n'):
                expected = blocking.build(current)
                with polling.start_build(current) as pipeline:
                    result = finish(pipeline)
                    self.assertTrue(pipeline.poll())
                    self.assertIsNone(pipeline.pid)
                    self.assertIsNone(pipeline.stage)
                for field in ('source_hash', 'objects', 'compiled', 'reused', 'driver_probe_reused'):
                    self.assertEqual(expected.receipt[field], result.receipt[field])
                self.assertEqual(execute(expected.executable), execute(result.executable))
                self.assertEqual((0, ('hé🙂' if current == source else 'new🙂').encode() + b'\0\n', b''), execute(result.executable))
                self.assertFalse(polling._busy)
                self.assertEqual(1, len(list(polling._root.iterdir())))

    def test_cancel_each_build_stage_discards_candidate_and_preserves_last_success_for_repair(self):
        original = CompilerRequest.start
        for target in ('prepare', 'compile', 'link'):
            with self.subTest(stage=target), tempfile.TemporaryDirectory() as temporary, \
                    UnitBuildSession(stable_toolchain=True) as session:
                successful = session.build(SOURCE)
                previous_cache, previous_probe = session._cache, session._probe
                marker = Path(temporary) / 'active'
                script = ('import os,pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                          f'pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)')
                def delayed(request):
                    if request.stage == target:
                        return BoundedCommand([sys.executable, '-c', script], b'', request.environment,
                                              request.remaining(), request.stdout_limit, cwd=request.cwd)
                    return original(request)
                with patch.object(CompilerRequest, 'start', delayed), session.start_build(CHANGED) as pipeline:
                    deadline = time.monotonic() + 10
                    while not marker.exists() and time.monotonic() < deadline:
                        self.assertFalse(pipeline.poll())
                        time.sleep(0.001)
                    self.assertTrue(marker.exists())
                    self.assertEqual(target, pipeline.stage)
                    child = pipeline._operation.process
                    self.assertTrue(session._busy)
                    with self.assertRaises(ValueError):
                        session.start_build(SOURCE)
                    with self.assertRaises(ValueError):
                        session.close()
                    observed = Path(temporary) / 'current-source'
                    observed.write_text('superseding source')
                    self.assertEqual('superseding source', observed.read_text())
                    pipeline.close()
                    self.assertIsNotNone(child.returncode)
                    with self.assertRaises(ValueError):
                        pipeline.poll()
                self.assertFalse(session._busy)
                self.assertIs(previous_cache, session._cache)
                self.assertIs(previous_probe, session._probe)
                self.assertEqual((0, b'', b''), execute(successful.executable))
                self.assertEqual(1, len(list(session._root.iterdir())))
                with session.start_build(SOURCE) as repaired:
                    result = finish(repaired)
                self.assertEqual([], result.receipt['compiled'])
                self.assertEqual(3, len(result.receipt['reused']))

    def test_command_failure_at_each_stage_keeps_previous_cache(self):
        original = CompilerRequest.start
        with UnitBuildSession(stable_toolchain=True) as session:
            successful = session.build(SOURCE)
            for target in ('prepare', 'compile', 'link'):
                def failing(request):
                    if request.stage == target:
                        return BoundedCommand([sys.executable, '-c', 'import sys; sys.exit(3)'], b'', request.environment,
                                              request.remaining(), request.stdout_limit, cwd=request.cwd)
                    return original(request)
                with self.subTest(stage=target), patch.object(CompilerRequest, 'start', failing):
                    with session.start_build(CHANGED) as pipeline, self.assertRaises(CompileError) as caught:
                        finish(pipeline)
                    self.assertEqual('E0402', caught.exception.code)
                self.assertFalse(session._busy)
                self.assertEqual((0, b'', b''), execute(successful.executable))
                self.assertEqual(1, len(list(session._root.iterdir())))
            self.assertEqual([], session.build(SOURCE).receipt['compiled'])

    def test_invalid_source_and_compiler_drift_reject_before_process_creation(self):
        with UnitBuildSession(stable_toolchain=True) as session, \
                patch('talven.c_command.subprocess.Popen', side_effect=AssertionError('no invalid-source tools')):
            with self.assertRaises(CompileError) as caught:
                session.start_build(SOURCE.replace('return 70003;', 'return false;'))
            self.assertEqual('E0201', caught.exception.code)
            self.assertFalse(session._busy)
            with patch('talven.unit_build.compiler_hash', return_value='changed'), self.assertRaises(CompileError) as caught:
                session.start_build(SOURCE)
            self.assertEqual('E0501', caught.exception.code)
            self.assertFalse(session._busy)

    def test_request_queue_delay_uses_remaining_deadline_and_snapshot_is_immutable(self):
        environment = {'SYNTHETIC': 'old'}
        argv = [sys.executable, '-c', 'pass']
        request = CompilerRequest('prepare', argv, bytearray(b'input'), environment, 0.01, 10, os.getcwd())
        argv.append('changed')
        environment['SYNTHETIC'] = 'changed'
        self.assertEqual('old', request.environment['SYNTHETIC'])
        self.assertEqual(3, len(request.command))
        with self.assertRaises(TypeError):
            request.environment['SYNTHETIC'] = 'forged'
        time.sleep(0.02)
        def steps():
            yield request
        with patch('talven.c_command.subprocess.Popen', side_effect=AssertionError('no expired requests')):
            with self.assertRaises(CompileError):
                BuildPipeline(steps())

    def test_pipeline_interruption_closes_command_and_unwinds_candidate(self):
        with UnitBuildSession(stable_toolchain=True) as session:
            successful = session.build(SOURCE)
            with session.start_build(CHANGED) as pipeline:
                process = pipeline._operation.process
                with patch.object(pipeline._operation, 'poll', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                    pipeline.poll()
            self.assertIsNotNone(process.returncode)
            self.assertFalse(session._busy)
            self.assertEqual((0, b'', b''), execute(successful.executable))
            self.assertEqual(1, len(list(session._root.iterdir())))

    def test_invalid_stage_or_yield_and_runner_stopiteration_do_not_report_success(self):
        with self.assertRaises(ValueError):
            CompilerRequest('unknown', [], b'', {}, 1, 10, os.getcwd())
        cleaned = []
        def invalid():
            try:
                yield 'not a compiler request'
            finally:
                cleaned.append(True)
        with self.assertRaises(ValueError):
            BuildPipeline(invalid())
        self.assertEqual([True], cleaned)
        def steps():
            yield CompilerRequest('prepare', [sys.executable, '-c', 'pass'], b'', {}, 1, 10, os.getcwd())
        def bad_runner(*_, **__):
            raise StopIteration('not pipeline completion')
        with self.assertRaises(StopIteration):
            run_steps(steps(), {'prepare': bad_runner})
