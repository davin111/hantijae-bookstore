import importlib.util
import io
import json
import subprocess
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from django.conf import settings
from django.test import SimpleTestCase

PATH = Path(settings.BASE_DIR).parent.parent / 'scripts' / 'meta_ads_token.py'
_spec = importlib.util.spec_from_file_location('meta_ads_token', PATH)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

LONG = 'LONG-SECRET-TOKEN'
EXP, DATA = 1764460800, 1767052800   # 2025-11-30 00:00 UTC(KST 09:00), 2025-12-30 00:00 UTC


class Res:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


def graph(account_status=200):
    calls = []

    def get(url, params=None, timeout=None):
        path = url.split('/v26.0/', 1)[1]
        calls.append((path, params))
        if path == 'oauth/access_token':
            return Res(200, {'access_token': LONG, 'expires_in': 5183944})
        if path == 'debug_token':
            return Res(200, {'data': {'is_valid': True, 'app_id': 'APP', 'scopes': ['ads_read', 'pages_show_list'],
                                      'expires_at': EXP, 'data_access_expires_at': DATA}})
        if path == 'act_1':
            return Res(account_status, {'id': 'act_1', 'currency': 'KRW', 'timezone_name': 'Asia/Seoul'}
                       if account_status == 200 else {'error': {'code': 200}})
        raise AssertionError(path)
    get.calls = calls
    return get


class FakeSM:
    def __init__(self):
        self.data = {'META_APP_ID': 'APP', 'META_APP_SECRET': 'SEC', 'OTHER': 'keep'}
        self.put = None

    def get_secret_value(self, SecretId):
        return {'SecretString': json.dumps(self.data), 'VersionId': 'v-old'}

    def put_secret_value(self, SecretId, SecretString):
        self.put = json.loads(SecretString)
        return {'VersionId': 'v-new'}


class ScriptTest(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.file = Path(self.dir) / 't.txt'
        self.file.write_text('SHORT-SECRET\n')
        self.sm, self.runs = FakeSM(), []
        self.noon = datetime(2026, 10, 3, 3, 0, tzinfo=timezone.utc)   # KST 12:00

    def main(self, *extra, get=None, now=None):
        out, errs = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(errs):
            code = script.main(['--token-file', str(self.file), '--account', 'act_1', *extra], get=get or graph(),
                               sm=self.sm, run=lambda args, check: self.runs.append(args), now=now or self.noon)
        return code, out.getvalue() + errs.getvalue()

    def test_expiry_is_the_earlier_of_token_and_data_access_in_kst(self):
        self.assertEqual(script.expiry_date({'expires_at': EXP, 'data_access_expires_at': DATA}), date(2025, 11, 30))
        self.assertEqual(script.expiry_date({'expires_at': 0, 'data_access_expires_at': DATA}), date(2025, 12, 30))

    def test_dawn_window_in_kst(self):
        kst = lambda h, m: datetime(2026, 10, 3, h - 9 if h >= 9 else h + 15, m, tzinfo=timezone.utc)
        self.assertEqual([script.in_dawn(kst(h, m)) for h, m in ((4, 29), (4, 30), (7, 9), (7, 10))],
                         [False, True, True, False])

    def test_full_run_merges_three_keys_restarts_and_never_prints_tokens(self):
        code, text = self.main()
        self.assertEqual(code, 0)
        self.assertEqual({k: self.sm.put[k] for k in ('META_ADS_TOKEN', 'META_AD_ACCOUNT_ID', 'META_ADS_EXPIRES', 'OTHER')},
                         {'META_ADS_TOKEN': LONG, 'META_AD_ACCOUNT_ID': 'act_1', 'META_ADS_EXPIRES': '2025-11-30',
                          'OTHER': 'keep'})
        self.assertEqual(self.runs, [['ssh', 'hantijae-prod', script.RESTART]])
        self.assertIn('v-new', text)
        self.assertIn('v-old', text)
        self.assertNotIn('SECRET', text)
        self.assertFalse(self.file.exists())

    def test_check_saves_nothing(self):
        code, text = self.main('--check')
        self.assertEqual((code, self.sm.put, self.runs), (0, None, []))
        self.assertFalse(self.file.exists())

    def test_unreadable_ad_account_stops_before_saving(self):
        code, text = self.main(get=graph(account_status=400))
        self.assertEqual((code, self.sm.put), (1, None))
        self.assertNotIn('SECRET', text)
        self.assertFalse(self.file.exists())

    def test_a_bad_flag_still_deletes_the_token_file(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            script.main(['--token-file', str(self.file), '--no-restar'], get=graph(), sm=self.sm, run=None, now=self.noon)
        self.assertFalse(self.file.exists())
        self.assertIsNone(self.sm.put)

    def test_help_also_deletes_the_token_file(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            script.main(['--token-file', str(self.file), '--help'], get=graph(), sm=self.sm, run=None, now=self.noon)
        self.assertFalse(self.file.exists())

    def test_account_failure_names_the_step_not_the_account_number(self):
        code, text = self.main(get=graph(account_status=400))
        self.assertIn('광고 계정', text)
        self.assertNotIn('act_1', text)

    def test_dawn_refuses_before_touching_anything(self):
        get = graph()
        code, text = self.main(get=get, now=datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc))   # KST 05:00
        self.assertEqual((code, get.calls, self.sm.put), (1, [], None))
        self.assertIn('04:30~07:10', text)

    def test_account_comes_from_secrets_after_the_first_time(self):
        self.sm.data['META_AD_ACCOUNT_ID'] = 'act_1'
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = script.main(['--token-file', str(self.file), '--no-restart'], get=graph(), sm=self.sm,
                               run=lambda args, check: self.runs.append(args), now=self.noon)
        self.assertEqual((code, self.runs, self.sm.put['META_AD_ACCOUNT_ID']), (0, [], 'act_1'))

    def test_network_error_never_leaks_the_url_or_tokens(self):
        def get(url, params=None, timeout=None):
            raise requests.ConnectionError('https://graph.facebook.com/v26.0/oauth/access_token'
                                           '?fb_exchange_token=SHORT-SECRET&client_secret=SEC')
        code, text = self.main(get=get)
        self.assertEqual((code, self.sm.put), (1, None))
        for leak in ('SECRET', 'SEC&', 'client_secret'):
            self.assertNotIn(leak, text)
        self.assertFalse(self.file.exists())

    def test_restart_failure_after_save_says_so_and_how_to_restart(self):
        def run(args, check):
            raise subprocess.CalledProcessError(255, ['ssh'])
        out, errs = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(errs):
            code = script.main(['--token-file', str(self.file), '--account', 'act_1'], get=graph(), sm=self.sm,
                               run=run, now=self.noon)
        text = out.getvalue() + errs.getvalue()
        self.assertEqual(code, 1)
        self.assertIsNotNone(self.sm.put)
        self.assertIn(script.RESTART, text)
        self.assertNotIn('SECRET', text)
        self.assertFalse(self.file.exists())
