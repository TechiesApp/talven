import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from talven.c_command import BoundedCommand, POLL_BYTES, run_bounded
from talven.dev import exit_status
from talven.frontend import CompileError


def command(script):
    return [sys.executable, '-c', script]


def complete(operation):
    while True:
        before = sum(map(len, operation.output.values()))
        result = operation.poll(wait=0.01)
        after = sum(map(len, operation.output.values()))
        if after - before > POLL_BYTES:
            raise AssertionError('compiler polling exceeded its per-call read budget')
        if result is not None:
            return result


class CompilerCommandTests(unittest.TestCase):
    def assert_not_executing(self, pid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, timeout=2).stdout.decode().strip()
            if not status or status.startswith('Z'):
                return
            time.sleep(0.01)
        self.fail(f'process {pid} is still executing')

    def test_poll_allows_observation_between_steps_and_captures_input_environment_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            gate = directory / 'gate'
            script = (f'import json, os, pathlib, sys, time\n'
                      f'while not pathlib.Path({str(gate)!r}).exists(): time.sleep(.01)\n'
                      'print(json.dumps([os.getcwd(), os.environ["TEST_COMMAND_VALUE"], sys.stdin.buffer.read().hex()]))\n')
            with BoundedCommand(command(script), b'input\0', {**os.environ, 'TEST_COMMAND_VALUE': 'synthetic'}, 5, cwd=temporary) as operation:
                self.assertIsNone(operation.poll())
                self.assertIsNone(exit_status(operation.process))
                observed = directory / 'source.tal'
                observed.write_text('current bytes')
                self.assertEqual('current bytes', observed.read_text())
                self.assertIsNone(operation.poll())
                gate.write_text('ready')
                result = complete(operation)
                self.assertEqual([os.path.realpath(temporary), 'synthetic', b'input\0'.hex()], json.loads(result))
                self.assertEqual(result, operation.poll())
                self.assertTrue(operation.input_file.closed and operation.process.stdout.closed and operation.process.stderr.closed)
                self.assertEqual(0, operation.process.returncode)

    def test_multiple_pipe_buffers_are_drained_under_per_poll_budget_and_empty_success_is_distinct(self):
        data = bytes(range(256)) * 1000
        with BoundedCommand(command('import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'),
                            data, dict(os.environ), 5) as operation:
            self.assertEqual(data, complete(operation))
        self.assertEqual(b'', run_bounded(command('pass'), b'', dict(os.environ), 5, 0))

    def test_output_failure_timeout_and_nonzero_exit_close_owned_resources(self):
        for script, timeout, limit in [('print("x" * 1000)', 5, 10),
                                       ('import sys; sys.stderr.write("x" * 70000)', 5, 100),
                                       ('import time; time.sleep(30)', 0.05, 100),
                                       ('import sys; sys.stderr.write("failed"); sys.exit(3)', 5, 100)]:
            with self.subTest(script=script):
                operation = BoundedCommand(command(script), b'', dict(os.environ), timeout, limit)
                with self.assertRaises(CompileError) as caught:
                    complete(operation)
                self.assertEqual('E0402', caught.exception.code)
                self.assertTrue(operation.input_file.closed and operation.process.stdout.closed and operation.process.stderr.closed)
                self.assertIsNotNone(operation.process.returncode)
                with self.assertRaises(ValueError):
                    operation.poll()

    def test_explicit_cancellation_stops_term_resistant_leader_and_descendant(self):
        with tempfile.TemporaryDirectory() as temporary:
            pidfile = Path(temporary) / 'child-pid'
            child = ('import os,pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                     f'pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(30)')
            script = ('import signal,subprocess,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                      f'subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(30)')
            with BoundedCommand(command(script), b'', dict(os.environ), 10) as operation:
                deadline = time.monotonic() + 5
                while not pidfile.exists() and time.monotonic() < deadline:
                    self.assertIsNone(operation.poll(wait=0.01))
                child_pid = int(pidfile.read_text())
                leader = operation.process.pid
                operation.close()
                self.assert_not_executing(leader)
                self.assert_not_executing(child_pid)
                self.assertEqual(-signal.SIGKILL, operation.process.returncode)
                operation.close()

    def test_leader_exit_keeps_pid_reserved_until_descendant_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            pidfile = Path(temporary) / 'child-pid'
            child = ('import os,pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                     f'pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(30)')
            script = ('import pathlib,subprocess,sys,time\n'
                      f'subprocess.Popen([sys.executable,"-c",{child!r}])\n'
                      f'while not pathlib.Path({str(pidfile)!r}).exists(): time.sleep(.01)\n')
            with BoundedCommand(command(script), b'', dict(os.environ), 10) as operation:
                deadline = time.monotonic() + 5
                while exit_status(operation.process) is None and time.monotonic() < deadline:
                    self.assertIsNone(operation.poll(wait=0.01))
                self.assertEqual(0, exit_status(operation.process))
                self.assertIsNone(operation.process.returncode)
                self.assertIsNotNone(os.waitid(os.P_PID, operation.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT))
                self.assertIsNone(operation.poll())  # Descendant still owns the output pipes.
                child_pid = int(pidfile.read_text())
                operation.close()
                self.assertEqual(0, operation.process.returncode)
                self.assert_not_executing(child_pid)

    def test_usage_and_launch_failures_do_not_leave_live_resources(self):
        for timeout in (0, 61, float('nan'), float('inf'), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                BoundedCommand(command('pass'), b'', dict(os.environ), timeout)
        for limit in (-1, 16 * 1024 * 1024 + 1, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                BoundedCommand(command('pass'), b'', dict(os.environ), 5, limit)
        for invalid in ('cc -E', [], [None]):
            with self.subTest(command=invalid), self.assertRaises(ValueError):
                BoundedCommand(invalid, b'', dict(os.environ), 5)
        with self.assertRaises(CompileError) as caught:
            BoundedCommand(['/no/such/compiler'], b'', dict(os.environ), 5)
        self.assertEqual('E0901', caught.exception.code)
        with BoundedCommand(command('pass'), b'', dict(os.environ), 5) as operation:
            for wait in (-1, 0.02, float('nan'), True):
                with self.subTest(wait=wait), self.assertRaises(ValueError):
                    operation.poll(wait=wait)
            complete(operation)
