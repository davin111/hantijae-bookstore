"""서치 콘솔(스펙 §7): 지난 7일 구글 검색에서 사이트가 보인 횟수·눌린 횟수와 많이 찾은 말. 브리핑 만들 때 두 번 읽는다(저장 없음).
서비스 계정(intake-reader, webmasters.readonly)을 속성 사용자로 추가해 두었다. 자료는 2~3일 늦다 → 오늘-3일까지 7일."""
import json
import logging
import urllib.parse
from datetime import timedelta

from django.conf import settings

log = logging.getLogger('intake')
SITE = 'sc-domain:hantijae-bookstore.com'
API = 'https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query'
SCOPE = 'https://www.googleapis.com/auth/webmasters.readonly'
LAG_DAYS, TOP = 3, 3


def _session():
    info = getattr(settings, 'INTAKE', {}).get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not info:
        return None
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    return AuthorizedSession(service_account.Credentials.from_service_account_info(json.loads(info), scopes=[SCOPE]))


def _rows(session, start, end, dims):
    res = session.post(API.format(site=urllib.parse.quote(SITE, safe='')),
                       json={'startDate': start.isoformat(), 'endDate': end.isoformat(), 'dimensions': list(dims),
                             'rowLimit': TOP if dims else 1}, timeout=30)
    res.raise_for_status()
    return res.json().get('rows') or []


def week_line(today, session=None):
    """'지난 7일 구글 검색: 노출 120·클릭 8. 많이 찾은 말: 한티재(노출 40·클릭 3), …'. 못 읽거나 노출이 0이면 ''."""
    try:
        session = session or _session()
        if session is None:
            return ''
        end = today - timedelta(days=LAG_DAYS)
        start = end - timedelta(days=6)
        total = _rows(session, start, end, ())
        if not total or not total[0].get('impressions'):
            return ''
        top = _rows(session, start, end, ('query',))
    except Exception as e:   # 권한·네트워크 문제는 줄만 빼고 브리핑은 그대로
        log.warning('search console: %s', type(e).__name__)
        return ''
    t = total[0]
    line = f'지난 7일 구글 검색: 노출 {int(t["impressions"])}·클릭 {int(t.get("clicks") or 0)}'
    words = [f'{r["keys"][0]}(노출 {int(r.get("impressions") or 0)}·클릭 {int(r.get("clicks") or 0)})'
             for r in top if r.get('keys')]
    return line + ('. 많이 찾은 말: ' + ', '.join(words) if words else '')
