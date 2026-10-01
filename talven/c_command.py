"""Pollable bounded trusted compiler commands; no watcher or program publication."""

import os
import selectors
import subprocess
import tempfile
import time

from .frontend import CompileError, Span

MAX_COMMAND_BYTES = 16 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
POLL_BYTES = 64 * 1024


def failure(message):
    return CompileError('E0402', message, Span(0, 0))


class BoundedCommand:
    def __init__(self, command, data, environment, timeout, stdout_limit=MAX_COMMAND_BYTES, *, cwd=None):
        if os.name != 'posix' or not hasattr(os, 'waitid'):
            raise CompileError('E0901', 'C unit preparation requires POSIX process groups and waitid', Span(0, 0))
        if type(timeout) not in (int, float) or not 0 < timeout <= 60:
            raise ValueError('Compiler command timeout must be finite and within (0, 60]')
        if type(stdout_limit) is not int or not 0 <= stdout_limit <= MAX_COMMAND_BYTES:
            raise ValueError('Compiler command stdout limit must be 0..16 MiB')
        if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_COMMAND_BYTES:
            raise failure('C unit preparation input exceeded its limit')
        if not isinstance(command, (list, tuple)) or not command or not all(isinstance(value, str) for value in command):
            raise ValueError('Compiler command requires a nonempty argument list')
        self.timeout, self.stdout_limit = timeout, stdout_limit
        self.started = time.monotonic()
        self.process, self.input_file, self.selector = None, None, None
        self.output = {'stdout': bytearray(), 'stderr': bytearray()}
        self._closed, self._result = False, None
        try:
            self.input_file = tempfile.TemporaryFile()
            self.input_file.write(data)
            self.input_file.seek(0)
            self.selector = selectors.DefaultSelector()
            self.process = subprocess.Popen(command, stdin=self.input_file, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            env=dict(environment), cwd=cwd, start_new_session=True)
            for label, stream in (('stdout', self.process.stdout), ('stderr', self.process.stderr)):
                os.set_blocking(stream.fileno(), False)
                self.selector.register(stream, selectors.EVENT_READ, label)
        except BaseException as error:
            self.close()
            if isinstance(error, OSError):
                raise CompileError('E0901', str(error), Span(0, 0)) from None
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        from .dev import stop_group
        try:
            if self.process is not None:
                stop_group(self.process, 0.1)
        finally:
            if self.selector is not None:
                self.selector.close()
            if self.input_file is not None:
                self.input_file.close()
            if self.process is not None:
                self.process.stdout.close()
                self.process.stderr.close()

    def poll(self, *, wait=0):
        """Return bytes after successful EOF/exit, or None while pending.

        Read at most 64 KiB per call; default readiness polling does not wait.
        Completion/failure closes resources and cleans up the owned child group.
        """
        if type(wait) not in (int, float) or not 0 <= wait <= 0.01:
            raise ValueError('Compiler poll wait must be 0..0.01 seconds')
        if self._result is not None:
            return self._result
        if self._closed:
            raise ValueError('Compiler command is closed')
        from .dev import exit_status
        try:
            if time.monotonic() - self.started >= self.timeout:
                raise failure('C unit preparation command timed out')
            budget = POLL_BYTES
            for key, _ in self.selector.select(wait):
                if budget == 0:
                    break
                try:
                    chunk = os.read(key.fileobj.fileno(), min(32768, budget))
                except BlockingIOError:
                    continue
                if not chunk:
                    self.selector.unregister(key.fileobj)
                else:
                    budget -= len(chunk)
                    self.output[key.data].extend(chunk)
                    limit = self.stdout_limit if key.data == 'stdout' else MAX_STDERR_BYTES
                    if len(self.output[key.data]) > limit:
                        raise failure('C unit preparation command output exceeded its limit')
            status = exit_status(self.process)
            if self.selector.get_map() or status is None:
                return None
            if status != 0:
                detail = bytes(self.output['stderr'] or self.output['stdout'])[:MAX_STDERR_BYTES].decode('utf-8', errors='replace').strip()
                raise failure('C unit preparation command failed: ' + detail)
            self._result = bytes(self.output['stdout'])
            self.close()
            return self._result
        except BaseException as error:
            self.close()
            if isinstance(error, OSError):
                raise CompileError('E0901', str(error), Span(0, 0)) from None
            raise


def run_bounded(command, data, environment, timeout, stdout_limit=MAX_COMMAND_BYTES, *, cwd=None):
    with BoundedCommand(command, data, environment, timeout, stdout_limit, cwd=cwd) as operation:
        while True:
            result = operation.poll(wait=0.01)
            if result is not None:
                return result
