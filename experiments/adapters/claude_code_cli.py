"""Evaluation transport through the Claude Code CLI (`claude -p`).

Uses the operator's signed-in Claude Code account, such as a Max subscription,
instead of an API key. Each attempt is one isolated headless session: safe
mode (no CLAUDE.md, skills, plugins, hooks, or MCP servers), no tools, no
session persistence, a pinned model and effort, the runner's system prompt,
and a JSON schema for the edit. Reported costs are the CLI's list-price
equivalents; subscription use is not billed per token.
"""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.adapters.anthropic_messages import (EFFORTS, PRICING_PATH, bounded_bytes, envelope, failure,
                                                     identity, load_pricing, receipt_usage)
from experiments.protocol import candidate_source, digest, encode, strict_json
from experiments.tasks import get_tasks

MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
EDIT_SCHEMA = {'type': 'object', 'properties': {'edits': {'type': 'object',
               'properties': {'task.tal': {'type': 'string'}}, 'required': ['task.tal'],
               'additionalProperties': False}}, 'required': ['edits'], 'additionalProperties': False}
# The CLI has no way to inject earlier assistant turns, so repair attempts
# render the conversation into one user message. Both conditions get the same framing.
TRANSCRIPT_HEADER = ('Earlier turns of this task, oldest first. "Runner" messages come from the evaluation '
                     'runner; "You" messages are your previous answers.')
MODEL_FAILURES = {'max_tokens', 'refusal'}
# Models that reject an effort setting; every other model must pin one.
NO_EFFORT_MODELS = {'claude-haiku-4-5'}


def validate_request(request):
    required = {'schema', 'corpus_version', 'task_id', 'context_mode', 'repetition', 'attempt',
                'allowed_files', 'model', 'messages'}
    if not isinstance(request, dict) or set(request) != required or request['schema'] != 'talven.eval.request.v1':
        raise ValueError('invalid_request')
    if not isinstance(request['task_id'], str) or request['task_id'] not in get_tasks(request['corpus_version']):
        raise ValueError('invalid_task')
    if request['allowed_files'] != ['task.tal'] or request['context_mode'] not in ('source', 'compiler'):
        raise ValueError('invalid_scope')
    model = request['model']
    if (not isinstance(model, dict) or set(model) != {'provider', 'model', 'tokenizer', 'settings'}
            or model['provider'] != 'anthropic-claude-code-cli' or not identity(model['model'])):
        raise ValueError('invalid_model')
    expected = set() if model['model'] in NO_EFFORT_MODELS else {'effort'}
    if (not isinstance(model['settings'], dict) or set(model['settings']) != expected
            or model['settings'].get('effort', EFFORTS[0]) not in EFFORTS):
        raise ValueError('invalid_settings')
    messages = request['messages']
    if not isinstance(messages, list) or len(messages) < 2 or len(messages) % 2:
        raise ValueError('invalid_history')
    for index, message in enumerate(messages):
        role = 'system' if index == 0 else ('user' if index % 2 else 'assistant')
        if (not isinstance(message, dict) or set(message) != {'role', 'content'} or message['role'] != role
                or not isinstance(message['content'], str) or not message['content']):
            raise ValueError('invalid_history')


def render_prompt(messages):
    """The latest runner message, preceded by earlier turns on repairs."""
    turns = messages[1:]
    if len(turns) == 1:
        return turns[0]['content']
    history = '\n\n'.join(f"[{'Runner' if message['role'] == 'user' else 'You'}]\n{message['content']}"
                          for message in turns[:-1])
    return f"{TRANSCRIPT_HEADER}\n\n{history}\n\n[Runner, current message]\n{turns[-1]['content']}"


def command(executable, model, effort, system):
    effort_flags = ['--effort', effort] if effort is not None else []
    return [executable, '-p', '--safe-mode', '--model', model, *effort_flags, '--tools', '',
            '--no-session-persistence', '--system-prompt', system, '--output-format', 'json',
            '--json-schema', json.dumps(EDIT_SCHEMA, separators=(',', ':'))]


def child_environment():
    # The subscription login must be used; an API key in the environment would take precedence.
    return {name: value for name, value in os.environ.items() if name != 'ANTHROPIC_API_KEY'}


