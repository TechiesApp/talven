"""Text-only evaluation through a pinned, ChatGPT-authenticated Codex CLI."""

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.adapters.claude_code_cli import EDIT_SCHEMA, render_prompt
from experiments.process import run_process
from experiments.protocol import candidate_source, digest, encode, strict_json
from experiments.tasks import get_tasks

MAX_BYTES = 4 * 1024 * 1024
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')
# This implementation has been checked against this CLI's catalog and tool registry.
CLI_VERSION = 'codex-cli 0.154.0'
DISABLED_FEATURES = ('shell_tool', 'unified_exec', 'view_image', 'apps', 'plugins', 'hooks',
                     'multi_agent', 'multi_agent_v2', 'memories', 'goals', 'tool_suggest',
                     'skill_search', 'sleep_tool', 'current_time_reminder', 'token_budget',
                     'request_permissions_tool', 'image_generation', 'browser_use',
                     'computer_use', 'artifact', 'workspace_dependencies', 'code_mode',
                     'code_mode_host', 'context_management')


def envelope(error=None):
    value = {'schema': 'talven.eval.response.v1', 'edits': {}, 'usage': None,
             'provider_metadata': {'transport': 'codex-cli', 'billing': 'chatgpt-subscription'}}
    if error:
        value['provider_metadata']['error'] = error
    return value


def validate_request(request):
    required = {'schema', 'corpus_version', 'task_id', 'context_mode', 'repetition', 'attempt',
                'allowed_files', 'model', 'messages'}
    if not isinstance(request, dict) or set(request) != required or request['schema'] != 'talven.eval.request.v1':
        raise ValueError('invalid_request')
    if request['task_id'] not in get_tasks(request['corpus_version']):
        raise ValueError('invalid_task')
    if request['allowed_files'] != ['task.tal'] or request['context_mode'] not in ('source', 'compiler'):
        raise ValueError('invalid_scope')
    model = request['model']
    if (not isinstance(model, dict) or set(model) != {'provider', 'model', 'tokenizer', 'settings'}
            or model['provider'] != 'openai-codex-cli' or not isinstance(model['model'], str)
            or not model['model'] or not isinstance(model['settings'], dict)
            or set(model['settings']) != {'effort', 'cli_version', 'cli_sha256', 'catalog_sha256'}
            or model['settings']['effort'] not in EFFORTS
            or model['settings']['cli_version'] != CLI_VERSION):
        raise ValueError('invalid_model_settings')
    messages = request['messages']
    if not isinstance(messages, list) or len(messages) < 2 or len(messages) % 2:
        raise ValueError('invalid_history')
    for index, message in enumerate(messages):
        role = 'system' if index == 0 else ('user' if index % 2 else 'assistant')
        if (not isinstance(message, dict) or set(message) != {'role', 'content'} or message['role'] != role
                or not isinstance(message['content'], str) or not message['content']):
            raise ValueError('invalid_history')


def restricted_catalog(raw, model, effort):
    rows = raw.get('models') if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise ValueError('invalid_catalog')
    matches = [row for row in rows if isinstance(row, dict) and row.get('slug') == model]
    if len(matches) != 1 or effort not in [r['effort'] for r in matches[0]['supported_reasoning_levels']]:
        raise ValueError('model_or_effort_not_in_catalog')
    row = dict(matches[0])
    row.update(apply_patch_tool_type=None, experimental_supported_tools=[], tool_mode='direct',
               supports_search_tool=False, supports_experimental_context=False,
               include_skills_usage_instructions=False, include_plugin_usage_instructions=False,
               include_apps_usage_instructions=False)
    return {**raw, 'models': [row]}


def command(executable, model, effort, catalog, system, schema):
    argv = [executable, 'exec', '--strict-config', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
            '--sandbox', 'read-only', '--json', '--color', 'never', '--model', model,
            '--output-schema', str(schema)]
    values = {'model_reasoning_effort': effort, 'forced_login_method': 'chatgpt',
              'model_instructions_file': str(system), 'model_catalog_json': str(catalog),
              'web_search': 'disabled', 'project_doc_max_bytes': 0,
              'tools.update_plan.enabled': False, 'tools.experimental_request_user_input.enabled': False,
              'include_apps_instructions': False, 'include_collaboration_mode_instructions': False,
              'include_permissions_instructions': False, 'features.skip_host_skill_discovery': True,
              'history.persistence': 'none', 'analytics.enabled': False}
    values.update({'features.' + feature: False for feature in DISABLED_FEATURES})
    for key, value in values.items():
        argv += ['-c', key + '=' + json.dumps(value)]
    return [*argv, '-']


