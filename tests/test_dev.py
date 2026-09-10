"""Observable development sessions; compiler/process doubles are test-only."""

import hashlib
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


@unittest.skipUnless(os.name == "posix" and shutil.which("cc"), "dev tests require POSIX and cc")
class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "hello.tal"
        self.events = self.directory / "events.jsonl"
        self.stdout = (self.directory / "stdout").open("w+b")
        self.stderr = (self.directory / "stderr").open("w+b")
        self.addCleanup(self.stdout.close)
        self.addCleanup(self.stderr.close)
        self.write("first")

    def save(self, data):
        candidate = self.directory / "saved.tal"
        candidate.write_bytes(data)
        candidate.replace(self.source)

    def write(self, message):
        self.save(f'fn main() -> i32 {{ return print("{message}\\n"); }}\n'.encode())

    def start(self, *args):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "talven", "dev", str(self.source), "--console",
             "--events", str(self.events), "--poll-interval", "0.01", "--debounce", "0.04",
             "--stop-timeout", "0.1", *map(str, args)],
            stdout=self.stdout, stderr=self.stderr, stdin=subprocess.DEVNULL)
        self.addCleanup(self.stop)
        return self.wait_event("observed", 1)

    def stop(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
                self.fail("development session did not shut down")

    def records(self):
        if not self.events.exists():
            return []
        # Ignore a last line still being written by the other process.
        return [json.loads(line) for line in self.events.read_text().splitlines(keepends=True)
                if line.endswith("\n")]

    def wait_event(self, event, revision=None):
        until = time.monotonic() + 10
        while time.monotonic() < until:
            for row in self.records():
                if row["event"] == event and (revision is None or row.get("revision") == revision):
                    return row
            if self.process.poll() is not None:
                break
            time.sleep(0.01)
        self.stderr.seek(0)
        self.fail(f"Missing {event} revision {revision}: {self.records()}\n{self.stderr.read()!r}")

    def wrapper(self, body):
        path = self.directory / "compiler with spaces"
        path.write_text(f"#!{sys.executable}\nimport os, pathlib, signal, subprocess, sys, time\n"
                        f"root = pathlib.Path({str(self.directory)!r})\n" + body)
        path.chmod(0o755)
        return path

    def test_native_greeting_rebuild_invalid_edit_repair_and_same_mtime(self):
        observed = self.start()
        first = self.wait_event("exited", 1)
        self.assertEqual(0, first["returncode"])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), observed["source_hash"])
        stamp = self.source.stat()
        # Same inode and byte count, without an intermediate truncation.
        with self.source.open("r+b") as stream:
            stream.write(self.source.read_bytes().replace(b"first", b"other"))
        os.utime(self.source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.wait_event("exited", 2)
        self.save(b"fn main() -> i32 { return false; }")
        rejected = self.wait_event("rejected", 3)
        self.assertEqual("E0201", rejected["diagnostic"]["code"])
        self.write("fixed")
        self.wait_event("exited", 4)
        self.stop()
        self.stdout.seek(0)
        self.assertEqual(b"first\nother\nfixed\n", self.stdout.read())
        self.assertEqual(143, self.process.returncode)
        for row in self.records():
            self.assertEqual("talven.dev.v1", row["schema"])
        started = [row for row in self.records() if row["event"] == "started"]
        self.assertEqual([1, 2, 4], [row["revision"] for row in started])
        self.assertTrue(all(row["observed_to_event_seconds"] >= 0.04 for row in started))

    def test_missing_invalid_utf8_oversize_and_nonregular_source_recover(self):
        self.source.unlink()
        self.start()
        self.wait_event("rejected", 1)
        self.save(b"\xff")
        self.wait_event("rejected", 2)
        self.save(b" " * (256 * 1024 + 1))
        self.assertEqual("E0005", self.wait_event("rejected", 3)["diagnostic"]["code"])
        fifo = self.directory / "source.fifo"
        os.mkfifo(fifo)
        fifo.replace(self.source)
        self.wait_event("rejected", 4)
        self.write("recovered")
        self.wait_event("exited", 5)

    def test_save_burst_is_coalesced_and_unchanged_bytes_do_not_restart(self):
        self.start("--debounce", "0.4")
        self.write("second")
        self.wait_event("observed", 2)
        self.write("latest")
        self.wait_event("exited", 3)
        self.write("latest")
        # This is a negative observation window, not a build-completion guess.
        time.sleep(0.5)
        self.stop()
        self.assertEqual([3], [r["revision"] for r in self.records() if r["event"] == "started"])
        self.stdout.seek(0)
        self.assertEqual(b"latest\n", self.stdout.read())

    def test_edit_during_slow_compile_discards_candidate(self):
        cc = self.wrapper("(root / 'cc-pid').write_text(str(os.getpid()))\n"
                          "while not (root / 'release').exists(): time.sleep(.01)\n"
                          "os.execvp('cc', ['cc', *sys.argv[1:]])\n")
        self.start("--cc", cc)
        self.wait_event("building", 1)
        self.write("fresh")
        self.wait_event("superseded", 1)
        (self.directory / "release").touch()
        self.wait_event("exited", 2)
        self.stop()
        self.stdout.seek(0)
        self.assertEqual(b"fresh\n", self.stdout.read())

    def test_compiler_timeout_is_reported(self):
        cc = self.wrapper("time.sleep(30)\n")
        self.start("--cc", cc, "--build-timeout", "0.3")
        self.assertIn("timed out", self.wait_event("rejected", 1)["diagnostic"]["message"])

    def test_compiler_output_limit_is_reported(self):
        cc = self.wrapper("os.write(2, b'x' * 200000)\ntime.sleep(30)\n")
        self.start("--cc", cc, "--build-timeout", "5")
        self.assertIn("output limit", self.wait_event("rejected", 1)["diagnostic"]["message"])

    def test_failed_build_keeps_process_then_stops_before_replacement(self):
        # A process double exercises lifetimes which current Talven I/O cannot express.
        program = (f"#!{sys.executable}\nimport os, pathlib, signal, time\n"
                   f"root = pathlib.Path({str(self.directory)!r})\n"
                   "(root / ('alive-' + str(os.getpid()))).touch()\n"
                   "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                   "while True: time.sleep(.01)\n")
        cc = self.wrapper("if (root / 'fail').exists(): sys.exit(9)\n"
                          "out = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
                          f"out.write_text({program!r})\nout.chmod(0o755)\n")
        self.start("--cc", cc)
        first = self.wait_event("started", 1)
        (self.directory / "fail").touch()
        self.write("badbuild")
        self.wait_event("rejected", 2)
        os.kill(first["pid"], 0)
        (self.directory / "fail").unlink()
        self.write("new")
        second = self.wait_event("started", 3)
        with self.assertRaises(ProcessLookupError):
            os.kill(first["pid"], 0)
        records = self.records()
        self.assertLess(next(i for i, r in enumerate(records) if r["event"] == "stopped"),
                        next(i for i, r in enumerate(records) if r["event"] == "started" and r["revision"] == 3))
        self.stop()
        with self.assertRaises(ProcessLookupError):
            os.kill(second["pid"], 0)

    def test_interrupt_during_compilation_cleans_compiler_group(self):
        cc = self.wrapper("(root / 'compiler-pid').write_text(str(os.getpid()))\n"
                          "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                          "while True: time.sleep(.01)\n")
        self.start("--cc", cc)
        self.wait_event("building", 1)
        until = time.monotonic() + 5
        pidfile = self.directory / "compiler-pid"
        while not pidfile.exists() and time.monotonic() < until:
            time.sleep(.01)
        pid = int(pidfile.read_text())
        self.process.send_signal(signal.SIGINT)
        self.process.wait(timeout=5)
        self.assertEqual(130, self.process.returncode)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def assert_not_executing(self, pid):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            try:
                os.kill(pid, 0)
                if sys.platform.startswith("linux"):
                    # A grandchild's reaping belongs to its adoptive parent.
                    state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
                    if state == "Z":
                        return
            except (ProcessLookupError, FileNotFoundError):
                return
            time.sleep(.01)
        self.fail(f"process {pid} is still executing")

    def test_compiler_descendant_is_stopped_on_interrupt(self):
        child = ("import os,pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                 f"pathlib.Path({str(self.directory / 'child-pid')!r}).write_text(str(os.getpid())); "
                 "time.sleep(30)")
        cc = self.wrapper("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                          f"child = subprocess.Popen([sys.executable, '-c', {child!r}])\n"
                          "time.sleep(30)\n")
        self.start("--cc", cc)
        build = self.wait_event("building", 1)
        until = time.monotonic() + 5
        pidfile = self.directory / "child-pid"
        while not pidfile.exists() and time.monotonic() < until:
            time.sleep(.01)
        child_pid = int(pidfile.read_text())
        self.stop()
        self.assert_not_executing(build["pid"])
        self.assert_not_executing(child_pid)

    def test_program_descendant_is_stopped_after_leader_exits(self):
        child = ("import os,pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                 f"pathlib.Path({str(self.directory / 'child-pid')!r}).write_text(str(os.getpid())); "
                 "time.sleep(30)")
        program = (f"#!{sys.executable}\nimport pathlib, subprocess, sys, time\n"
                   f"p = subprocess.Popen([sys.executable, '-c', {child!r}])\n"
                   f"while not pathlib.Path({str(self.directory / 'child-pid')!r}).exists(): time.sleep(.01)\n")
        cc = self.wrapper("out = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
                          f"out.write_text({program!r})\nout.chmod(0o755)\n")
        self.start("--cc", cc)
        self.assertEqual(0, self.wait_event("exited", 1)["returncode"])
        self.assert_not_executing(int((self.directory / "child-pid").read_text()))

    def test_save_during_shutdown_does_not_launch_superseded_program(self):
        program = (f"#!{sys.executable}\nimport pathlib, signal, time\n"
                   f"root = pathlib.Path({str(self.directory)!r})\n"
                   "def stop(sig, frame):\n"
                   "    (root / 'stopping').touch()\n"
                   "signal.signal(signal.SIGTERM, stop)\n"
                   "(root / 'ready').touch()\n"
                   "while True: time.sleep(.01)\n")
        cc = self.wrapper("out = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
                          f"out.write_text({program!r})\nout.chmod(0o755)\n")
        self.start("--cc", cc, "--stop-timeout", "0.6")
        self.wait_event("started", 1)
        until = time.monotonic() + 5
        while not (self.directory / "ready").exists() and time.monotonic() < until:
            time.sleep(.01)
        self.assertTrue((self.directory / "ready").exists())
        self.write("second")
        until = time.monotonic() + 5
        while not (self.directory / "stopping").exists() and time.monotonic() < until:
            time.sleep(.01)
        self.assertTrue((self.directory / "stopping").exists())
        self.write("latest")
        self.wait_event("started", 3)
        self.assertFalse(any(r["event"] == "started" and r["revision"] == 2 for r in self.records()))

    def test_missing_compiler_launch_failure_and_program_exit_are_distinct(self):
        cc = self.directory / "late-compiler"
        self.start("--cc", cc)
        self.assertEqual("E0901", self.wait_event("rejected", 1)["diagnostic"]["code"])
        wrapper = self.wrapper("if (root / 'launch').exists():\n"
                               "    out = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
                               "    out.write_text('not executable')\n"
                               "else: os.execvp('cc', ['cc', *sys.argv[1:]])\n")
        wrapper.rename(cc)
        (self.directory / "launch").touch()
        self.write("unlaunchable")
        self.assertIn("Program launch failed", self.wait_event("rejected", 2)["diagnostic"]["message"])
        (self.directory / "launch").unlink()
        self.save(b"fn main() -> i32 { return 7; }")
        self.assertEqual(7, self.wait_event("exited", 3)["returncode"])
        self.stop()
        self.assertEqual([3], [r["revision"] for r in self.records() if r["event"] == "started"])

    def test_event_path_cannot_create_missing_source(self):
        self.source.unlink()
        result = subprocess.run([sys.executable, "-m", "talven", "dev", str(self.source),
                                 "--events", str(self.source)], capture_output=True, timeout=5)
        self.assertEqual(1, result.returncode)
        self.assertFalse(self.source.exists())

    def test_events_never_overwrite_source_and_intervals_are_finite(self):
        before = self.source.read_bytes()
        for args in (("--events", str(self.source)), ("--poll-interval", "nan"),
                     ("--build-timeout", "inf"), ("--debounce", "-1")):
            result = subprocess.run([sys.executable, "-m", "talven", "dev", str(self.source), *args],
                                    capture_output=True, timeout=5)
            self.assertNotEqual(0, result.returncode)
            self.assertNotIn(b"Traceback", result.stderr)
        self.assertEqual(before, self.source.read_bytes())