def translate_result(data, model, pricing):
    result = envelope(); metadata = result['provider_metadata']
    metadata['transport'] = 'claude-code-cli'
    metadata['response_sha256'] = digest(data)
    try:
        value = strict_json(data.decode('utf-8'))
    except (ValueError, UnicodeError):
        return failure(result, 'invalid_response_json')
    if not isinstance(value, dict) or value.get('type') != 'result':
        return failure(result, 'invalid_response')
    for field in ('session_id', 'stop_reason', 'subtype', 'terminal_reason'):
        if isinstance(value.get(field), str) and identity(value[field]):
            metadata['response_' + field] = value[field]
    models = value.get('modelUsage')
    if isinstance(models, dict):
        metadata['response_models'] = sorted(name for name in models if isinstance(name, str) and identity(name))
    result['usage'], malformed = receipt_usage(value.get('usage'), False, metadata, model, pricing)
    if malformed:
        return failure(result, 'invalid_usage')
    if result['usage'] is not None:
        result['usage']['usage_source'] = 'Claude Code CLI result usage'
        if result['usage']['model_cost_usd'] is not None:
            result['usage']['model_cost_source'] = (pricing['provenance'] + '; list-price equivalent, '
                                                    'billed through the Claude Code subscription')
    reported = value.get('total_cost_usd')
    if isinstance(reported, (int, float)) and math.isfinite(reported):
        metadata['cli_list_cost_usd'] = reported
    if metadata.get('response_models') not in (None, [model]):
        return failure(result, 'unexpected_model')
    if value.get('is_error') or value.get('subtype') != 'success':
        return failure(result, 'cli_error')
    stop = value.get('stop_reason')
    if stop in MODEL_FAILURES:
        metadata['model_failure'] = stop
        return result, 0
    candidate = value.get('structured_output')
    text = value.get('result')
    if isinstance(text, str) and text:
        metadata['candidate_text'] = text
    try:
        if not isinstance(candidate, dict) or set(candidate) != {'edits'}:
            raise ValueError('invalid_candidate')
        candidate_source(candidate)
        result['edits'] = candidate['edits']
    except ValueError:
        metadata['candidate_error'] = 'invalid_source_edit'
    return result, 0


def run(request, executable, timeout, pricing):
    model = request['model']['model']
    argv = command(executable, model, request['model']['settings'].get('effort'), request['messages'][0]['content'])
    prompt = render_prompt(request['messages']).encode('utf-8')
    try:
        completed = subprocess.run(argv, input=prompt, capture_output=True, timeout=timeout,
                                   env=child_environment(), cwd=os.getcwd())
    except subprocess.TimeoutExpired:
        return failure(envelope(), 'timeout')
    except OSError:
        return failure(envelope(), 'launch_error')
    if len(completed.stdout) > MAX_OUTPUT_BYTES:
        return failure(envelope(), 'response_size_limit')
    result, code = translate_result(completed.stdout, model, pricing)
    result['provider_metadata']['request_sha256'] = digest(encode({'argv': argv[1:], 'stdin': prompt.decode('utf-8')}).encode('utf-8'))
    if completed.returncode != 0 and code == 0 and not result['edits']:
        result['provider_metadata']['cli_exit_status'] = completed.returncode
    return result, code


def write_config(args):
    if not identity(args.model):
        raise ValueError('explicit_model_required')
    if args.model in NO_EFFORT_MODELS:
        if args.effort is not None:
            raise ValueError('model_does_not_support_effort')
    elif args.effort not in EFFORTS:
        raise ValueError('explicit_effort_required')
    pricing = Path(args.pricing).resolve(strict=True)
    if args.model not in load_pricing(pricing)['models']:
        raise ValueError('model_missing_from_pricing_table')
    # The resolved CLI path, which includes its version, is recorded in the command.
    # The binary is not listed as an artifact: archiving it would copy ~200 MB per run.
    executable = shutil.which(args.claude)
    if executable is None:
        raise ValueError('claude_cli_not_found')
    script = Path(__file__).resolve(); root = script.parents[2]
    config = {'schema': 'talven.eval.adapter.v1', 'kind': 'live', 'provider': 'anthropic-claude-code-cli',
              'model': args.model, 'tokenizer': 'unavailable: Claude Code CLI does not expose tokenizer identity',
              'settings': {} if args.effort is None else {'effort': args.effort},
              'command': [str(Path(sys.executable).resolve()), str(script), '--claude', str(Path(executable).resolve()),
                          '--timeout', str(args.timeout), '--pricing', str(pricing)],
              'artifacts': [str(script), str(root / 'experiments/adapters/anthropic_messages.py'),
                            str(root / 'experiments/protocol.py'), str(root / 'experiments/metrics.py'),
                            str(pricing)]}
    target = Path(args.write_config)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as handle:
        handle.write(encode(config))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-config')
    parser.add_argument('--model')
    parser.add_argument('--effort', choices=EFFORTS)
    parser.add_argument('--claude', default='claude')
    parser.add_argument('--timeout', type=float, default=900)
    parser.add_argument('--pricing', default=str(PRICING_PATH))
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.timeout) or not 0 < args.timeout <= 3600:
            raise ValueError('invalid_timeout')
        if args.write_config is not None:
            write_config(args)
            return 0
        if args.model is not None or args.effort is not None:
            raise ValueError('settings_belong_in_request')
        data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError('request_size_limit')
        request = strict_json(data.decode('utf-8'))
        validate_request(request)
        bounded_bytes(request, MAX_REQUEST_BYTES)
        pricing = load_pricing(args.pricing)
        pricing['provenance'] = f"{Path(args.pricing).name} sha256:{digest(Path(args.pricing).read_bytes())}; {pricing['source']}"
        result, code = run(request, args.claude, args.timeout, pricing)
    except (ValueError, OSError, UnicodeError):
        result, code = failure(envelope(), 'invalid_input_or_configuration')
    sys.stdout.write(encode(result))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
