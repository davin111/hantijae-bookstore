from datetime import date
from types import SimpleNamespace

import requests
from django.test import SimpleTestCase

from marketing import search


class Resp:
    def __init__(self, status, rows):
        self.status_code, self._rows = status, rows

    def json(self):
        return {'rows': self._rows}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(str(self.status_code))


class Session:
    """rows_by_dims: dimensions 튜플 → rows. calls에 (주소, json)을 적는다."""

    def __init__(self, rows_by_dims, status=200):
        self.rows, self.status, self.calls = rows_by_dims, status, []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        return Resp(self.status, self.rows.get(tuple(json.get('dimensions') or ()), []))


class WeekLineTest(SimpleTestCase):
    def test_line_with_top_queries(self):
        s = Session({(): [{'clicks': 8, 'impressions': 120}],
                     ('query',): [{'keys': ['한티재'], 'clicks': 3, 'impressions': 40},
                                  {'keys': ['커밍아웃 스토리'], 'clicks': 2, 'impressions': 15}]})
        line = search.week_line(date(2026, 10, 5), session=s)
        self.assertEqual(line, '지난 7일 구글 검색: 노출 120·클릭 8. 많이 찾은 말: 한티재(노출 40·클릭 3), 커밍아웃 스토리(노출 15·클릭 2)')
        url, body = s.calls[0]
        self.assertIn('sc-domain%3Ahantijae-bookstore.com', url)
        self.assertEqual((body['startDate'], body['endDate']), ('2026-09-26', '2026-10-02'))
        self.assertEqual(s.calls[1][1]['rowLimit'], search.TOP)

    def test_no_data_or_error_gives_no_line(self):
        self.assertEqual(search.week_line(date(2026, 10, 5), session=Session({(): [{'clicks': 0, 'impressions': 0}]})), '')
        self.assertEqual(search.week_line(date(2026, 10, 5), session=Session({(): []})), '')
        with self.assertLogs('intake', level='WARNING'):
            self.assertEqual(search.week_line(date(2026, 10, 5), session=Session({}, status=403)), '')

    def test_without_service_account_gives_no_line(self):
        self.assertEqual(search.week_line(date(2026, 10, 5)), '')   # MODE=test에는 서비스 계정이 없다

    def test_logs_the_status_code_on_http_error(self):
        class RaisingSession:
            def post(self, url, json=None, timeout=None):
                raise requests.HTTPError(response=SimpleNamespace(status_code=403))

        with self.assertLogs('intake', level='WARNING') as cm:
            line = search.week_line(date(2026, 10, 5), session=RaisingSession())
        self.assertEqual(line, '')
        self.assertTrue(any('403' in m for m in cm.output))
