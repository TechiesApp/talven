"""Offline Claude Code CLI adapter contracts; a fake `claude` stands in for the CLI."""
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from experiments.adapters import claude_code_cli as adapter
from experiments.protocol import encode

FAKE_CLI = '''#!{python}
import json, os, sys
prompt = sys.stdin.read()
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "w") as log:
    json.dump({{"args": args, "prompt": prompt, "api_key": os.environ.get("ANTHROPIC_API_KEY")}}, log)
mode = os.environ.get("FAKE_MODE", "ok")
usage = {{"input_tokens": 2, "cache_creation_input_tokens": 1029, "cache_read_input_tokens": 0,
          "output_tokens": 76, "cache_creation": {{"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 1029}}}}
result = {{"type": "result", "subtype": "success", "is_error": False, "stop_reason": "end_turn",
           "session_id": "s1", "usage": usage, "total_cost_usd": 0.00976,
           "modelUsage": {{args[args.index("--model") + 1]: {{"costUSD": 0.00976}}}},
           "structured_output": {{"edits": {{"task.tal": "fn main() -> i32 {{ return 1; }}"}}}},
           "result": "{{}}"}}
if mode == "max_tokens":
    result["stop_reason"] = "max_tokens"; result.pop("structured_output")
if mode == "error":
    result.update(subtype="error_during_execution", is_error=True)
if mode == "other-model":
    result["modelUsage"] = {{"claude-haiku-4-5": {{}}}}
print(json.dumps(result))
'''


def request(**changes):
    value = dict(schema='talven.eval.request.v1', corpus_version='m1-agent-tasks-v2', task_id='strict-type',
                 context_mode='source', repetition=1, attempt=0, allowed_files=['task.tal'],
                 model=dict(provider='anthropic-claude-code-cli', model='claude-opus-5-5',
                            tokenizer='unavailable: test', settings={'effort': 'high'}),
                 messages=[{'role': 'system', 'content': 'exact system\n'}, {'role': 'user', 'content': 'task'}])
    value.update(changes)
    return value


@unittest.skipIf(sys.platform == 'win32', 'The fake CLI is a POSIX script')
class ClaudeCodeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.cli = self.directory / 'claude'
        self.cli.write_text(FAKE_CLI.format(python=sys.executable))
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        self.log = self.directory / 'log.json'

    def invoke(self, req=None, mode='ok'):
        output = io.StringIO()
        stdin = Mock(buffer=io.BytesIO(encode(req or request()).encode()))
        environment = {'FAKE_LOG': str(self.log), 'FAKE_MODE': mode, 'ANTHROPIC_API_KEY': 'must-not-pass'}
        with patch.dict(os.environ, environment), patch.object(adapter.sys, 'stdin', stdin), \
             patch.object(adapter.sys, 'stdout', output):
            code = adapter.main(['--claude', str(self.cli)])
        return code, json.loads(output.getvalue())

    def test_isolated_invocation_prices_usage_and_returns_the_edit(self):
        code, envelope = self.invoke()
        self.assertEqual(0, code)
        self.assertEqual({'task.tal': 'fn main() -> i32 { return 1; }'}, envelope['edits'])
        call = json.loads(self.log.read_text())
        args = call['args']
        for flag in ('-p', '--safe-mode', '--no-session-persistence'):
            self.assertIn(flag, args)
        self.assertEqual('', args[args.index('--tools') + 1])
        self.assertEqual(('claude-opus-5-5', 'high', 'exact system\n'),
                         (args[args.index('--model') + 1], args[args.index('--effort') + 1],
                          args[args.index('--system-prompt') + 1]))
        self.assertIsNone(call['api_key'])  # The subscription login, never an API key.
        self.assertEqual('task', call['prompt'])
        usage = envelope['usage']
        # Opus 5.5 list prices reproduce the CLI's own estimate.
        self.assertEqual(('0.00976', 1031, 1029), (usage['model_cost_usd'], usage['input_tokens'],
                                                   usage['cache_write_input_tokens']))
        self.assertIn('subscription', usage['model_cost_source'])
        self.assertEqual(0.00976, envelope['provider_metadata']['cli_list_cost_usd'])

    def test_repairs_render_the_conversation_into_one_message(self):
        messages = [{'role': 'system', 'content': 'sys'}, {'role': 'user', 'content': 'first'},
                    {'role': 'assistant', 'content': 'answer'}, {'role': 'user', 'content': 'feedback'}]
        self.invoke(request(messages=messages, attempt=1))
        prompt = json.loads(self.log.read_text())['prompt']
        self.assertTrue(prompt.startswith(adapter.TRANSCRIPT_HEADER))
        self.assertLess(prompt.index('[Runner]\nfirst'), prompt.index('[You]\nanswer'))
        self.assertTrue(prompt.endswith('[Runner, current message]\nfeedback'))

    def test_cut_off_errors_and_model_mismatch(self):
        code, envelope = self.invoke(mode='max_tokens')
        self.assertEqual((0, {}, 'max_tokens'), (code, envelope['edits'], envelope['provider_metadata']['model_failure']))
        self.assertEqual(2, self.invoke(mode='error')[0])
        code, envelope = self.invoke(mode='other-model')
        self.assertEqual((2, 'unexpected_model'), (code, envelope['provider_metadata']['error']))

    def test_models_without_effort_omit_the_flag(self):
        req = request(model=dict(provider='anthropic-claude-code-cli', model='claude-haiku-4-5',
                                 tokenizer='unavailable: test', settings={}))
        code, envelope = self.invoke(req)
        self.assertEqual(0, code)
        self.assertNotIn('--effort', json.loads(self.log.read_text())['args'])
        self.log.unlink()
        req['model']['settings'] = {'effort': 'low'}
        self.assertEqual(2, self.invoke(req)[0])
        self.assertFalse(self.log.exists())

    def test_invalid_requests_never_launch_the_cli(self):
        for req in (request(model=dict(provider='anthropic', model='m', tokenizer='t', settings={'effort': 'high'})),
                    request(model=dict(provider='anthropic-claude-code-cli', model='m', tokenizer='t', settings={})),
                    request(task_id='absent')):
            with self.subTest(req=req['model']):
                self.assertEqual(2, self.invoke(req)[0])
                self.assertFalse(self.log.exists())

    def test_config_requires_model_effort_and_pricing(self):
        target = self.directory / 'config.json'
        base = ['--write-config', str(target), '--claude', str(self.cli)]
        for args in ([], ['--model', 'claude-opus-5-5'], ['--model', 'unpriced', '--effort', 'high'],
                     ['--model', 'claude-haiku-4-5', '--effort', 'low']):
            with patch.object(adapter.sys, 'stdout', io.StringIO()):
                self.assertEqual(2, adapter.main(base + args))
            self.assertFalse(target.exists())
        with patch.object(adapter.sys, 'stdout', io.StringIO()):
            self.assertEqual(0, adapter.main(base + ['--model', 'claude-opus-5-5', '--effort', 'high']))
        config = json.loads(target.read_text())
        self.assertEqual(('live', 'anthropic-claude-code-cli', {'effort': 'high'}),
                         (config['kind'], config['provider'], config['settings']))


if __name__ == '__main__':
    unittest.main()
