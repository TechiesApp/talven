"""Offline adapter contracts; all provider receipts and transports are synthetic."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from experiments.adapters import anthropic_messages as adapter
from experiments.protocol import encode


def request():
    return dict(schema='talven.eval.request.v1', corpus_version='m1c-agent-tasks-v1',
                task_id='strict-type', context_mode='source', repetition=1, attempt=0,
                allowed_files=['task.tal'], model=dict(provider='anthropic', model='fixture-messages-v1',
                tokenizer='unavailable: offline test', settings={'max_tokens': 200}),
                messages=[{'role': 'system', 'content': 'exact system\n'},
                          {'role': 'user', 'content': 'source'},
                          {'role': 'assistant', 'content': 'previous output'},
                          {'role': 'user', 'content': 'repair feedback'}])


def response():
    return dict(type='message', id='msg_test', model='fixture-messages-v1', role='assistant',
                stop_reason='end_turn', content=[{'type': 'text', 'text': '{"edits":{"task.tal":"source"}}'}],
                usage=dict(input_tokens=10, cache_creation_input_tokens=20, cache_read_input_tokens=30,
                           output_tokens=40, thinking_tokens=999))


def sse(*events):
    return [line for event in events
            for line in (f"event: {event['type']}\n".encode(), f"data: {json.dumps(event)}\n".encode(), b"\n")] + [b""]


def streamed(text='{"edits":{"task.tal":"source"}}', stop='end_turn'):
    return sse({'type': 'message_start', 'message': {'id': 'msg_live', 'type': 'message', 'role': 'assistant',
                'model': 'fixture-messages-v1', 'content': [], 'usage': {'input_tokens': 10,
                'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 1}}},
               {'type': 'ping'},
               {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''}},
               {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'signature_delta', 'signature': 'sig'}},
               {'type': 'content_block_stop', 'index': 0},
               {'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'text', 'text': ''}},
               {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': text[:9]}},
               {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': text[9:]}},
               {'type': 'content_block_stop', 'index': 1},
               {'type': 'message_delta', 'delta': {'stop_reason': stop}, 'usage': {'output_tokens': 40}},
               {'type': 'message_stop'})


class AdapterTests(unittest.TestCase):
    def translate(self, body=None, **kwargs):
        return adapter.translate_response(encode(body if body is not None else response()).encode(), **kwargs)

    def invoke(self, args, req=None):
        output = io.StringIO()
        stdin = Mock(buffer=io.BytesIO(encode(req if req is not None else request()).encode()))
        with patch.object(adapter.sys, 'stdin', stdin), patch.object(adapter.sys, 'stdout', output):
            code = adapter.main(args)
        return code, json.loads(output.getvalue()) if output.getvalue() else None

    def test_exact_translation_and_immutability(self):
        req = request()
        req['model']['settings']['temperature'] = 0.2
        original = copy.deepcopy(req)
        payload = adapter.build_request(req)
        self.assertEqual(req, original)
        self.assertEqual(payload['system'], req['messages'][0]['content'])
        self.assertEqual(payload['messages'], req['messages'][1:])
        self.assertEqual(set(payload), {'model', 'max_tokens', 'temperature', 'system', 'messages', 'stream', 'output_config'})
        schema = payload['output_config']['format']['schema']
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['properties']['edits']['required'], ['task.tal'])
        self.assertTrue(payload['stream'])
        req = request(); req['model']['settings'].update(effort='high', thinking='adaptive')
        payload = adapter.build_request(req)
        self.assertEqual('high', payload['output_config']['effort'])
        self.assertEqual({'type': 'adaptive'}, payload['thinking'])

    def test_current_models_reject_sampling_and_accept_effort(self):
        for model in ('claude-opus-5-5', 'claude-opus-5', 'claude-sonnet-5', 'claude-fable-5-1', 'claude-opus-4-8'):
            req = request(); req['model']['model'] = model
            req['model']['settings'] = {'max_tokens': 1000, 'temperature': 0}
            with self.subTest(model=model), self.assertRaisesRegex(ValueError, 'sampling_unsupported'):
                adapter.build_request(req)
        req = request(); req['model']['settings'] = {'max_tokens': 1000, 'effort': 'extreme'}
        with self.assertRaisesRegex(ValueError, 'invalid_effort'):
            adapter.build_request(req)

    def test_pricing_table_prices_each_token_class(self):
        pricing = adapter.load_pricing()
        pricing['provenance'] = 'test'
        receipt = dict(input_tokens=1_000_000, cache_creation_input_tokens=3_000_000,
                       cache_read_input_tokens=1_000_000, output_tokens=1_000_000,
                       cache_creation={'ephemeral_5m_input_tokens': 2_000_000, 'ephemeral_1h_input_tokens': 1_000_000})
        # Opus 5.5: 4 input + 2*5 + 1*8 writes + 0.2 read + 20 output.
        self.assertEqual('42.2', adapter.model_cost(receipt, 'claude-opus-5-5', pricing))
        self.assertIsNone(adapter.model_cost(receipt, 'unpriced-model', pricing))
        receipt['cache_creation'] = {}
        self.assertIsNone(adapter.model_cost(receipt, 'claude-opus-5-5', pricing))
        usage, malformed = adapter.receipt_usage(dict(input_tokens=10, cache_creation_input_tokens=0,
                                                      cache_read_input_tokens=5, output_tokens=7),
                                                 False, {}, 'claude-haiku-4-5', pricing)
        self.assertFalse(malformed)
        self.assertEqual(('0.0000455', 'test', 0, 5, 15), (usage['model_cost_usd'], usage['model_cost_source'],
                         usage['cache_write_input_tokens'], usage['cached_input_tokens'], usage['input_tokens']))

    def test_invalid_request_never_reads_key_or_connects(self):
        cases = []
        for key, value in [('attempt', True), ('attempt', 21), ('repetition', 0), ('context_mode', 'other'),
                           ('task_id', 'absent'), ('allowed_files', ['other']), ('extra', 0)]:
            req = request(); req[key] = value; cases.append(req)
        for settings in [{'max_tokens': True}, {'max_tokens': 0}, {'max_tokens': 128001},
                         {'max_tokens': 1, 'temperature': float('inf')}, {'max_tokens': 1, 'top_p': -1},
                         {'max_tokens': 1, 'temperature': 0, 'top_p': 1}, {'max_tokens': 1, 'tools': []}]:
            req = request(); req['model']['settings'] = settings; cases.append(req)
        for messages in [[], [{'role': 'user', 'content': 'x'}], request()['messages'][:-1],
                         [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': ''}]]:
            req = request(); req['messages'] = messages; cases.append(req)
        with patch.object(adapter.os, 'getenv', side_effect=AssertionError('credential path')), \
             patch.object(adapter.http.client, 'HTTPSConnection', side_effect=AssertionError('network')):
            for req in cases:
                with self.subTest(req=req):
                    with self.assertRaises(ValueError): adapter.build_request(req)
            req = request(); req['attempt'] = 99
            self.assertEqual(self.invoke(['--live'], req)[0], 2)

    def test_accounting_no_double_count_and_fixture(self):
        envelope, code = self.translate()
        self.assertEqual(code, 0)
        self.assertEqual(envelope['usage']['input_tokens'], 60)
        self.assertEqual(envelope['usage']['cached_input_tokens'], 30)
        self.assertEqual(envelope['usage']['output_tokens'], 40)
        self.assertIsNone(envelope['usage']['model_cost_usd'])
        self.assertIsNone(envelope['usage']['tool_cost_usd'])
        envelope, code = self.translate(fixture=True)
        self.assertIsNone(envelope['usage'])
        self.assertTrue(envelope['provider_metadata']['synthetic'])

    def test_partial_and_malformed_usage_preserves_independent_output(self):
        for missing in ['input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens']:
            body = response(); del body['usage'][missing]
            envelope, code = self.translate(body)
            self.assertEqual(code, 0)
            self.assertIsNone(envelope['usage']['input_tokens'])
            self.assertIsNone(envelope['usage']['cached_input_tokens'])
            self.assertEqual(envelope['usage']['output_tokens'], 40)
        for invalid in [True, -1, 10**12 + 1, '1']:
            body = response(); body['usage']['input_tokens'] = invalid
            envelope, code = self.translate(body)
            self.assertEqual(code, 2)
            self.assertEqual(envelope['usage']['output_tokens'], 40)
            self.assertIsNone(envelope['usage']['input_tokens'])
        body = response(); del body['usage']
        self.assertIsNone(self.translate(body)[0]['usage'])
        body = response(); body['usage'] = dict.fromkeys(body['usage'], 0)
        self.assertEqual(self.translate(body)[0]['usage']['input_tokens'], 0)

    def test_thinking_and_text_chunks(self):
        body = response(); body['content'] = [dict(type='thinking', thinking='private', signature='x'),
            dict(type='text', text='{"edits":'), dict(type='redacted_thinking', data='x'),
            dict(type='text', text='{"task.tal":"ok"}}')]
        env, code = self.translate(body)
        self.assertEqual((code, env['edits']), (0, {'task.tal': 'ok'}))
        self.assertNotIn('private', encode(env))

    def test_provider_failures_keep_receipt(self):
        cases = []
        for reason in ['tool_use', 'pause_turn', 'model_context_window_exceeded', 'stop_sequence', None]:
            body = response(); body['stop_reason'] = reason; cases.append(body)
        for block in [dict(type='tool_use'), dict(type='server_tool_use'), dict(type='refusal'), dict(type='unknown'), dict(type='text', text=1)]:
            body = response(); body['content'] = [block]; cases.append(body)
        body = response(); body['stop_details'] = {'type': 'refusal'}; cases.append(body)
        for body in cases:
            env, code = self.translate(body)
            self.assertEqual(code, 2)
            self.assertEqual(env['usage']['output_tokens'], 40)
            self.assertEqual(env['edits'], {})
        env, code = self.translate(http_status=401)
        self.assertEqual(code, 2); self.assertEqual(env['usage']['input_tokens'], 60)

    def test_cut_off_or_refused_answers_are_repairable_model_failures(self):
        for reason in adapter.MODEL_FAILURES:
            body = response(); body['stop_reason'] = reason
            if reason == 'refusal':
                body['stop_details'] = {'type': 'refusal', 'category': None, 'explanation': None}
            env, code = self.translate(body)
            self.assertEqual((0, {}), (code, env['edits']))
            self.assertEqual(reason, env['provider_metadata']['model_failure'])
            self.assertEqual(40, env['usage']['output_tokens'])
        body = response(); body['stop_details'] = {'type': 'refusal'}
        self.assertEqual(2, self.translate(body)[1])

    def test_candidate_failure_repairable_and_cannot_forge_usage(self):
        for candidate in ['not json', '{"edits":{},"usage":{"output_tokens":999}}', '{"edits":{"task.tal":1}}',
                          '{"edits":{"other":"x"}}', '{"edits":{},"edits":{}}']:
            body = response(); body['content'][0]['text'] = candidate
            env, code = self.translate(body)
            self.assertEqual(code, 0); self.assertEqual(env['edits'], {})
            self.assertIn('candidate_error', env['provider_metadata'])
            self.assertEqual(env['usage']['output_tokens'], 40)

    def test_fixed_transport_and_http_errors_sanitized(self):
        connection = Mock(); result = connection.getresponse.return_value
        result.status = 200; result.getheader.return_value = 'req_test'; result.readline.side_effect = streamed()
        with patch.object(adapter.http.client, 'HTTPSConnection', return_value=connection) as factory, \
             patch.object(adapter.os, 'getenv', return_value='fake-test-key'):
            code, env = self.invoke(['--live', '--timeout', '12'])
            self.assertEqual(code, 0)
            factory.assert_called_once_with('api.anthropic.com', timeout=12.0)
            args, kwargs = connection.request.call_args
            self.assertEqual(args[:2], ('POST', '/v1/messages'))
            self.assertTrue(json.loads(kwargs['body'])['stream'])
            self.assertEqual(kwargs['headers'], {'x-api-key': 'fake-test-key', 'anthropic-version': '2023-06-01', 'Content-Type': 'application/json'})
            connection.request.assert_called_once(); connection.close.assert_called_once()
            self.assertEqual({'task.tal': 'source'}, env['edits'])
            self.assertEqual((10, 40, 'msg_live', 'req_test'), (env['usage']['input_tokens'], env['usage']['output_tokens'],
                             env['provider_metadata']['response_id'], env['provider_metadata']['request_id']))
            self.assertIn('request_sha256', env['provider_metadata'])
        result.readline.side_effect = streamed()[:-3] + [b""]  # Ends before message_stop.
        with patch.object(adapter.http.client, 'HTTPSConnection', return_value=connection), \
             patch.object(adapter.os, 'getenv', return_value='fake-test-key'):
            code, env = self.invoke(['--live'])
            self.assertEqual((2, 'stream_error'), (code, env['provider_metadata']['error']))
        connection.reset_mock(); result.status = 401
        result.read.return_value = b'{"type":"error","error":{"message":"fake-test-key"}}'
        with patch.object(adapter.http.client, 'HTTPSConnection', return_value=connection), patch.object(adapter.os, 'getenv', return_value='fake-test-key'):
            code, env = self.invoke(['--live'])
            self.assertEqual(code, 2); self.assertNotIn('fake-test-key', encode(env))
            connection.request.assert_called_once()

    def test_network_errors_bounds_and_key_validation(self):
        with patch.object(adapter.http.client, 'HTTPSConnection', side_effect=OSError('fake-secret')) as factory, \
             patch.object(adapter.os, 'getenv', return_value='fake-test-key'), \
             patch.object(adapter.time, 'sleep') as sleep:
            code, env = self.invoke(['--live'])
            self.assertEqual(code, 2); self.assertNotIn('fake-secret', encode(env))
            # Connection failures send nothing billable, so they are retried with backoff.
            self.assertEqual(adapter.MAX_RETRIES + 1, factory.call_count)
            self.assertEqual([1.0, 2.0, 4.0], [call.args[0] for call in sleep.call_args_list])
            self.assertEqual(adapter.MAX_RETRIES, len(env['provider_metadata']['retries']))
        for key in ['', ' ', 'bad key', 'bad\nkey', 'é']:
            with patch.object(adapter.os, 'getenv', return_value=key), patch.object(adapter.http.client, 'HTTPSConnection') as factory:
                self.assertEqual(self.invoke(['--live'])[0], 2); factory.assert_not_called()
        self.assertEqual(adapter.translate_response(b'x' * (adapter.MAX_RESPONSE_BYTES + 1))[1], 2)
        req = request(); req['messages'][1]['content'] = 'x' * adapter.MAX_REQUEST_BYTES
        with self.assertRaises(ValueError): adapter.build_request(req)

    def test_overload_is_retried_after_the_server_delay(self):
        overloaded, ok = Mock(), Mock()
        overloaded.status = 529; overloaded.read.return_value = b'{"type":"error"}'
        overloaded.getheader.side_effect = lambda name: {'retry-after': '7'}.get(name)
        ok.status = 200; ok.getheader.return_value = 'req_ok'; ok.readline.side_effect = streamed()
        connection = Mock(); connection.getresponse.side_effect = [overloaded, ok]
        with patch.object(adapter.http.client, 'HTTPSConnection', return_value=connection), \
             patch.object(adapter.os, 'getenv', return_value='fake-key'), \
             patch.object(adapter.time, 'sleep') as sleep:
            code, env = self.invoke(['--live'])
        self.assertEqual(0, code)
        sleep.assert_called_once_with(7.0)
        self.assertEqual([{'http_status': 529}], env['provider_metadata']['retries'])

    def test_redirect_read_error_and_response_cap_never_retry(self):
        for status, data, error in [(302, encode(response()).encode(), None),
                                     (200, b'x' * (adapter.MAX_RESPONSE_BYTES + 1), None),
                                     (200, b'', OSError('fake-key'))]:
            connection = Mock(); result = connection.getresponse.return_value
            result.status = status; result.getheader.return_value = 'unsafe header\n'
            result.read.return_value = data; result.read.side_effect = error
            with patch.object(adapter.os, 'getenv', return_value='fake-key'), \
                 patch.object(adapter.http.client, 'HTTPSConnection', return_value=connection):
                code, env = self.invoke(['--live'])
            self.assertEqual(code, 2)
            connection.request.assert_called_once(); connection.close.assert_called_once()
            self.assertNotIn('fake-key', encode(env))
            self.assertNotIn('request_id', env['provider_metadata'])

    def test_cli_rejects_bad_mode_timeout_and_oversized_stdin_before_key(self):
        with patch.object(adapter.os, 'getenv', side_effect=AssertionError('key')), \
             patch.object(adapter.http.client, 'HTTPSConnection', side_effect=AssertionError('network')):
            self.assertEqual(self.invoke(['--fixture', ''])[0], 2)
            for args in [[], ['--live', '--fixture', 'unused']]:
                with patch.object(adapter.sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit):
                    adapter.main(args)
            for timeout in ['nan', 'inf', '0', '-1', '601']:
                self.assertEqual(self.invoke(['--live', '--timeout', timeout])[0], 2)
            stdin = Mock(buffer=io.BytesIO(b'x' * (adapter.MAX_REQUEST_BYTES + 1)))
            with patch.object(adapter.sys, 'stdin', stdin), patch.object(adapter.sys, 'stdout', io.StringIO()):
                self.assertEqual(adapter.main(['--live']), 2)

    def test_usage_limits_breakdown_and_sanitized_metadata(self):
        body = response()
        body['usage']['cache_creation'] = {'ephemeral_5m_input_tokens': 7, 'ephemeral_1h_input_tokens': 13, 'secret': 'fake-key'}
        body['usage']['arbitrary'] = 'fake-key'
        body['usage']['output_tokens_details'] = {'thinking_tokens': 5}
        env, code = self.translate(body, request_id='unsafe key!')
        self.assertEqual(code, 0); self.assertEqual(env['usage']['input_tokens'], 60)
        self.assertEqual(env['provider_metadata']['usage_receipt']['output_tokens_details'], {'thinking_tokens': 5})
        self.assertEqual(env['usage']['output_tokens'], 40)
        self.assertNotIn('fake-key', encode(env)); self.assertNotIn('request_id', env['provider_metadata'])
        body['usage']['input_tokens'] = 10**12
        env, code = self.translate(body)
        self.assertEqual(code, 2); self.assertIsNone(env['usage']['input_tokens'])
        self.assertEqual(env['usage']['output_tokens'], 40)
        body = response(); body['usage']['output_tokens_details'] = {'thinking_tokens': True}
        env, code = self.translate(body)
        self.assertEqual(code, 2); self.assertEqual(env['usage']['output_tokens'], 40)
        body = response(); body['usage']['cache_creation'] = {'ephemeral_5m_input_tokens': True}
        env, code = self.translate(body)
        self.assertEqual(code, 2); self.assertEqual(env['usage']['input_tokens'], 60)
        self.assertEqual(env['usage']['output_tokens'], 40)

    def test_empty_config_path_never_executes_request(self):
        for mode in [['--live'], ['--fixture', 'unused-fixture.json']]:
            with self.subTest(mode=mode), \
                 patch.object(adapter.os, 'getenv', side_effect=AssertionError('credential path')) as key, \
                 patch.object(adapter.http.client, 'HTTPSConnection', side_effect=AssertionError('network')) as network, \
                 patch.object(adapter.sys, 'stdin') as stdin, \
                 patch.object(adapter.sys, 'stdout', io.StringIO()):
                stdin.buffer.read.side_effect = AssertionError('stdin')
                self.assertEqual(adapter.main([*mode, '--write-config', '']), 2)
                stdin.buffer.read.assert_not_called()
                key.assert_not_called()
                network.assert_not_called()

    def test_live_config_and_malformed_fixture_are_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'new' / 'live.json'
            fixture = Path(directory) / 'fixture.json'
            fixture.write_text('{"schema":"invalid"}')
            with patch.object(adapter.os, 'getenv', side_effect=AssertionError('key')), \
                 patch.object(adapter.http.client, 'HTTPSConnection', side_effect=AssertionError('network')):
                base = ['--live', '--write-config', str(target), '--tokenizer', 'unavailable:test']
                for extra in (['--model', 'claude-opus-5-5'],  # Live runs pin effort explicitly.
                              ['--model', 'claude-opus-5-5', '--effort', 'high', '--top-p', '0.5'],
                              ['--model', 'unpriced-model', '--effort', 'high']):
                    self.assertEqual(self.invoke(base + extra)[0], 2)
                    self.assertFalse(target.exists())
                self.assertEqual(self.invoke(base + ['--model', 'claude-opus-5-5', '--effort', 'high'])[0], 0)
                config = json.loads(target.read_text())
                self.assertEqual(config['settings'], {'max_tokens': 32000, 'effort': 'high'})
                self.assertIn(str(adapter.PRICING_PATH), config['artifacts'])
                self.assertEqual(config['provider'], 'anthropic'); self.assertEqual(config['kind'], 'live')
                self.assertEqual(self.invoke(['--fixture', str(fixture)])[0], 2)
                fixture.write_bytes(b'x' * (adapter.MAX_REQUEST_BYTES + 1))
                self.assertEqual(self.invoke(['--fixture', str(fixture)])[0], 2)

    def test_fixture_and_config_without_credentials_or_network(self):
        fixture = Path(__file__).parent / 'fixtures' / 'anthropic_messages.json'
        temporary_root = tempfile.gettempdir()  # Resolve before the credential-access guard.
        with patch.object(adapter.os, 'getenv', side_effect=AssertionError('credential path')), \
             patch.object(adapter.http.client, 'HTTPSConnection', side_effect=AssertionError('network')):
            code, env = self.invoke(['--fixture', str(fixture)])
            self.assertEqual(code, 0); self.assertIsNone(env['usage'])
            req = request(); req['attempt'] = 20
            self.assertEqual(self.invoke(['--fixture', str(fixture)], req)[0], 2)
            req = request(); req['model']['model'] = 'mismatch'
            self.assertEqual(self.invoke(['--fixture', str(fixture)], req)[0], 2)
            with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
                dest = Path(directory) / 'config.json'
                args = ['--fixture', str(fixture), '--write-config', str(dest), '--model', 'fixture-messages-v1', '--tokenizer', 'unavailable:test']
                with patch.object(adapter.sys, 'stdin', Mock(read=Mock(side_effect=AssertionError('stdin')))):
                    self.assertEqual(adapter.main(args), 0)
                config = json.loads(dest.read_text())
                self.assertEqual(config['kind'], 'fixture')
                self.assertTrue(all(Path(p).is_absolute() for p in config['artifacts']))
                self.assertNotIn('--model', config['command'])
                self.assertEqual(self.invoke(args)[0], 2)


if __name__ == '__main__':
    unittest.main()