def translate_events(data):
    result = envelope()
    metadata = result['provider_metadata']
    metadata['response_sha256'] = digest(data.encode())
    completions, candidates = [], []
    kinds, item_kinds = set(), set()
    error = None
    for line in data.splitlines():
        event = strict_json(line)
        if not isinstance(event, dict):
            raise ValueError('invalid_event')
        kind = event.get('type')
        if isinstance(kind, str) and len(kind) <= 100 and all(c.isalnum() or c in '._' for c in kind):
            kinds.add(kind)
        if kind == 'turn.completed':
            completions.append(event.get('usage'))
        elif kind in ('turn.failed', 'error'):
            error = 'cli_error'
        elif kind in ('item.started', 'item.updated', 'item.completed'):
            item = event.get('item', {})
            if isinstance(item, dict) and isinstance(item.get('type'), str) and len(item['type']) <= 100:
                item_kinds.add(item['type'])
            if not isinstance(item, dict) or item.get('type') not in ('agent_message', 'reasoning'):
                error = 'unexpected_tool_or_item'
            elif kind == 'item.completed' and item['type'] == 'agent_message':
                candidates.append(item.get('text'))
        elif kind not in ('thread.started', 'turn.started'):
            error = 'unexpected_event'
    metadata['completed_turns'] = len(completions)
    metadata['event_types'] = sorted(kinds)
    metadata['item_types'] = sorted(item_kinds)
    metadata['model_identity'] = 'CLI selector pinned; returned model snapshot unavailable'
    if len(completions) == 1 and isinstance(completions[0], dict):
        receipt = completions[0]
        names = ('input_tokens', 'cached_input_tokens', 'output_tokens')
        if any(type(receipt.get(k)) is not int or not 0 <= receipt[k] <= 10**12 for k in names):
            error = error or 'invalid_usage'
        elif receipt['cached_input_tokens'] > receipt['input_tokens']:
            error = error or 'invalid_usage'
        else:
            metadata['raw_usage'] = {k: receipt[k] for k in names}
            result['usage'] = {**metadata['raw_usage'], 'cache_write_input_tokens': None,
                               'model_cost_usd': None, 'tool_cost_usd': None,
                               'usage_source': 'Codex CLI turn.completed usage'}
    else:
        error = error or 'incomplete_or_multiple_turns'
    if error:
        metadata['error'] = error
        return result, 2
    if len(candidates) != 1 or not isinstance(candidates[0], str):
        metadata['candidate_error'] = 'invalid_source_edit'
        return result, 0
    text = candidates[0]
    metadata['candidate_text'] = text
    try:
        candidate = strict_json(text)
        if not isinstance(candidate, dict) or set(candidate) != {'edits'}:
            raise ValueError('invalid_candidate')
        candidate_source(candidate)
        result['edits'] = candidate['edits']
    except ValueError:
        metadata['candidate_error'] = 'invalid_source_edit'
    return result, 0


