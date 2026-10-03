"""Explicit local-project CLI; normal single-file commands remain unchanged."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .backend import emit_c
from .context import encode
from .frontend import CompileError, Span
from .native import compiler_command
from .project import ProjectReader, failure, project_context, resolve_project


def run_project(args):
    reader = None
    try:
        reader = ProjectReader(args.root)
        project = resolve_project(args.entry, reader.read)
        identity = project.identity()
        if args.expect_graph_hash not in (None, identity['graph_hash']):
            raise failure('E0501', 'Project revision changed; request fresh sources and context')
        reader.verify(project)
        if args.project_command == 'check':
            if args.json:
                print(encode({'schema': 'talven.project-check.v1', 'ok': True,
                              'validation': 'frontend-only', **identity, 'diagnostics': []}), end='')
            else:
                print(f'Project check passed ({len(project.modules)} modules)')
        elif args.project_command == 'context':
            receipt = project_context(project, args.symbol, args.include_body, args.max_bytes)
            print(encode(receipt), end='')
        else:
            output = args.output
            if output is not None:
                for path in project.modules:
                    source = args.root / path
                    if output.resolve() == source.resolve() or (output.exists() and output.samefile(source)):
                        raise failure('E0403', 'Output must not overwrite any project source')
            generated = emit_c(project.analysis, console=args.console)
            if output is None:
                print(generated, end='')
            else:
                output = output.resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='talven-project-', dir=output.parent) as temporary:
                    cfile = Path(temporary) / 'program.c'
                    cfile.write_text(generated, encoding='utf-8')
                    staged = cfile
                    if args.project_command == 'build':
                        staged = Path(temporary) / 'program'
                        result = subprocess.run(compiler_command(args.cc, cfile, staged),
                                                capture_output=True, text=True, timeout=30)
                        if result.returncode:
                            raise failure('E0402', 'C compiler failed: ' + (result.stderr or result.stdout).strip())
                    reader.verify(project)
                    os.replace(staged, output)
                print(f'Built {output}' if args.project_command == 'build' else f'Emitted {output}')
        return 0
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        diagnostic = CompileError('E0901', str(error), Span(0, 0)).diagnostic('')
    except CompileError as error:
        diagnostic = error.diagnostic('')
    finally:
        if reader is not None:
            reader.close()
    if args.project_command == 'context' or getattr(args, 'json', False):
        print(encode({'schema': 'talven.diagnostics.v1', 'ok': False, 'diagnostics': [diagnostic]}), end='')
    else:
        start = diagnostic['range']['start']
        print(f"{diagnostic.get('file', args.entry)}:{start['line'] + 1}:{start['character'] + 1}: "
              f"{diagnostic['code']}: {diagnostic['message']}", file=sys.stderr)
    return 1
