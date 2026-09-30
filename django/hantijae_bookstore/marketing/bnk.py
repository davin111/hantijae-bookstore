"""출판유통통합전산망(bnk.kpipa.or.kr) 판매 조회. 공식 API가 아니라 화면이 뒤에서 부르는 주소를 쓴다
(시험 기록 .claude/docs/signals/2026-09-30-bnk-sales-spike.md, 로컬).
원리: 로그인 화면의 _csrf와 세션 쿠키로 로그인 → 각 화면 HTML의 m_sCsrf를 헤더 X-CSRF-TOKEN에 실어 AJAX 주소를 부른다.
아이디·비밀번호는 로그·예외 문구에 남기지 않는다."""
import logging
import re
import time

import requests
from django.conf import settings

log = logging.getLogger('intake')
BASE = 'https://bnk.kpipa.or.kr'
LOGIN_PAGE = BASE + '/home/v3/login'
LOGIN = BASE + '/home/v3/loginAjax'
LOGOUT = BASE + '/home/v3/logoutAjax'
SALES_PAGE = BASE + '/home/v3/stats/sec/statsSaleAllList'
SALES_DAY = SALES_PAGE + '/searchGridOnly'
READERS_PAGE = BASE + '/home/v3/stats/sec/statsAnalysisReaderOnline'
READERS = READERS_PAGE + '/cntList'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'
TIMEOUT, SPACING, PAGE_SIZE, MAX_PAGES = 30, 1.5, 200, 10
STORES = (('kyobo', 'cKyobo'), ('yes24', 'cYes'), ('aladin', 'cAladin'), ('ypbooks', 'cYoung'), ('local', 'cLocal'))
AGES = (('10대', 'One'), ('20대', 'Two'), ('30대', 'Three'), ('40대', 'Four'), ('50대', 'Five'), ('60대 이상', 'Six'),
        ('기타', 'Etc'))
REGIONS = (('서울', 'Seoul'), ('부산', 'Busan'), ('대구', 'Daegu'), ('인천', 'Incheon'), ('광주', 'Gwangju'),
           ('대전', 'Daejeon'), ('울산', 'Ulsan'), ('세종', 'Sejong'), ('경기', 'Gyeonggi'), ('강원', 'Gangwon'),
           ('충북', 'Chungbuk'), ('충남', 'Chungnam'), ('전북', 'Jeonbuk'), ('전남', 'Jeonnam'), ('경북', 'Gyeongbuk'),
           ('경남', 'Gyeongnam'), ('제주', 'Jeju'))
_FORM_CSRF = re.compile(r'name="_csrf"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="_csrf"')
_PAGE_CSRF = re.compile(r'm_sCsrf\s*=\s*"([^"]+)"')
_LOGIN_ERROR = re.compile(r'id="loginErrorMessage"[^>]*value="([^"]*)"')


class BnkError(Exception):
    pass


class BnkLoginError(BnkError):
    pass


def form_csrf(html):
    m = _FORM_CSRF.search(html or '')
    return (m.group(1) or m.group(2)) if m else None


def page_token(html):
    m = _PAGE_CSRF.search(html or '')
    return m.group(1) if m else None


def _ymd(day):
    return day.strftime('%Y%m%d')


def _json(res, url):
    try:
        data = res.json()
    except ValueError:
        raise BnkError(f'응답이 JSON이 아니에요(로그인이 풀렸거나 화면이 바뀌었을 수 있어요): {url}')
    if data.get('ajaxResult') != 'succ':
        raise BnkError(f'조회 실패({data.get("ajaxResult")}): {url}')
    return data


def parse_sales(data):
    out = []
    for row in data.get('bookList') or []:
        isbn = re.sub(r'\D', '', str(row.get('cIsbn') or ''))
        if len(isbn) != 13:
            continue
        item = {'isbn': isbn, 'title': str(row.get('cBookNm') or '')[:300]}
        for key, col in STORES:
            item[key] = int(row.get(col) or 0)
        item['total'] = int(row.get('cTotal') or 0)
        out.append(item)
    return out


