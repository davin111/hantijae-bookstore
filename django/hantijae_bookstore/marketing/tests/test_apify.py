import json

import requests
from django.test import SimpleTestCase

from marketing.apify import Apify, ApifyAuthError, ApifyError


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class ApifyTest(SimpleTestCase):
    def test_start_run_sends_caps_and_keeps_token_out_of_url(self):
        s = FakeSession(FakeResponse(201, {'data': {'id': 'r1', 'status': 'RUNNING', 'defaultDatasetId': 'd1'}}))
        data = Apify('tok', session=s).start_run('apify~facebook-posts-scraper', {'resultsLimit': 5}, timeout=180,
                                                 max_items=10, max_charge_usd=0.15)
        method, url, kw = s.calls[0]
        self.assertEqual((method, url), ('POST', 'https://api.apify.com/v2/acts/apify~facebook-posts-scraper/runs'))
        self.assertEqual(kw['params'], {'timeout': 180, 'maxItems': 10, 'maxTotalChargeUsd': 0.15, 'waitForFinish': 45})
        self.assertEqual(kw['json'], {'resultsLimit': 5})
        self.assertEqual(kw['headers'], {'Authorization': 'Bearer tok'})
        self.assertNotIn('tok', url + json.dumps(kw['params']))
        self.assertEqual(data['id'], 'r1')

    def test_auth_error_vs_other_errors(self):
        with self.assertRaises(ApifyAuthError):
            Apify('t', session=FakeSession(FakeResponse(401, {}))).get_run('r')
        for bad in (FakeResponse(500, {'error': 'x'}), requests.ConnectionError('down')):
            with self.assertRaises(ApifyError) as cm:
                Apify('t', session=FakeSession(bad)).get_run('r')
            self.assertNotIsInstance(cm.exception, ApifyAuthError)

    def test_get_run_dataset_and_abort(self):
        s = FakeSession(FakeResponse(200, {'data': {'status': 'SUCCEEDED', 'usageTotalUsd': 0.05}}),
                        FakeResponse(200, [{'postId': '1'}]), FakeResponse(200, {'data': {'status': 'ABORTING'}}))
        client = Apify('t', session=s)
        self.assertEqual(client.get_run('r1')['status'], 'SUCCEEDED')
        self.assertEqual(client.dataset_items('d1'), [{'postId': '1'}])
        client.abort_run('r1')
        self.assertEqual([(m, u) for m, u, _ in s.calls], [
            ('GET', 'https://api.apify.com/v2/actor-runs/r1'), ('GET', 'https://api.apify.com/v2/datasets/d1/items'),
            ('POST', 'https://api.apify.com/v2/actor-runs/r1/abort')])
        self.assertEqual(s.calls[1][2]['params'], {'clean': 'true', 'format': 'json', 'limit': 500})