def run(request, executable, catalog, timeout, trace_dir=None):
    settings = request['model']['settings']
    if (digest(Path(executable).read_bytes()) != settings['cli_sha256']
            or digest(Path(catalog).read_bytes()) != settings['catalog_sha256']):
        raise ValueError('transport_changed')
    checked = restricted_catalog(strict_json(Path(catalog).read_text()), request['model']['model'], settings['effort'])
    if checked != strict_json(Path(catalog).read_text()):
        raise ValueError('unrestricted_catalog')
    with tempfile.TemporaryDirectory(prefix='talven-codex-') as temporary:
        directory = Path(temporary)
        system, schema = directory / 'instructions.txt', directory / 'edit-schema.json'
        system.write_text(request['messages'][0]['content'])
        schema.write_text(encode(EDIT_SCHEMA))
        argv = command(executable, request['model']['model'], settings['effort'], catalog, system, schema)
        prompt = render_prompt(request['messages']).encode()
        # Auth remains CLI-owned. Force ChatGPT login and remove API-key overrides.
        env = {k: v for k, v in os.environ.items() if k not in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY')}
        process = run_process(argv, cwd=directory, timeout=timeout, stdin=prompt, max_bytes=MAX_BYTES,
                              env=env, start_new_session=False)
    if trace_dir is not None:
        # Local diagnostics stay outside the public envelope. Never commit this
        # directory automatically: arbitrary provider errors may contain private data.
        trace = Path(trace_dir)
        trace.mkdir(parents=True, exist_ok=True)
        data = encode(process).encode()
        target = trace / (digest(data) + '.json')
        if not target.exists():
            with target.open('xb') as handle:
                handle.write(data)
    result, code = translate_events(process['stdout'])
    metadata = result['provider_metadata']
    metadata.update(cli_version=CLI_VERSION, cli_sha256=settings['cli_sha256'],
                    catalog_sha256=settings['catalog_sha256'], requested_model=request['model']['model'],
                    request_sha256=digest(encode({'system': request['messages'][0]['content'],
                                                'prompt': prompt.decode(), 'settings': settings}).encode()))
    if process['error'] or process['returncode'] != 0:
        metadata['error'] = process['error'] or 'cli_exit_error'
        result['edits'] = {}
        code = 2
    metadata['cli_returncode'] = process['returncode']
    metadata['cli_stderr_sha256'] = digest(process['stderr'].encode())
    return result, code


def write_config(args):
    if not args.model or args.effort not in EFFORTS:
        raise ValueError('explicit_model_and_effort_required')
    executable = shutil.which(args.codex)
    if executable is None:
        raise ValueError('codex_cli_not_found')
    executable = str(Path(executable).resolve())
    version = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    if version != CLI_VERSION:
        raise ValueError('unsupported_cli_version')
    bundled = subprocess.run([executable, 'debug', 'models', '--bundled'], capture_output=True,
                             text=True, timeout=10, check=True)
    catalog = restricted_catalog(strict_json(bundled.stdout), args.model, args.effort)
    target = Path(args.write_config).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    catalog_path = target.with_suffix('.catalog.json')
    if target.exists() or catalog_path.exists():
        raise ValueError('refusing_to_overwrite_configuration')
    catalog_bytes = encode(catalog).encode()
    script = Path(__file__).resolve()
    config = {'schema': 'talven.eval.adapter.v1', 'kind': 'live', 'provider': 'openai-codex-cli',
              'model': args.model, 'tokenizer': 'unavailable: Codex CLI does not expose tokenizer identity',
              'settings': {'effort': args.effort, 'cli_version': version,
                           'cli_sha256': digest(Path(executable).read_bytes()), 'catalog_sha256': digest(catalog_bytes)},
              'command': [str(Path(sys.executable).resolve()), str(script), '--codex', executable,
                          '--catalog', str(catalog_path), '--timeout', str(args.timeout),
                          '--trace-dir', str(target.parent / (target.stem + '.receipts'))],
              'artifacts': [str(script), str(script.with_name('claude_code_cli.py')), str(catalog_path)]}
    with catalog_path.open('xb') as handle:
        handle.write(catalog_bytes)
    with target.open('x') as handle:
        handle.write(encode(config))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-config')
    parser.add_argument('--model')
    parser.add_argument('--effort', choices=EFFORTS)
    parser.add_argument('--codex', default='codex')
    parser.add_argument('--catalog')
    parser.add_argument('--trace-dir')
    parser.add_argument('--timeout', type=float, default=900)
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.timeout) or not 0 < args.timeout <= 3600:
            raise ValueError('invalid_timeout')
        if args.write_config:
            write_config(args)
            return 0
        if args.model is not None or args.effort is not None or args.catalog is None:
            raise ValueError('invalid_configuration')
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('request_size_limit')
        request = strict_json(data.decode())
        validate_request(request)
        result, code = run(request, args.codex, args.catalog, args.timeout, args.trace_dir)
    except (ValueError, OSError, UnicodeError, KeyError, TypeError, subprocess.SubprocessError):
        result, code = envelope('invalid_input_or_configuration'), 2
    sys.stdout.write(encode(result))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
