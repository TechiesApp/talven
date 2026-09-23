"""Bounded Anthropic Messages transport for the source-edit evaluation protocol.

Live requests require an explicit --live flag and stream the response. Fixture
receipts are synthetic. A pinned pricing table turns reported usage into a
model cost; unknown prices or token breakdowns leave the cost null.
"""
import argparse
from decimal import Decimal
import http.client
import math
import os
from pathlib import Path
import re
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.protocol import candidate_source, digest, encode, strict_json
from experiments.tasks import get_tasks

MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_OUTPUT_TOKENS = 128000
DEFAULT_MAX_TOKENS = 32000
API_VERSION = '2023-06-01'
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
# These models reject temperature/top_p with HTTP 400; thinking depth is set by effort instead.
NO_SAMPLING_MODELS = re.compile(r'claude-(opus-(4-[78]|5)|sonnet-5|fable|mythos)')
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})
MAX_RETRIES = 3
MAX_RETRY_DELAY = 60.0
# Stop reasons that describe what the model produced, not a transport fault.
# The runner treats them as a failed attempt that may be repaired.
MODEL_FAILURES = ('max_tokens', 'refusal')
PRICING_PATH = Path(__file__).resolve().with_name('anthropic-pricing.json')
PRICE_FIELDS = ('input', 'output', 'cache_write_5m', 'cache_write_1h', 'cache_read')
TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)


def bounded_bytes(value, limit):
    data = encode(value).encode('utf-8')
    if len(data) > limit:
        raise ValueError('size_limit')
    return data


def identity(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 512 and all(ord(c) >= 32 for c in value)


def settings_valid(settings, model=None):
    allowed = {'max_tokens', 'effort', 'thinking', 'temperature', 'top_p'}
    if not isinstance(settings, dict) or settings.keys() - allowed:
        raise ValueError('invalid_settings')
    if type(settings.get('max_tokens')) is not int or not 1 <= settings['max_tokens'] <= MAX_OUTPUT_TOKENS:
        raise ValueError('invalid_max_tokens')
    if 'effort' in settings and settings['effort'] not in EFFORTS:
        raise ValueError('invalid_effort')
    if 'thinking' in settings and settings['thinking'] != 'adaptive':
        raise ValueError('invalid_thinking')
    if 'temperature' in settings and 'top_p' in settings:
        raise ValueError('conflicting_sampling_options')
    for key in ('temperature', 'top_p'):
        if key in settings:
            if isinstance(model, str) and NO_SAMPLING_MODELS.match(model):
                raise ValueError('sampling_unsupported_by_model')
            value = settings[key]
            if type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value):
                raise ValueError('invalid_sampling_option')


def build_request(request):
    required = {'schema', 'corpus_version', 'task_id', 'context_mode', 'repetition', 'attempt',
                'allowed_files', 'model', 'messages'}
    if not isinstance(request, dict) or set(request) != required or request['schema'] != 'talven.eval.request.v1':
        raise ValueError('invalid_request')
    bounded_bytes(request, MAX_REQUEST_BYTES)
    task_id = request['task_id']
    if not isinstance(task_id, str) or task_id not in get_tasks(request['corpus_version']):
        raise ValueError('invalid_task')
    if request['allowed_files'] != ['task.tal'] or request['context_mode'] not in ('source', 'compiler'):
        raise ValueError('invalid_scope')
    for name, low, high in [('attempt', 0, 20), ('repetition', 1, 100)]:
        if type(request[name]) is not int or not low <= request[name] <= high:
            raise ValueError('invalid_trial')
    model = request['model']
    if not isinstance(model, dict) or set(model) != {'provider', 'model', 'tokenizer', 'settings'}:
        raise ValueError('invalid_model')
    if model['provider'] != 'anthropic' or not identity(model['model']) or not identity(model['tokenizer']):
        raise ValueError('invalid_model')
    settings = model['settings']
    settings_valid(settings, model['model'])
    messages = request['messages']
    if not isinstance(messages, list) or len(messages) < 2 or len(messages) % 2:
        raise ValueError('invalid_history')
    for index, message in enumerate(messages):
        role = 'system' if index == 0 else ('user' if index % 2 else 'assistant')
        if (not isinstance(message, dict) or set(message) != {'role', 'content'} or message['role'] != role
                or not isinstance(message['content'], str) or not message['content']):
            raise ValueError('invalid_history')
    edit_schema = {'type': 'object', 'properties': {'edits': {'type': 'object',
                   'properties': {'task.tal': {'type': 'string'}}, 'required': ['task.tal'],
                   'additionalProperties': False}}, 'required': ['edits'], 'additionalProperties': False}
    output_config = {'format': {'type': 'json_schema', 'schema': edit_schema}}
    if 'effort' in settings:
        output_config['effort'] = settings['effort']
    payload = {'model': model['model'], 'max_tokens': settings['max_tokens'], 'system': messages[0]['content'],
               'messages': [dict(message) for message in messages[1:]], 'stream': True,
               'output_config': output_config}
    for key in ('temperature', 'top_p'):
        if key in settings:
            payload[key] = settings[key]
    if settings.get('thinking') == 'adaptive':
        payload['thinking'] = {'type': 'adaptive'}
    bounded_bytes(payload, MAX_REQUEST_BYTES)
    return payload


