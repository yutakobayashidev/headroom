import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import urllib.error

spec = importlib.util.spec_from_file_location('mistral', Path(__file__).parents[1] / 'providers/mistral/fetch.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

BUDGET = {'vibe_budget': {'usage_percentage': 42.5, 'initial_budget': 300,
                         'reset_at': '2026-12-01T00:00:00Z', 'payg_enabled': False},
          'api_budget': {'usage_percentage': 99}}

class MistralTest(unittest.TestCase):
    def failure(self, code, fn, *args):
        with self.assertRaises(m.Failure) as caught:
            fn(*args)
        self.assertEqual(caught.exception.code, code)

    def test_monthly_vibe_not_api(self):
        result = m.normalize(BUDGET)
        self.assertEqual(result, {'usedPercent': 42.5, 'resetsAt': 1796083200})
        self.assertEqual(m.normalize({'vibe_budget': {'usage_percentage': 110, 'initial_budget': 30}}),
                         {'usedPercent': 100, 'resetsAt': None})

    def test_bad_or_absent_allowance(self):
        self.failure('no_plan', m.normalize, {'vibe_budget': None})
        self.failure('no_plan', m.normalize, {'vibe_budget': {'usage_percentage': 0, 'initial_budget': 0}})
        for data in ({}, [], {'vibe_budget': {}}, {'vibe_budget': []}):
            self.failure('parse', m.normalize, data)
        for value in (True, -1, float('nan'), float('inf'), 'bad'):
            data = {'vibe_budget': dict(BUDGET['vibe_budget'], usage_percentage=value)}
            self.failure('parse', m.normalize, data)
        self.failure('parse', m.normalize, {'vibe_budget': dict(BUDGET['vibe_budget'], reset_at='not a date')})

    def test_env_precedes_keyring(self):
        with patch.dict(os.environ, {'MISTRAL_API_KEY': 'synthetic'}, clear=True), patch.object(m.subprocess, 'run') as run:
            self.assertEqual(m.credential(), 'synthetic')
            run.assert_not_called()

    def test_keyring_and_legacy(self):
        for legacy in (False, True):
            with patch.dict(os.environ, {}, clear=True), patch.object(m.subprocess, 'run') as run:
                run.side_effect = ([Mock(returncode=1, stdout='')] if legacy else []) + [Mock(returncode=0, stdout='synthetic\n')]
                self.assertEqual(m.credential(), 'synthetic')
                self.assertIn('vibe' if legacy else 'ai.mistral.vibe', run.call_args.args[0])

    def test_dotenv_and_no_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'VIBE_HOME': tmp}, clear=True), patch.object(m.subprocess, 'run', side_effect=FileNotFoundError):
            self.failure('not_configured', m.credential)
            path = Path(tmp) / '.env'
            for line in ("MISTRAL_API_KEY='synthetic'", 'export MISTRAL_API_KEY="synthetic" # comment', 'MISTRAL_API_KEY=synthetic # comment'):
                path.write_text(line)
                self.assertEqual(m.credential(), 'synthetic')
            path.write_text('OTHER_KEY=synthetic')
            self.failure('not_configured', m.credential)

    def test_request_and_http_failures(self):
        with patch.object(m, 'credential', return_value='synthetic'):
            opener = Mock()
            opener.open.return_value = io.BytesIO(json.dumps(BUDGET).encode())
            self.assertEqual(m.fetch(opener)['usedPercent'], 42.5)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.mistral.ai/v1/billing/budget')
            self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic')
            for status, code in ((401, 'auth'), (403, 'auth'), (404, 'server'), (429, 'rate_limited'), (500, 'server'), (302, 'server')):
                opener.open.side_effect = urllib.error.HTTPError(request.full_url, status, 'private', {}, None)
                self.failure(code, m.fetch, opener)
            opener.open.side_effect = urllib.error.URLError('private')
            self.failure('network', m.fetch, opener)
            opener.open.side_effect = None
            opener.open.return_value = io.BytesIO(b'not json')
            self.failure('parse', m.fetch, opener)

    def test_no_redirect_or_secret_output(self):
        self.assertIsNone(m.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test'))
        with patch.object(m, 'fetch', side_effect=RuntimeError('synthetic-secret')), patch('sys.stdout', new_callable=io.StringIO) as output:
            m.main()
            self.assertEqual(json.loads(output.getvalue()), {'error': 'parse'})

if __name__ == '__main__':
    unittest.main()
