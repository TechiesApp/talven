import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SOURCE = ('fn message() -> str { return "first\\n"; } '
          'fn relay(s: str) -> str { return s; } '
          'fn main() -> i32 { return print(relay(message())); }\n')


class NativeWatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source, self.events = self.directory / 'source.tal', self.directory / 'events.jsonl'
        self.stdout = (self.directory / 'stdout').open('w+b')
        self.stderr = (self.directory / 'stderr').open('w+b')
        self.addCleanup(self.stdout.close)
        self.addCleanup(self.stderr.close)
        self.save(SOURCE)
        self.process = None

    def save(self, source):
        replacement = self.directory / 'save.tal'
        replacement.write_text(source)
        replacement.replace(self.source)

    def start(self, *extra):
        self.process = subprocess.Popen([sys.executable, '-m', 'talven', 'dev', str(self.source), '--console',
                                         '--incremental-build', '--stable-toolchain', '--events', str(self.events),
                                         '--poll-interval', '0.01', '--debounce', '0.03', '--stop-timeout', '0.1',
                                         *map(str, extra)], stdin=subprocess.DEVNULL, stdout=self.stdout, stderr=self.stderr)
        self.addCleanup(self.stop)
        self.wait('observed', 1)

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            self.process.wait(timeout=10)

    def rows(self):
        if not self.events.exists():
            return []
        return [json.loads(line) for line in self.events.read_text().splitlines(keepends=True) if line.endswith('\n')]

    def wait(self, name, revision=None):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            for row in self.rows():
                if row['event'] == name and (revision is None or row['revision'] == revision):
                    return row
            if self.process.poll() is not None:
                break
            time.sleep(0.01)
        self.stderr.seek(0)
        self.fail(f'missing {name} revision {revision}: {self.rows()} {self.stderr.read()!r}')

    def wrapper(self, body):
        actual = str(Path(shutil.which('cc')).resolve())
        path = self.directory / 'compiler with spaces'
        path.write_text(f'#!{sys.executable}\nimport os,pathlib,signal,subprocess,sys,time\n'
                        f'root=pathlib.Path({str(self.directory)!r})\nactual={actual!r}\n' + body)
        path.chmod(0o700)
        return path

    def test_real_native_body_comment_contract_invalid_and_repair_revisions(self):
        self.start()
        self.wait('exited', 1)
        first = self.wait('compiled', 1)
        self.assertEqual(['fn:message', 'fn:relay', 'fn:main', 'entry'], first['compiled'])
        self.assertEqual([], first['reused'])
        self.assertFalse(first['driver_probe_reused'])
        self.assertEqual('units', self.wait('session_started')['build_mode'])
        body = SOURCE.replace('first', 'second')
        self.save(body)
        self.wait('exited', 2)
        second = self.wait('compiled', 2)
        self.assertEqual(['fn:message'], second['compiled'])
        self.assertEqual(['fn:relay', 'fn:main', 'entry'], second['reused'])
        self.assertTrue(second['driver_probe_reused'])
        self.save('// current 😀\n' + body)
        self.wait('exited', 3)
        self.assertEqual([], self.wait('compiled', 3)['compiled'])
        contract = body.replace('relay(s: str)', 'relay(text: str)').replace('return s;', 'return text;')
        self.save(contract)
        self.wait('exited', 4)
        self.assertEqual([], self.wait('compiled', 4)['reused'])
        self.save(contract.replace('return "second\\n";', 'return false;'))
        self.assertEqual('E0201', self.wait('rejected', 5)['diagnostic']['code'])
        self.save(contract)
        self.wait('exited', 6)
        self.assertEqual([], self.wait('compiled', 6)['compiled'])
        self.stop()
        self.assertEqual(143, self.process.returncode)
        self.stdout.seek(0)
        self.assertEqual(b'first\nsecond\nsecond\nsecond\nsecond\n', self.stdout.read())
        self.assertTrue(all(row['build_mode'] == 'units' for row in self.rows() if row['event'] == 'started'))
        self.assertTrue(any(row['event'] == 'compiler_step' and row['stage'] == 'link' for row in self.rows()))

    def test_superseded_preprocessing_is_cancelled_without_stale_restart(self):
        compiler = self.wrapper('if "-E" in sys.argv and (root/"delay").exists():\n'
                                ' signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                                ' (root/"pending").write_text(str(os.getpid()))\n'
                                ' while not (root/"release").exists(): time.sleep(.01)\n'
                                'os.execv(actual,[actual,*sys.argv[1:]])\n')
        self.start('--cc', compiler)
        self.wait('exited', 1)
        (self.directory / 'delay').write_text('delay')
        self.save(SOURCE.replace('first', 'stale'))
        self.wait('building', 2)
        deadline = time.monotonic() + 5
        while not (self.directory / 'pending').exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        pid = int((self.directory / 'pending').read_text())
        self.save(SOURCE.replace('first', 'current'))
        self.wait('superseded', 2)
        (self.directory / 'release').write_text('released')
        self.wait('exited', 3)
        self.assertFalse(any(row['event'] == 'started' and row['revision'] == 2 for row in self.rows()))
        self.assertEqual('units', self.wait('compiled', 3)['build_mode'])
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.stop()
        self.stdout.seek(0)
        self.assertEqual(b'first\ncurrent\n', self.stdout.read())

    def test_failed_native_link_preserves_last_successful_objects_for_repair(self):
        compiler = self.wrapper('if "--version" not in sys.argv and "-dumpmachine" not in sys.argv '
                                'and "-E" not in sys.argv and "-c" not in sys.argv and (root/"fail").exists():\n'
                                ' sys.stderr.write("test link failure"); sys.exit(3)\n'
                                'os.execv(actual,[actual,*sys.argv[1:]])\n')
        self.start('--cc', compiler)
        self.wait('exited', 1)
        (self.directory / 'fail').write_text('fail')
        self.save(SOURCE.replace('first', 'failed'))
        self.assertEqual('E0402', self.wait('rejected', 2)['diagnostic']['code'])
        (self.directory / 'fail').unlink()
        self.save(SOURCE)
        self.wait('exited', 3)
        repaired = self.wait('compiled', 3)
        self.assertEqual([], repaired['compiled'])
        self.assertEqual(4, len(repaired['reused']))
        self.stop()
        self.stdout.seek(0)
        self.assertEqual(b'first\nfirst\n', self.stdout.read())

    def test_timeout_and_shutdown_cancel_owned_pipeline(self):
        compiler = self.wrapper('if "-E" in sys.argv:\n'
                                ' signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                                ' (root/"pending").write_text(str(os.getpid())); time.sleep(30)\n'
                                'os.execv(actual,[actual,*sys.argv[1:]])\n')
        self.start('--cc', compiler, '--build-timeout', '0.5')
        self.assertEqual('E0402', self.wait('rejected', 1)['diagnostic']['code'])
        self.save(SOURCE.replace('first', 'second'))
        active = self.wait('building', 2)
        self.stop()
        with self.assertRaises(ProcessLookupError):
            os.kill(active['pid'], 0)
        self.assertFalse(any(row['event'] == 'started' for row in self.rows()))
        self.assertEqual(143, self.process.returncode)

    def test_cli_mode_requires_stable_toolchain_and_excludes_check_only_mode(self):
        for options in (['--incremental-build'], ['--stable-toolchain'],
                        ['--incremental-build', '--stable-toolchain', '--incremental-check']):
            with self.subTest(options=options):
                result = subprocess.run([sys.executable, '-m', 'talven', 'dev', str(self.source), *options],
                                        capture_output=True, timeout=5)
                self.assertEqual(2, result.returncode)
                self.assertFalse(self.events.exists())

    def lifecycle_compiler(self):
        # Process doubles exercise deployment lifetime, not native language semantics.
        program = ('import json,os,pathlib,signal,sys,time\n'
                   f'root=pathlib.Path({str(self.directory)!r})\n'
                   'number=NUMBER\n(root/f"run-{number}").write_text(str(os.getpid()))\n'
                   'def stop(signum,frame):\n'
                   ' (root/f"stopped-{number}").write_text(json.dumps(pathlib.Path(sys.argv[0]).exists()))\n'
                   ' replacement=root/"during-stop"\n'
                   ' if replacement.exists():\n'
                   '  saved=root/"stop-save.tal"; saved.write_bytes(replacement.read_bytes()); saved.replace(root/"source.tal"); replacement.unlink()\n'
                   ' time.sleep(.02); raise SystemExit(0)\n'
                   'signal.signal(signal.SIGTERM,stop)\n'
                   'while True: time.sleep(.01)\n')
        return self.wrapper('if "--version" in sys.argv or "-dumpmachine" in sys.argv or "-E" in sys.argv:\n'
                            ' os.execv(actual,[actual,*sys.argv[1:]])\n'
                            'out=pathlib.Path(sys.argv[sys.argv.index("-o")+1])\n'
                            'if "-c" in sys.argv: out.write_bytes(b"test-only object"); raise SystemExit(0)\n'
                            'counter=root/"links"\nnumber=int(counter.read_text())+1 if counter.exists() else 1\n'
                            'counter.write_text(str(number))\n'
                            f'out.write_text("#!"+sys.executable+"\\n"+{program!r}.replace("NUMBER",str(number)))\n'
                            'out.chmod(0o700)\n')

    def wait_file(self, name):
        path = self.directory / name
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(path.exists(), name)
        return path

    def test_live_old_program_survives_invalid_source_and_deployment_copy_survives_cache_replacement(self):
        compiler = self.lifecycle_compiler()
        self.start('--cc', compiler)
        first = self.wait('started', 1)
        self.wait_file('run-1')
        self.save(SOURCE.replace('return "first\\n";', 'return false;'))
        self.assertEqual('E0201', self.wait('rejected', 2)['diagnostic']['code'])
        os.kill(first['pid'], 0)
        self.save(SOURCE.replace('first', 'second'))
        self.wait('started', 3)
        self.wait_file('run-2')
        self.assertTrue(json.loads(self.wait_file('stopped-1').read_text()))
        with self.assertRaises(ProcessLookupError):
            os.kill(first['pid'], 0)
        self.stop()

    def test_save_during_old_program_shutdown_prevents_superseded_native_candidate_start(self):
        compiler = self.lifecycle_compiler()
        self.start('--cc', compiler)
        self.wait('started', 1)
        self.wait_file('run-1')
        (self.directory / 'during-stop').write_text(SOURCE.replace('first', 'third'))
        self.save(SOURCE.replace('first', 'second'))
        self.wait('superseded', 2)
        self.wait('started', 3)
        self.wait_file('run-3')
        self.assertFalse((self.directory / 'run-2').exists())
        self.assertFalse(any(row['event'] == 'started' and row['revision'] == 2 for row in self.rows()))
        self.assertTrue(json.loads(self.wait_file('stopped-1').read_text()))
        self.stop()