def envelope(fixture=False):
    return {'schema': 'talven.eval.response.v1', 'edits': {}, 'usage': None,
            'provider_metadata': {'provider': 'anthropic', 'api_version': API_VERSION, 'synthetic': fixture}}


def failure(result, code):
    result['provider_metadata']['error'] = code
    return result, 2


def load_pricing(path=PRICING_PATH):
    value = strict_json(Path(path).read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or value.get('schema') != 'talven.eval.anthropic-pricing.v1'
            or not identity(value.get('source')) or not isinstance(value.get('models'), dict)):
        raise ValueError('invalid_pricing')
    for model, prices in value['models'].items():
        if not identity(model) or not isinstance(prices, dict) or set(prices) != set(PRICE_FIELDS):
            raise ValueError('invalid_pricing')
        for price in prices.values():
            if not isinstance(price, str) or not re.fullmatch(r'\d{1,6}(\.\d{1,6})?', price):
                raise ValueError('invalid_pricing')
    return value


def model_cost(receipt, model, pricing):
    """USD cost of one call from its usage receipt, or None when unknown.

    Input is billed as uncached input + cache writes by TTL + cache reads.
    Cache writes without a TTL breakdown cannot be priced.
    """
    prices = (pricing or {}).get('models', {}).get(model)
    fields = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')
    if prices is None or any(field not in receipt for field in fields):
        return None
    writes = receipt['cache_creation_input_tokens']
    breakdown = receipt.get('cache_creation', {})
    by_ttl = (breakdown.get('ephemeral_5m_input_tokens', 0), breakdown.get('ephemeral_1h_input_tokens', 0))
    if writes and sum(by_ttl) != writes:
        return None
    rate = {field: Decimal(price) for field, price in prices.items()}
    total = (receipt['input_tokens'] * rate['input'] + by_ttl[0] * rate['cache_write_5m']
             + by_ttl[1] * rate['cache_write_1h'] + receipt['cache_read_input_tokens'] * rate['cache_read']
             + receipt['output_tokens'] * rate['output']) / TOKENS_PER_PRICE_UNIT
    text = format(total.quantize(Decimal('0.000000000001')), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def receipt_usage(raw, fixture, metadata, model=None, pricing=None):
    if raw is None:
        return None, False
    if not isinstance(raw, dict):
        return None, True
    fields = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')
    receipt = {}; malformed = False
    for field in fields:
        value = raw.get(field)
        if value is None:
            continue
        if type(value) is not int or not 0 <= value <= 10**12:
            malformed = True
        else:
            receipt[field] = value
    # Details are breakdowns, never additional input/output-token summands.
    for name, detail_fields in [('cache_creation', ('ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens')),
                         ('output_tokens_details', ('thinking_tokens',))]:
        detail = raw.get(name)
        if detail is None:
            continue
        if not isinstance(detail, dict):
            malformed = True
            continue
        clean = {}
        for field in detail_fields:
            value = detail.get(field)
            if value is None:
                continue
            if type(value) is not int or not 0 <= value <= 10**12:
                malformed = True
            else:
                clean[field] = value
        receipt[name] = clean
    source = 'synthetic Anthropic Messages fixture usage' if fixture else 'Anthropic Messages API response usage'
    metadata['usage_receipt'] = receipt
    metadata['usage_source'] = source
    total = None
    if all(field in receipt for field in fields[:3]):
        total = sum(receipt[field] for field in fields[:3])
        if total > 10**12:
            malformed = True
            total = None
    usage = {'input_tokens': total,
             'cached_input_tokens': receipt.get('cache_read_input_tokens') if total is not None else None,
             'cache_write_input_tokens': receipt.get('cache_creation_input_tokens') if total is not None else None,
             'output_tokens': receipt.get('output_tokens'), 'model_cost_usd': None, 'tool_cost_usd': None,
             'usage_source': source}
    cost = None if malformed else model_cost(receipt, model, pricing)
    if cost is not None:
        usage['model_cost_usd'] = cost
        usage['model_cost_source'] = pricing['provenance']
    return None if fixture else usage, malformed


def translate_message(value, *, http_status=200, fixture=False, model=None, pricing=None, result=None):
    """Validate a complete Messages API response object into the protocol envelope."""
    result = result or envelope(fixture); metadata = result['provider_metadata']
    if not isinstance(value, dict):
        return failure(result, 'invalid_response')
    for field in ('id', 'model', 'stop_reason'):
        item = value.get(field)
        if isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', item):
            metadata['response_' + field] = item
    result['usage'], malformed = receipt_usage(value.get('usage'), fixture, metadata, model, pricing)
    if malformed:
        return failure(result, 'invalid_usage')
    if type(http_status) is not int or http_status != 200:
        return failure(result, 'http_error')
    if value.get('type') != 'message' or value.get('role') != 'assistant' or value.get('error') is not None:
        return failure(result, 'invalid_message')
    stop = value.get('stop_reason')
    if stop not in ('end_turn', *MODEL_FAILURES):
        return failure(result, 'incomplete_or_refused')
    details = value.get('stop_details')
    if details is not None and (not isinstance(details, dict)
                                or (details.get('type') == 'refusal') != (stop == 'refusal')):
        return failure(result, 'refused_or_invalid_stop_details')
    content = value.get('content')
    if not isinstance(content, list):
        return failure(result, 'invalid_content')
    chunks = []
    for block in content:
        if not isinstance(block, dict):
            return failure(result, 'invalid_content')
        kind = block.get('type')
        if kind == 'text' and isinstance(block.get('text'), str):
            chunks.append(block['text'])
        elif kind == 'thinking' and isinstance(block.get('thinking'), str) and isinstance(block.get('signature'), str):
            continue
        elif kind == 'redacted_thinking' and isinstance(block.get('data'), str):
            continue
        else:
            return failure(result, 'unsupported_content')
    text = ''.join(chunks)
    if text:
        metadata['candidate_text'] = text
    if stop in MODEL_FAILURES:
        # A cut-off or refused answer is a model outcome: no edit is accepted,
        # and the runner may offer a repair attempt.
        metadata['model_failure'] = stop
        return result, 0
    if not chunks:
        return failure(result, 'missing_text')
    try:
        candidate = strict_json(text)
        if not isinstance(candidate, dict) or set(candidate) != {'edits'}:
            raise ValueError('invalid_candidate')
        candidate_source(candidate)
        result['edits'] = candidate['edits']
    except ValueError:
        metadata['candidate_error'] = 'invalid_source_edit'
    return result, 0


def translate_response(body, *, http_status=200, request_id=None, fixture=False, model=None, pricing=None):
    result = envelope(fixture); metadata = result['provider_metadata']
    metadata['response_sha256'] = digest(body)
    if isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,200}', request_id):
        metadata['request_id'] = request_id
    if len(body) > MAX_RESPONSE_BYTES:
        return failure(result, 'response_size_limit')
    try:
        value = strict_json(body.decode('utf-8'))
    except (ValueError, UnicodeError):
        return failure(result, 'invalid_response_json')
    return translate_message(value, http_status=http_status, fixture=fixture, model=model, pricing=pricing,
                             result=result)


