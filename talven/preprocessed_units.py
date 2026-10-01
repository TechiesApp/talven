"""Freeze a single trusted C preprocessing pass into checked function units.

This prepares compiler input, never objects or an executable. Tool/source hashes
are byte identities, not authenticated toolchain or native-acceptance evidence.
"""

import hashlib
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import stat
import time

from .backend import MAX_C_UNIT_BYTES, MAX_C_UNITS, emit_preprocess_units
from . import PROFILE
from .context import compiler_hash, encode, source_hash
from .frontend import CompileError, Span, analyze
from .c_command import run_bounded
from .c_pipeline import CompilerRequest, run_steps

MAX_PREPARED_BYTES = 64 * 1024 * 1024
FLAGS = ('-std=c11', '-O2', '-Wall', '-Wextra', '-pedantic-errors')
BOUNDARY = re.compile(r'\s*extern\s+int\s+tv_unit_(header_boundary|boundary_([0-9]+))\s*;\s*\Z')
OWN_LINE = re.compile(r'(#\s+)\d+(\s+"<stdin>"(?:\s+[1-4])*\s*)\Z')
IDENTITY = re.compile(r'(?:entry|fn:[A-Za-z_][A-Za-z_0-9]*)\Z')


def failure(message):
    return CompileError('E0402', message, Span(0, 0))


def split_preprocessed(output, identities):
    if (not identities or len(identities) > MAX_C_UNITS + 1
            or any(not isinstance(identity, str) or not IDENTITY.fullmatch(identity) for identity in identities)
            or len(set(identities)) != len(identities)):
        raise failure('Invalid preprocessed unit identities')
    if not isinstance(output, str) or len(output.encode('utf-8')) > MAX_C_UNIT_BYTES:
        raise failure('Preprocessor output exceeds the 16 MiB experiment limit')
    header, pending, units, size = None, [], {}, 0
    for line in output.splitlines(keepends=True):
        marker = BOUNDARY.fullmatch(line)
        if marker:
            if marker[1] == 'header_boundary':
                if header is not None or units:
                    raise failure('Repeated preprocessor header boundary')
                header, pending = ''.join(pending), []
                if not header.strip():
                    raise failure('Empty preprocessed header')
            else:
                if header is None or int(marker[2]) != len(units) or len(units) >= len(identities):
                    raise failure('Missing or unordered preprocessed unit boundary')
                body = ''.join(pending)
                if not any(line.strip() and not line.lstrip().startswith('#') for line in pending):
                    raise failure('Empty preprocessed unit')
                generated = header + body
                size += len(generated.encode('utf-8'))
                if size > MAX_PREPARED_BYTES:
                    raise failure('Prepared units exceed the 64 MiB experiment limit')
                units[identities[len(units)]] = generated
                pending = []
            continue
        own = OWN_LINE.fullmatch(line)
        pending.append(f'{own[1]}1{own[2]}' if own else line)
    if header is None or len(units) != len(identities) or any(
            line.strip() and not OWN_LINE.fullmatch(line) for line in pending):
        raise failure('Incomplete or trailing preprocessed unit output')
    return units


def executable_hash(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise CompileError('E0901', 'C compiler executable must be a regular file', Span(0, 0))
        digest = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()


@dataclass(frozen=True)
class DriverProbe:
    identity: tuple[str, str, str, str]
    version: str
    target: str


def _prepare_c_units_steps(source, *, cc='cc', console=False, timeout=30, probe=None, local_contracts=False):
    if type(timeout) not in (int, float) or not 0.01 <= timeout <= 60:
        raise ValueError('Preparation timeout must be between 0.01 and 60 seconds')
    pinned = compiler_hash()
    preprocessing_input, identities = emit_preprocess_units(analyze(source), console=console,
                                                           local_contracts=local_contracts)
    environment = dict(os.environ)
    environment['LC_ALL'] = 'C'
    # Hash the effective inherited environment without retaining values in receipts.
    environment_hash = source_hash(encode(environment))
    working_directory = os.getcwd()
    working_directory_hash = source_hash(working_directory)
    selected = shutil.which(cc, path=environment.get('PATH'))
    if selected is None:
        raise CompileError('E0901', 'C compiler executable was not found', Span(0, 0))
    executable = Path(selected).resolve()
    before = executable_hash(executable)
    started = time.monotonic()

    def command(arguments, data=b'', limit=64 * 1024):
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise failure('C unit preparation timed out')
        return (yield CompilerRequest('prepare', (str(executable), *arguments), data, environment,
                                      remaining, limit, working_directory))

    probe_identity = (str(executable), before, environment_hash, working_directory_hash)
    probe_reused = isinstance(probe, DriverProbe) and probe.identity == probe_identity
    if probe_reused:
        version, target = probe.version, probe.target
    else:
        version = (yield from command(['--version'])).decode('utf-8')
        target = (yield from command(['-dumpmachine'])).decode('utf-8').strip()
    output = yield from command([*FLAGS, '-E', '-x', 'c', '-'], preprocessing_input.encode('utf-8'), MAX_C_UNIT_BYTES)
    units = split_preprocessed(output.decode('utf-8'), identities)
    if before != executable_hash(executable) or pinned != compiler_hash():
        raise CompileError('E0501', 'Compiler inputs changed during C unit preparation; retry with a stable toolchain', Span(0, 0))
    receipt = {'schema': 'talven.preprocessed-units.v1',
            'profile': 'hosted-preprocessed-local-contracts-v1' if local_contracts else 'hosted-preprocessed-units-v1',
            'language_profile': PROFILE,
            'source_hash': source_hash(source), 'compiler_hash': pinned, 'console': console,
            'driver_probe_reused': probe_reused,
            'compiler': {'executable_hash': before, 'version': version, 'target': target,
                         'flags': list(FLAGS), 'environment_hash': environment_hash,
                         'working_directory_hash': working_directory_hash},
            'preprocessing_input_hash': source_hash(preprocessing_input),
            'raw_preprocessed_hash': hashlib.sha256(output).hexdigest(),
            'normalization': 'Own <stdin> line-marker numbers become 1; system markers/flags retained',
            'units': [{'id': identity, 'c': generated, 'c_hash': source_hash(generated)}
                      for identity, generated in units.items()]}
    return receipt, executable, environment, DriverProbe(probe_identity, version, target), working_directory


def _prepare_c_units(source, *, cc='cc', console=False, timeout=30, probe=None, local_contracts=False):
    return run_steps(_prepare_c_units_steps(source, cc=cc, console=console, timeout=timeout, probe=probe,
                                          local_contracts=local_contracts),
                     {'prepare': run_bounded})


def prepare_c_units(source, *, cc='cc', console=False, timeout=30, local_contracts=False):
    return _prepare_c_units(source, cc=cc, console=console, timeout=timeout, local_contracts=local_contracts)[0]
