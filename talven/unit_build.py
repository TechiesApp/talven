"""Private last-successful object reuse under an explicit stable-toolchain contract.

This synchronous experimental API never watches, publishes to a user-selected
path or executes a program. It is not a cross-session or authenticated cache.
"""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time

from .context import compiler_hash, encode, source_hash
from .frontend import CompileError, Span
from .preprocessed_units import FLAGS, _prepare_c_units, executable_hash, failure, run_bounded

OBJECT_FLAGS = (*FLAGS, '-Werror', '-fno-lto')
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_OBJECT_BYTES = 64 * 1024 * 1024


def artifact_bytes(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise failure('Native unit artifact is not a regular file')
        data = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(data) > MAX_ARTIFACT_BYTES or not data:
        raise failure('Native unit artifact is empty or exceeds 16 MiB')
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class UnitBuild:
    executable: Path
    receipt: dict


class UnitBuildSession:
    def __init__(self, *, stable_toolchain, cc='cc', console=False, timeout=30):
        if stable_toolchain is not True:
            raise ValueError('Object reuse requires an explicitly trusted stable toolchain for the session')
        if type(timeout) not in (int, float) or not 0.01 <= timeout <= 60:
            raise ValueError('Build timeout must be between 0.01 and 60 seconds')
        self.cc, self.console, self.timeout = cc, console, timeout
        self._compiler_hash = compiler_hash()
        self._temporary = tempfile.TemporaryDirectory(prefix='talven-unit-session-')
        self._root = Path(self._temporary.name)
        self._cache, self._successful, self._closed, self._busy = {}, None, False, False

    def __enter__(self):
        if self._closed:
            raise ValueError('Unit build session is closed')
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self._busy:
            raise ValueError('Cannot close a unit build session during a build')
        self._temporary.cleanup()
        self._cache, self._successful, self._closed = {}, None, True

    def build(self, source):
        if self._closed or self._busy:
            raise ValueError('Unit build session is closed or already building')
        if compiler_hash() != self._compiler_hash:
            raise CompileError('E0501', 'Compiler inputs changed; restart the unit build session', Span(0, 0))
        self._busy = True
        candidate = None
        started = time.monotonic()

        def remaining():
            value = self.timeout - (time.monotonic() - started)
            if value < 0.01:
                raise failure('Native unit build timed out')
            return value

        try:
            prepared, executable, environment = _prepare_c_units(
                source, cc=self.cc, console=self.console, timeout=remaining())
            if prepared['compiler_hash'] != self._compiler_hash:
                raise CompileError('E0501', 'Compiler inputs changed; restart the unit build session', Span(0, 0))
            candidate = Path(tempfile.mkdtemp(prefix='candidate-', dir=self._root))
            configuration = source_hash(encode({
                'profile': 'hosted-object-reuse-v1', 'compiler_hash': self._compiler_hash,
                'language_profile': prepared['language_profile'], 'console': prepared['console'],
                'compiler': prepared['compiler'], 'flags': OBJECT_FLAGS,
                'driver_path': str(executable)}))
            cache, objects, compiled, reused, total = {}, [], [], [], 0
            for index, unit in enumerate(prepared['units']):
                remaining()
                identity, key = unit['id'], source_hash(encode([configuration, unit['id'], unit['c_hash']]))
                obj = candidate / f'{index}.o'
                previous = self._cache.get(identity)
                data = None
                if previous is not None and previous[0] == key:
                    try:
                        cached = artifact_bytes(previous[1])
                        if digest(cached) == previous[2]:
                            data = cached
                    except (OSError, CompileError):
                        pass  # Missing, nonregular or corrupt objects are cache misses.
                if data is not None:
                    with obj.open('xb') as stream:
                        stream.write(data)
                    reused.append(identity)
                else:
                    run_bounded([str(executable), *OBJECT_FLAGS, '-x', 'cpp-output', '-c', '-', '-o', str(obj)],
                                unit['c'].encode('utf-8'), environment, remaining(), 64 * 1024)
                    data = artifact_bytes(obj)
                    compiled.append(identity)
                total += len(data)
                if total > MAX_OBJECT_BYTES:
                    raise failure('Native unit objects exceed the 64 MiB session limit')
                cache[identity] = (key, obj, digest(data))
                objects.append(obj)
            program = candidate / 'program'
            run_bounded([str(executable), *OBJECT_FLAGS, *map(str, objects), '-o', str(program)],
                        b'', environment, remaining(), 64 * 1024)
            program_hash = digest(artifact_bytes(program))
            # The linker might alter input objects: verify every candidate before promotion.
            if any(digest(artifact_bytes(path)) != expected for _, path, expected in cache.values()):
                raise failure('Native unit object changed before successful publication')
            if (executable_hash(executable) != prepared['compiler']['executable_hash']
                    or compiler_hash() != self._compiler_hash):
                raise CompileError('E0501', 'Compiler inputs changed during native unit build; restart the session', Span(0, 0))
            remaining()
            receipt = {'schema': 'talven.unit-build.v1', 'profile': 'hosted-object-reuse-v1',
                       'source_hash': prepared['source_hash'], 'compiler_hash': self._compiler_hash,
                       'language_profile': prepared['language_profile'], 'console': prepared['console'],
                       'compiler': prepared['compiler'], 'flags': list(OBJECT_FLAGS),
                       'stable_toolchain_required': True, 'compiled': compiled, 'reused': reused,
                       'objects': [{'id': unit['id'], 'c_hash': unit['c_hash'],
                                    'key': cache[unit['id']][0], 'object_hash': cache[unit['id']][2]}
                                   for unit in prepared['units']],
                       'object_bytes': total, 'executable_hash': program_hash,
                       'raw_preprocessed_hash': prepared['raw_preprocessed_hash']}
            result = UnitBuild(program, receipt)
            previous_directory = self._successful
            self._cache, self._successful = cache, candidate
            candidate = None
            if previous_directory is not None:
                shutil.rmtree(previous_directory, ignore_errors=True)
            return result
        except OSError as error:
            raise CompileError('E0901', str(error), Span(0, 0)) from None
        finally:
            if candidate is not None:
                shutil.rmtree(candidate, ignore_errors=True)
            self._busy = False