def read_stream(response):
    """Assemble a Messages API object from server-sent events.

    Returns (message, raw_bytes). Raises ValueError for an error event,
    malformed events, or a stream that ends before message_stop.
    """
    raw = bytearray(); message = None; blocks = {}; event_data = []

    def dispatch(data):
        nonlocal message
        event = strict_json(data)
        if not isinstance(event, dict):
            raise ValueError('invalid_event')
        kind = event.get('type')
        if kind == 'message_start':
            message = dict(event.get('message') or {})
            message['content'] = []
        elif message is None and kind != 'ping':
            raise ValueError('event_before_message_start')
        elif kind == 'content_block_start':
            blocks[event['index']] = dict(event['content_block'])
        elif kind == 'content_block_delta':
            block, delta = blocks[event['index']], event['delta']
            field = {'text_delta': 'text', 'thinking_delta': 'thinking', 'signature_delta': 'signature'}.get(
                delta.get('type'))
            if field is None:
                raise ValueError('unsupported_delta')
            block[field] = block.get(field, '') + delta[field]
        elif kind == 'message_delta':
            delta = event.get('delta') or {}
            for key in ('stop_reason', 'stop_sequence', 'stop_details'):
                if key in delta:
                    message[key] = delta[key]
            usage = dict(message.get('usage') or {})
            usage.update({key: value for key, value in (event.get('usage') or {}).items() if value is not None})
            message['usage'] = usage
        elif kind == 'message_stop':
            message['content'] = [blocks[index] for index in sorted(blocks)]
            return True
        elif kind == 'error':
            raise ValueError('stream_error')
        return False

    while True:
        line = response.readline(MAX_RESPONSE_BYTES + 1)
        raw += line
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError('response_size_limit')
        if not line:
            raise ValueError('stream_ended_early')
        text = line.decode('utf-8').rstrip('\r\n')
        if text.startswith('data:'):
            event_data.append(text[5:].lstrip(' '))
        elif not text and event_data:
            if dispatch('\n'.join(event_data)):
                return message, bytes(raw)
            event_data = []