def parse_readers(data):
    """온라인 구매자 비율(cntList). 같은 값이면 AGES·REGIONS 순서를 지킨다."""
    age = (data.get('ageRatio') or [{}])[0]
    gender = (data.get('genderRatio') or [{}])[0]
    region = (data.get('regionRatio') or [{}])[0]
    return {'age': sorted(((name, float(age.get('cRatio' + k) or 0)) for name, k in AGES), key=lambda x: -x[1]),
            'female': float(gender.get('cRatioFemale') or 0), 'male': float(gender.get('cRatioMale') or 0),
            'region': sorted(((name, int(region.get('cSum' + k) or 0)) for name, k in REGIONS), key=lambda x: -x[1]),
            'buyers': sum(int(age.get('cSum' + k) or 0) for _, k in AGES)}


class BnkClient:
    def __init__(self, user_id, password, session=None, sleep=time.sleep):
        if not user_id or not password:
            raise BnkLoginError('출판유통통합전산망 계정이 설정되지 않았어요(KPIPA_BNK_ID/KPIPA_BNK_PASSWORD)')
        self.user_id, self._pw = user_id, password
        self.s = session or requests.Session()
        self.s.headers['User-Agent'] = UA
        self.sleep = sleep
        self._token, self._tokens = None, {}

    def __enter__(self):
        return self.login()

    def __exit__(self, *exc):
        self.logout()
        return False

    def login(self):
        token = form_csrf(self.s.get(LOGIN_PAGE, timeout=TIMEOUT).text)
        if not token:
            raise BnkError('로그인 화면에서 _csrf를 찾지 못했어요(화면이 바뀌었을 수 있어요)')
        res = self.s.post(LOGIN, data={'loginid': self.user_id, 'loginpwd': self._pw, '_csrf': token, 'reprice': '',
                                       'returnUrl': ''}, timeout=TIMEOUT)
        if 'logoutAjax' not in res.text:   # 로그인하면 보이는 로그아웃 폼이 없으면 실패(로그인 화면으로 돌아옴)
            m = _LOGIN_ERROR.search(res.text)
            raise BnkLoginError('출판유통통합전산망 로그인 실패' + (f': {m.group(1)}' if m and m.group(1) else ''))
        self._token = page_token(res.text)
        return self

    def _token_for(self, page_url):
        if page_url not in self._tokens:
            token = page_token(self.s.get(page_url, timeout=TIMEOUT).text)
            if not token:
                raise BnkError(f'화면에서 토큰을 찾지 못했어요(로그인이 풀렸거나 화면이 바뀌었을 수 있어요): {page_url}')
            self._tokens[page_url] = self._token = token
        return self._tokens[page_url]

    def _ajax(self, page_url, url, data):
        token = self._token_for(page_url)
        self.sleep(SPACING)
        res = self.s.post(url, data={**data, '_csrf': token}, timeout=TIMEOUT,
                          headers={'X-CSRF-TOKEN': token, 'X-Requested-With': 'XMLHttpRequest', 'Referer': page_url})
        return _json(res, url)

    @staticmethod
    def _query(start, end, page=1):
        return {'searchDateType': 'D', 'txtFromDate': _ymd(start), 'txtToDate': _ymd(end), 'cStoreFlg': '0',
                'cStoreSeq': '', 'cRegionCd': '', 'listBook': '', 'pageNo': str(page),
                'recordCountPerPage': str(PAGE_SIZE), 'loadingBarFlg': 'N'}

    def sales_on(self, day):
        """그날 팔린 책별·서점별 부수. 200줄이 넘으면 다음 쪽까지."""
        rows, page = [], 1
        while True:
            data = self._ajax(SALES_PAGE, SALES_DAY, self._query(day, day, page))
            batch = data.get('bookList') or []
            rows += parse_sales(data)
            total = int(batch[0].get('totcnt') or 0) if batch else 0
            if not batch or page * PAGE_SIZE >= total or page >= MAX_PAGES:
                return rows
            page += 1

    def readers(self, start, end):
        return parse_readers(self._ajax(READERS_PAGE, READERS, self._query(start, end)))

    def logout(self):
        if not self._token:
            return
        try:
            self.s.post(LOGOUT, data={'_csrf': self._token}, timeout=TIMEOUT,
                        headers={'X-CSRF-TOKEN': self._token, 'X-Requested-With': 'XMLHttpRequest'})
        except Exception:
            log.warning('bnk logout failed', exc_info=True)
        self._token, self._tokens = None, {}


def client_from_settings():
    conf = getattr(settings, 'MARKETING', {}) or {}
    return BnkClient(conf.get('KPIPA_BNK_ID', ''), conf.get('KPIPA_BNK_PASSWORD', ''))
