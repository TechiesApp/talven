"""Owned sequential compiler requests with blocking and pollable drivers."""

from dataclasses import dataclass, field
import time
from types import MappingProxyType

from .c_command import BoundedCommand, failure


@dataclass(frozen=True)
class CompilerRequest:
    stage: str
    command: tuple
    data: bytes
    environment: object
    timeout: float
    stdout_limit: int
    cwd: str
    created_at: float = field(default_factory=time.monotonic, init=False)

    def __post_init__(self):
        if self.stage not in ('prepare', 'compile', 'link'):
            raise ValueError('Unknown compiler pipeline stage')
        if type(self.timeout) not in (int, float) or not 0 < self.timeout <= 60:
            raise ValueError('Compiler request timeout must be finite and within (0, 60]')
        object.__setattr__(self, 'command', tuple(self.command))
        object.__setattr__(self, 'data', bytes(self.data))
        object.__setattr__(self, 'environment', MappingProxyType(dict(self.environment)))

    def remaining(self):
        value = self.timeout - (time.monotonic() - self.created_at)
        if value <= 0:
            raise failure('Compiler pipeline request timed out before launch')
        return value

    def start(self):
        return BoundedCommand(self.command, self.data, self.environment, self.remaining(), self.stdout_limit, cwd=self.cwd)

    def run(self, runner):
        return runner(list(self.command), self.data, self.environment, self.remaining(), self.stdout_limit, cwd=self.cwd)


def run_steps(steps, runners):
    value = None
    try:
        while True:
            try:
                request = steps.send(value)
            except StopIteration as completed:
                return completed.value
            if not isinstance(request, CompilerRequest):
                raise ValueError('Compiler pipeline yielded an invalid request')
            value = request.run(runners[request.stage])
    finally:
        steps.close()


class BuildPipeline:
    def __init__(self, steps):
        self._steps, self._request, self._operation = steps, None, None
        self._done, self._closed, self.result = False, False, None
        try:
            self._advance(None)
        except BaseException:
            self.close()
            raise

    @property
    def stage(self):
        return self._request.stage if self._request is not None else None

    @property
    def pid(self):
        return self._operation.process.pid if self._operation is not None else None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._operation is not None:
                self._operation.close()
        finally:
            self._operation, self._request = None, None
            self._steps.close()

    def _advance(self, output):
        self._operation, self._request = None, None
        try:
            request = self._steps.send(output)
        except StopIteration as completed:
            self.result, self._done = completed.value, True
            return
        if not isinstance(request, CompilerRequest):
            raise ValueError('Compiler pipeline yielded an invalid request')
        self._request = request
        self._operation = request.start()

    def poll(self):
        if self._done:
            return True
        if self._closed:
            raise ValueError('Compiler pipeline is closed')
        try:
            output = self._operation.poll()
            if output is not None:
                self._advance(output)
            return self._done
        except BaseException:
            self.close()
            raise