def retry_delay(response, attempt):
    header = response.getheader('retry-after') if response is not None else None
    try:
        delay = float(header)
    except (TypeError, ValueError):
        delay = 2.0 ** attempt
    return min(max(delay, 0.0), MAX_RETRY_DELAY) if math.isfinite(delay) else MAX_RETRY_DELAY


def live_request(payload, timeout, model=None, pricing=None):
    key = os.getenv('ANTHROPIC_API_KEY')
    if not isinstance(key, str) or not key or any(not 33 <= ord(c) <= 126 for c in key):
        return failure(envelope(), 'invalid_api_key')
    retries = []
    for attempt in range(MAX_RETRIES + 1):
        connection = None; response = None
        try:
            connection = http.client.HTTPSConnection('api.anthropic.com', timeout=timeout)
            connection.request('POST', '/v1/messages', body=payload,
                               headers={'x-api-key': key, 'anthropic-version': API_VERSION,
                                        'Content-Type': 'application/json'})
            response = connection.getresponse()
            request_id = response.getheader('request-id')
            if response.status != 200:
                data = response.read(MAX_RESPONSE_BYTES + 1)
                if response.status in RETRY_STATUSES and attempt < MAX_RETRIES:
                    retries.append({'http_status': response.status})
                    delay = retry_delay(response, attempt)
                else:
                    result, code = translate_response(data, http_status=response.status, request_id=request_id,
                                                      model=model, pricing=pricing)
                    break
            else:
                # Once the stream starts the call may be billed, so it is never retried.
                try:
                    message, data = read_stream(response)
                except (ValueError, KeyError, TypeError, UnicodeError):
                    result, code = failure(envelope(), 'stream_error')
                    break
                result = envelope(); metadata = result['provider_metadata']
                metadata['response_sha256'] = digest(data)
                if isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,200}', request_id):
                    metadata['request_id'] = request_id
                result, code = translate_message(message, model=model, pricing=pricing, result=result)
                break
        except (OSError, http.client.HTTPException, ValueError, UnicodeError):
            # No response headers arrived, so nothing was generated or billed.
            if response is not None or attempt == MAX_RETRIES:
                result, code = failure(envelope(), 'transport_error')
                break
            retries.append({'transport_error': True})
            delay = retry_delay(None, attempt)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (OSError, http.client.HTTPException):
                    pass
        time.sleep(delay)
    if retries:
        result['provider_metadata']['retries'] = retries
    return result, code


def load_fixture(path):
    with Path(path).open('rb') as handle:
        data = handle.read(MAX_REQUEST_BYTES + 1)
    if len(data) > MAX_REQUEST_BYTES:
        raise ValueError('fixture_size_limit')
    value = strict_json(data.decode('utf-8'))
    if (not isinstance(value, dict) or set(value) != {'schema', 'model', 'responses'}
            or value['schema'] != 'talven.eval.anthropic-fixture.v1' or not identity(value['model'])
            or not isinstance(value['responses'], dict)):
        raise ValueError('invalid_fixture')
    for task, entries in value['responses'].items():
        if not isinstance(task, str) or not isinstance(entries, list):
            raise ValueError('invalid_fixture')
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {'http_status', 'request_id', 'body'}
                    or type(entry['http_status']) is not int or not 100 <= entry['http_status'] <= 599
                    or (entry['request_id'] is not None and not isinstance(entry['request_id'], str))
                    or not isinstance(entry['body'], dict)):
                raise ValueError('invalid_fixture')
    return value


