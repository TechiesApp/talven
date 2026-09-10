"""Single-file full builds and process restarts. No persistent compiler or hot reload."""

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

from .backend import emit_c
from .context import compiler_hash
from .frontend import CompileError, MAX_SOURCE_BYTES, Span, analyze
from .native import compiler_command

MAX_BUILD_OUTPUT = 64 * 1024


def interval(value):
    number = float(value)
    if not math.isfinite(number) or not 0.01 <= number <= 60:
        raise argparse.ArgumentTypeError("duration must be finite and between 0.01 and 60 seconds")
    return number


@dataclass(frozen=True)
class Snapshot:
    data: bytes = b""
    code: str | None = None
    error: str | None = None

    @property
    def digest(self):
        return None if self.error else hashlib.sha256(self.data).hexdigest()


def read_source(path):
    try:
        # Nonblocking open avoids hanging on a source path replaced with a FIFO.
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return Snapshot(code="E0901", error="Development source must be a regular file")
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            return Snapshot(code="E0005", error="Source exceeds the 256 KiB prototype limit")
        return Snapshot(data=data)
    except OSError as error:
        return Snapshot(code="E0901", error=str(error))


def stop_group(process, timeout):
    """Reap our child and signal its group, even if the group leader exited."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # Descendants may retain descriptors after their parent exits.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


@dataclass
class Job:
    revision: int
    snapshot: Snapshot
    observed: float
    directory: Path
    process: subprocess.Popen | None
    started: float
    output: bytearray


class Session:
    def __init__(self, args, directory, events):
        self.args, self.directory, self.events = args, directory, events
        self.revision = 0
        self.snapshot = None
        self.observed = 0.0
        self.attempted = 0
        self.build = None
        self.program = None
        self.cancelled = 0

    def event(self, name, job=None, **fields):
        row = {"schema": "talven.dev.v1", "event": name}
        if job:
            row.update(revision=job.revision, source_hash=job.snapshot.digest,
                       observed_to_event_seconds=time.monotonic() - job.observed)
        else:
            row.update(revision=self.revision, source_hash=self.snapshot.digest if self.snapshot else None)
        row.update(fields)
        if self.events:
            self.events.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")
            self.events.flush()
        diagnostic = fields.get("diagnostic")
        description = ""
        if diagnostic:
            start = diagnostic["range"]["start"]
            description = (f"{self.args.source}:{start['line'] + 1}:{start['character'] + 1}: "
                           f"{diagnostic['code']}: {diagnostic['message']}")
        print(f"talven dev: {name} revision {row['revision']} {description}".rstrip(), file=sys.stderr, flush=True)

    def observe(self):
        snapshot = read_source(self.args.source)
        if snapshot != self.snapshot:
            self.snapshot = snapshot
            self.revision += 1
            self.observed = time.monotonic()
            self.event("observed")

    def reject(self, job, error, source=""):
        self.event("rejected", job, diagnostic=error.diagnostic(source))

    def discard(self, job):
        stop_group(job.process, self.args.stop_timeout)
        if job.process.stdout:
            job.process.stdout.close()
        shutil.rmtree(job.directory)

    def stop_program(self, reason):
        if self.program:
            job, self.program = self.program, None
            self.discard(job)
            self.event("stopped", job, reason=reason, returncode=job.process.returncode)

    def begin_build(self):
        self.attempted = self.revision
        # A job identity exists before frontend checking or process launch.
        job = Job(self.revision, self.snapshot, self.observed,
                  self.directory / str(self.revision), None, time.monotonic(), bytearray())
        source = ""
        try:
            if job.snapshot.error:
                raise CompileError(job.snapshot.code, job.snapshot.error, Span(0, 0))
            source = job.snapshot.data.decode("utf-8")
            generated = emit_c(analyze(source), console=self.args.console)
            self.observe()
            if self.cancelled or job.revision != self.revision:
                self.event("superseded", job)
                return
            job.directory.mkdir()
            cfile, executable = job.directory / "program.c", job.directory / "program"
            cfile.write_text(generated, encoding="utf-8")
            job.process = subprocess.Popen(compiler_command(self.args.cc, cfile, executable),
                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, start_new_session=True)
            self.build = job
            os.set_blocking(job.process.stdout.fileno(), False)
            self.event("building", job, build_mode="full", pid=job.process.pid)
        except (OSError, UnicodeError) as error:
            if job.process is not None:
                self.build = None
                self.discard(job)
            else:
                shutil.rmtree(job.directory, ignore_errors=True)
            self.reject(job, CompileError("E0901", str(error), Span(0, 0)), source)
        except CompileError as error:
            self.reject(job, error, source)

    def check_build(self):
        job = self.build
        if job is None:
            return
        if job.revision != self.revision:
            self.build = None
            self.discard(job)
            self.event("superseded", job)
            return
        # Read at most one budget per tick so a noisy compiler cannot starve watching.
        try:
            chunk = os.read(job.process.stdout.fileno(), MAX_BUILD_OUTPUT + 1 - len(job.output))
            job.output.extend(chunk)
        except BlockingIOError:
            chunk = None
        failure = None
        if len(job.output) > MAX_BUILD_OUTPUT:
            failure = "C compiler exceeded the 64 KiB output limit"
        elif time.monotonic() - job.started > self.args.build_timeout:
            failure = "Full build timed out"
        status = job.process.poll()
        # Drain until EOF: a process can exit with more than one pipe buffer pending.
        if not failure and (status is None or chunk):
            return
        if failure or status:
            self.build = None
            message = failure or ("C compiler failed: " + job.output.decode("utf-8", errors="replace").strip())
            self.discard(job)
            self.reject(job, CompileError("E0402", message, Span(0, 0)))
            return
        self.build = None
        stop_group(job.process, self.args.stop_timeout)
        job.process.stdout.close()
        self.observe()
        if self.cancelled or job.revision != self.revision:
            shutil.rmtree(job.directory)
            self.event("superseded", job)
            return
        self.stop_program("replacement")
        # A save may arrive during graceful shutdown of the previous program.
        self.observe()
        if self.cancelled or job.revision != self.revision:
            shutil.rmtree(job.directory)
            self.event("superseded", job)
            return
        try:
            job.process = subprocess.Popen([str(job.directory / "program")],
                                           stdin=subprocess.DEVNULL, start_new_session=True)
            self.program = job
            self.event("started", job, pid=job.process.pid, build_mode="full")
        except OSError as error:
            shutil.rmtree(job.directory)
            self.reject(job, CompileError("E0901", f"Program launch failed: {error}", Span(0, 0)))

    def run(self):
        def cancel(signum, frame):
            self.cancelled = signum

        previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            self.event("session_started", build_mode="full", source=str(self.args.source),
                       compiler_hash=compiler_hash(), cc=self.args.cc,
                       poll_interval_seconds=self.args.poll_interval, debounce_seconds=self.args.debounce,
                       build_timeout_seconds=self.args.build_timeout, stop_timeout_seconds=self.args.stop_timeout)
            while not self.cancelled:
                self.observe()
                if self.program and self.program.process.poll() is not None:
                    job, self.program = self.program, None
                    self.discard(job)
                    self.event("exited", job, returncode=job.process.returncode)
                self.check_build()
                if (not self.cancelled and self.build is None and self.attempted != self.revision
                        and time.monotonic() - self.observed >= self.args.debounce):
                    self.begin_build()
                time.sleep(self.args.poll_interval)
            return 128 + self.cancelled
        finally:
            try:
                try:
                    if self.build:
                        self.discard(self.build)
                        self.build = None
                finally:
                    self.stop_program("session shutdown")
                self.event("session_stopped", signal=self.cancelled)
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)


def run_dev(args):
    if os.name != "posix":
        print("talven dev: requires POSIX process groups", file=sys.stderr)
        return 1
    try:
        if args.events and args.events.resolve() == args.source.resolve():
            raise OSError("Event receipts must use a different path from the watched source")
        # Exclusive creation cannot truncate an existing source or evidence file.
        events = args.events.open("x", encoding="utf-8") if args.events else None
        try:
            with tempfile.TemporaryDirectory(prefix="talven-dev-") as directory:
                return Session(args, Path(directory), events).run()
        finally:
            if events:
                events.close()
    except OSError as error:
        print(f"talven dev: {error}", file=sys.stderr)
        return 1
