"""Apify API(실행 시작·상태·결과 읽기). HTTP만 하고 DB는 모른다.
토큰은 Authorization 헤더로만 보낸다 — 주소에 넣으면 서버·프록시 로그에 남는다.
비용 상한(maxTotalChargeUsd)·결과 수(maxItems)·시간(timeout)은 콘솔 설정과 따로라 호출마다 붙여야 한다."""
import requests

BASE = 'https://api.apify.com/v2'
FINAL = ('SUCCEEDED', 'FAILED', 'TIMED-OUT', 'ABORTED')


class ApifyError(Exception):
    pass


class ApifyAuthError(ApifyError):
    """401/403 — 토큰 문제. 다시 해도 소용없다."""


class Apify:
    def __init__(self, token, session=None, timeout=70):
        self.token, self.session, self.timeout = token, session or requests.Session(), timeout

    def _call(self, method, path, **kw):
        try:
            res = self.session.request(method, BASE + path, headers={'Authorization': f'Bearer {self.token}'},
                                       timeout=self.timeout, **kw)
        except requests.RequestException as e:
            raise ApifyError(f'network: {e}') from e
        if res.status_code in (401, 403):
            raise ApifyAuthError(f'HTTP {res.status_code}')
        if res.status_code >= 400:
            raise ApifyError(f'HTTP {res.status_code}: {res.text[:200]}')
        return res.json()

    def start_run(self, actor, run_input, *, timeout, max_items, max_charge_usd, wait=45):
        """실행을 시작하고 최대 wait초 기다린다. 끝났으면 status가 FINAL 가운데 하나다."""
        params = {'timeout': timeout, 'maxItems': max_items, 'maxTotalChargeUsd': max_charge_usd,
                  'waitForFinish': wait}
        return self._call('POST', f'/acts/{actor}/runs', params=params, json=run_input)['data']

    def get_run(self, run_id):
        return self._call('GET', f'/actor-runs/{run_id}')['data']

    def abort_run(self, run_id):
        return self._call('POST', f'/actor-runs/{run_id}/abort')['data']

    def dataset_items(self, dataset_id, limit=500):
        return self._call('GET', f'/datasets/{dataset_id}/items', params={'clean': 'true', 'format': 'json',
                                                                         'limit': limit})