def write_config(args):
    if not identity(args.model) or not identity(args.tokenizer):
        raise ValueError('explicit_model_and_tokenizer_required')
    if args.live and args.effort is None:
        raise ValueError('live_runs_require_explicit_effort')
    settings = {'max_tokens': args.max_tokens if args.max_tokens is not None else DEFAULT_MAX_TOKENS}
    for name in ('effort', 'temperature', 'top_p'):
        if getattr(args, name) is not None:
            settings[name] = getattr(args, name)
    if args.thinking:
        settings['thinking'] = 'adaptive'
    settings_valid(settings, args.model)
    script = Path(__file__).resolve(); root = script.parents[2]
    command = [str(Path(sys.executable).resolve()), str(script)]
    artifacts = [script, script.parent / '__init__.py', root / 'experiments/protocol.py', root / 'experiments/metrics.py']
    if args.fixture is not None:
        fixture = Path(args.fixture).resolve(strict=True)
        if load_fixture(fixture)['model'] != args.model:
            raise ValueError('fixture_model_mismatch')
        command += ['--fixture', str(fixture)]
        artifacts.append(fixture)
    else:
        command.append('--live')
    pricing = Path(args.pricing).resolve(strict=True)
    if args.live and args.model not in load_pricing(pricing)['models']:
        raise ValueError('model_missing_from_pricing_table')
    command += ['--timeout', str(args.timeout), '--pricing', str(pricing)]
    artifacts.append(pricing)
    config = {'schema': 'talven.eval.adapter.v1', 'kind': 'fixture' if args.fixture is not None else 'live',
              'provider': 'anthropic', 'model': args.model, 'tokenizer': args.tokenizer,
              'settings': settings, 'command': command, 'artifacts': list(map(str, artifacts))}
    target = Path(args.write_config)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as handle:
        handle.write(encode(config))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--live', action='store_true')
    modes.add_argument('--fixture')
    parser.add_argument('--write-config')
    parser.add_argument('--model')
    parser.add_argument('--tokenizer')
    parser.add_argument('--max-tokens', type=int)
    parser.add_argument('--effort', choices=EFFORTS)
    parser.add_argument('--thinking', action='store_true', help='Request adaptive thinking explicitly')
    parser.add_argument('--temperature', type=float)
    parser.add_argument('--top-p', type=float)
    parser.add_argument('--timeout', type=float, default=300,
                        help='Socket timeout in seconds for connecting and between streamed reads')
    parser.add_argument('--pricing', default=str(PRICING_PATH))
    args = parser.parse_args(argv)
    fixture = args.fixture is not None
    try:
        if fixture and not args.fixture:
            raise ValueError('empty_fixture_path')
        if not math.isfinite(args.timeout) or not 0 < args.timeout <= 600:
            raise ValueError('invalid_timeout')
        if args.write_config is not None:
            if not args.write_config:
                raise ValueError('empty_config_path')
            write_config(args)
            return 0
        if any(getattr(args, name) is not None for name in ('model', 'tokenizer', 'max_tokens', 'effort',
                                                             'temperature', 'top_p')) or args.thinking:
            raise ValueError('settings_belong_in_request')
        data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError('request_size_limit')
        request = strict_json(data.decode('utf-8'))
        payload = bounded_bytes(build_request(request), MAX_REQUEST_BYTES)
        model = request['model']['model']
        pricing = load_pricing(args.pricing)
        pricing['provenance'] = f"{Path(args.pricing).name} sha256:{digest(Path(args.pricing).read_bytes())}; {pricing['source']}"
        if fixture:
            responses = load_fixture(args.fixture)
            if responses['model'] != model:
                raise ValueError('fixture_model_mismatch')
            entries = responses['responses'].get(request['task_id'], [])
            if request['attempt'] >= len(entries):
                raise ValueError('fixture_exhausted')
            entry = entries[request['attempt']]
            result, code = translate_response(bounded_bytes(entry['body'], MAX_RESPONSE_BYTES),
                                             http_status=entry['http_status'], request_id=entry['request_id'],
                                             fixture=True, model=model, pricing=pricing)
        else:
            result, code = live_request(payload, args.timeout, model, pricing)
        result['provider_metadata']['request_sha256'] = digest(payload)
    except (ValueError, OSError, UnicodeError):
        result, code = failure(envelope(fixture), 'invalid_input_or_configuration')
    sys.stdout.write(encode(result))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
