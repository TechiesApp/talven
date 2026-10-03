"""Synthetic Codex receipts and fake CLI processes; no model calls."""
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.adapters import codex_cli as adapter
from experiments.protocol import digest, encode


def events(text=None, usage=None, extra=()):
    text = text if text is not None else encode({'edits': {'task.tal': 'fn main() -> i32 { return 1; }'}})
    return '\n'.join(json.dumps(e) for e in [
        {'type': 'thread.started', 'thread_id': 'synthetic'}, {'type': 'turn.started'}, *extra,
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}},
        {'type': 'turn.completed', 'usage': usage if usage is not None else
         {'input_tokens': 120, 'cached_input_tokens': 100, 'output_tokens': 40}}])


def catalog():
    return {'models': [{'slug': 'fixture-model', 'supported_reasoning_levels': [{'effort': 'low'}],
                        'apply_patch_tool_type': 'freeform', 'experimental_supported_tools': ['clock'],
                        'tool_mode': 'code_mode_only'}]}


class CodexAdapterTests(unittest.TestCase):
    def test_receipt_tokens_are_retained_without_inventing_cost_or_snapshot(self):
        result, code = adapter.translate_events(events())
        self.assertEqual(0, code)
        self.assertEqual({'task.tal': 'fn main() -> i32 { return 1; }'}, result['edits'])
        self.assertEqual((120, 100, 40), tuple(result['usage'][k] for k in
                                             ('input_tokens', 'cached_input_tokens', 'output_tokens')))
        self.assertIsNone(result['usage']['model_cost_usd'])
        self.assertIsNone(result['usage']['cache_write_input_tokens'])
        self.assertIn('snapshot unavailable', result['provider_metadata']['model_identity'])

    def test_tools_failed_turns_and_multiple_completions_cannot_supply_edits(self):
        for extra in ([{'type': 'item.started', 'item': {'type': 'command_execution'}}],
                      [{'type': 'turn.failed', 'error': {'message': 'do not expose'}}],
                      [{'type': 'turn.completed', 'usage': {}}]):
            result, code = adapter.translate_events(events(extra=extra))
            self.assertEqual((2, {}), (code, result['edits']))
            self.assertNotIn('do not expose', encode(result))

    def test_usage_bounds_and_bad_candidates(self):
        for usage in ({'input_tokens': True, 'cached_input_tokens': 0, 'output_tokens': 1},
                      {'input_tokens': 1, 'cached_input_tokens': 2, 'output_tokens': 1},
                      {'input_tokens': 1, 'output_tokens': 1}):
            result, code = adapter.translate_events(events(usage=usage))
            self.assertEqual(2, code)
            self.assertIsNone(result['usage'])
        for text in ('not JSON', '{"edits":{"../outside":"bad"}}', '{"edits":{},"usage":{}}'):
            result, code = adapter.translate_events(events(text=text))
            self.assertEqual((0, {}), (code, result['edits']))
            self.assertEqual('invalid_source_edit', result['provider_metadata']['candidate_error'])
        with self.assertRaises(ValueError):
            adapter.translate_events('{"type":"turn.completed","type":"error"}')

    def test_catalog_removes_model_tools_without_changing_model_or_effort(self):
        raw = catalog()
        restricted = adapter.restricted_catalog(raw, 'fixture-model', 'low')
        row = restricted['models'][0]
        self.assertEqual('fixture-model', row['slug'])
        self.assertIsNone(row['apply_patch_tool_type'])
        self.assertEqual([], row['experimental_supported_tools'])
        self.assertEqual('direct', row['tool_mode'])
        self.assertEqual('freeform', raw['models'][0]['apply_patch_tool_type'])
        for model, effort in (('missing', 'low'), ('fixture-model', 'high')):
            with self.assertRaises(ValueError):
                adapter.restricted_catalog(raw, model, effort)

    @unittest.skipIf(sys.platform == 'win32', 'Fake executable requires POSIX')
    def test_fake_cli_receives_exact_guide_and_prompt_with_subscription_controls(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cli, log = directory / 'codex', directory / 'call.json'
            cli.write_text(f'''#!{sys.executable}
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
values=[args[i+1] for i,v in enumerate(args) if v=='-c']
system=json.loads(next(v.split('=',1)[1] for v in values if v.startswith('model_instructions_file=')))
Path({str(log)!r}).write_text(json.dumps({{'args':args,'system':Path(system).read_text(),'prompt':sys.stdin.read(),'api_key':os.environ.get('OPENAI_API_KEY'),'codex_key':os.environ.get('CODEX_API_KEY')}}))
print({events()!r})
''')
            cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
            path = directory / 'catalog.json'
            path.write_text(encode(adapter.restricted_catalog(catalog(), 'fixture-model', 'low')))
            request = {'schema': 'talven.eval.request.v1', 'corpus_version': 'm1-agent-tasks-v2',
                       'task_id': 'strict-type', 'context_mode': 'source', 'repetition': 1, 'attempt': 0,
                       'allowed_files': ['task.tal'], 'model': {'provider': 'openai-codex-cli',
                       'model': 'fixture-model', 'tokenizer': 'unavailable: synthetic', 'settings':
                       {'effort': 'low', 'cli_version': adapter.CLI_VERSION,
                        'cli_sha256': digest(cli.read_bytes()), 'catalog_sha256': digest(path.read_bytes())}},
                       'messages': [{'role': 'system', 'content': 'exact pinned guide\n'},
                                    {'role': 'user', 'content': 'exact task'}]}
            adapter.validate_request(request)
            with patch.dict('os.environ', {'OPENAI_API_KEY': 'must-not-pass', 'CODEX_API_KEY': 'must-not-pass'}):
                result, code = adapter.run(request, str(cli), path, 10)
            self.assertEqual(0, code)
            call = json.loads(log.read_text())
            self.assertEqual(('exact pinned guide\n', 'exact task', None, None),
                             (call['system'], call['prompt'], call['api_key'], call['codex_key']))
            for flag in ('--ignore-user-config', '--ephemeral', '--skip-git-repo-check', '--output-schema'):
                self.assertIn(flag, call['args'])
            self.assertIn('forced_login_method="chatgpt"', call['args'])
            self.assertIn('features.shell_tool=false', call['args'])
            path.write_text('{}')
            with self.assertRaises(ValueError):
                adapter.run(request, str(cli), path, 10)


if __name__ == '__main__':
    unittest.main()
