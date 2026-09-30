from datetime import date

from django.test import SimpleTestCase, override_settings

from marketing import bnk

LOGIN_HTML = ('<form id="loginForm" action="/home/v3/loginAjax" method="post">'
              '<input type="hidden" name="_csrf" value="tok-login"/></form>')
MAIN_HTML = ('<script>m_hCsrf = "X-CSRF-TOKEN"; m_sCsrf = "tok-main";</script>'
             '<form id="btuiLogoutForm" action="/home/v3/logoutAjax"></form>')
FAIL_HTML = LOGIN_HTML + '<input type="hidden" id="loginErrorMessage" value="아이디 또는 비밀번호를 확인해 주세요."/>'
SALES_HTML = '<script>m_sCsrf = "tok-sales";</script>'
READERS_HTML = '<script>m_sCsrf = "tok-readers";</script>'


def book_row(isbn, title, total, yes=0, kyobo=0, aladin=0, young=0, local=0, totcnt=2):
    """searchGridOnly bookList 한 줄(2026-09-30 실제 모양)."""
    return {'ro': 1, 'cIsbn': isbn, 'cIsbnFormat': '', 'cBookNm': title, 'cCntrbtrInfo': '', 'cPubldtDay': '2021-10-18',
            'cPriceamt': 15000, 'cTotal': total, 'cKyobo': kyobo, 'cYes': yes, 'cAladin': aladin, 'cYoung': young,
            'cLocal': local, 'totcnt': totcnt}


SALES_JSON = {'ajaxResult': 'succ', 'paginationInfo': {}, 'bookList': [
    book_row('9791190178716', '밥은 먹고 다니냐는 말', 26, yes=22, kyobo=1, aladin=2, young=1),
    book_row('9791192455877', '무지개를 변호하다', 3, yes=1, kyobo=1, aladin=1)]}
READERS_JSON = {  # 2026-09-01~28 실제 값
    'ajaxResult': 'succ',
    'ageRatio': [{'cSumOne': 9, 'cSumTwo': 17, 'cSumThree': 29, 'cSumFour': 30, 'cSumFive': 67, 'cSumSix': 30,
                  'cSumEtc': 6, 'cRatioOne': 4.79, 'cRatioTwo': 9.04, 'cRatioThree': 15.43, 'cRatioFour': 15.96,
                  'cRatioFive': 35.64, 'cRatioSix': 15.96, 'cRatioEtc': 3.19}],
    'genderRatio': [{'cSumFemale': 115, 'cSumMale': 71, 'cSumEtc': 2, 'cRatioFemale': 61.17, 'cRatioMale': 37.77,
                     'cRatioEtc': 1.06}],
    'regionRatio': [{'cSumSeoul': 31, 'cSumBusan': 4, 'cSumDaegu': 8, 'cSumIncheon': 4, 'cSumGwangju': 4,
                     'cSumDaejeon': 2, 'cSumUlsan': 2, 'cSumSejong': 4, 'cSumGyeonggi': 54, 'cSumGangwon': 2,
                     'cSumChungbuk': 14, 'cSumChungnam': 6, 'cSumJeonbuk': 2, 'cSumJeonnam': 8, 'cSumGyeongbuk': 2,
                     'cSumGyeongnam': 8, 'cSumJeju': 0, 'cSumUnknown': 0}]}


class Res:
    def __init__(self, url, text='', data=None):
        self.url, self.text, self._data = url, text, data

    def json(self):
        if self._data is None:
            raise ValueError('not json')
        return self._data


class FakeSession:
    """(방법, 주소) → 응답 하나 또는 목록(차례로). 보낸 요청을 (방법, 주소, 폼, 헤더)로 적는다."""
    def __init__(self, routes):
        self.routes, self.calls, self.headers = dict(routes), [], {}

    def _answer(self, key):
        r = self.routes[key]
        return r.pop(0) if isinstance(r, list) else r

    def get(self, url, timeout=None):
        self.calls.append(('GET', url, None, None))
        return self._answer(('GET', url))

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append(('POST', url, data, headers))
        return self._answer(('POST', url))


def routes():
    r = {('GET', bnk.LOGIN_PAGE): Res(bnk.LOGIN_PAGE, LOGIN_HTML),
         ('POST', bnk.LOGIN): Res(bnk.BASE + '/home/v3/main/sec/mainBoard', MAIN_HTML),
         ('GET', bnk.SALES_PAGE): Res(bnk.SALES_PAGE, SALES_HTML),
         ('POST', bnk.SALES_DAY): Res(bnk.SALES_DAY, data=SALES_JSON),
         ('GET', bnk.READERS_PAGE): Res(bnk.READERS_PAGE, READERS_HTML),
         ('POST', bnk.READERS): Res(bnk.READERS, data=READERS_JSON),
         ('POST', bnk.LOGOUT): Res(bnk.LOGIN_PAGE, LOGIN_HTML)}
    return r


def client(session, password='pw-secret'):
    return bnk.BnkClient('hantijae-test', password, session=session, sleep=lambda s: None)


class LoginTest(SimpleTestCase):
    def test_login_posts_credentials_with_form_token(self):
        s = FakeSession(routes())
        client(s).login()
        self.assertEqual(s.calls[1][:3], ('POST', bnk.LOGIN, {'loginid': 'hantijae-test', 'loginpwd': 'pw-secret',
                                                              '_csrf': 'tok-login', 'reprice': '', 'returnUrl': ''}))

    def test_login_failure_raises_with_site_message_but_never_the_password(self):
        s = FakeSession(routes() | {('POST', bnk.LOGIN): Res(bnk.LOGIN_PAGE, FAIL_HTML)})
        with self.assertRaises(bnk.BnkLoginError) as e:
            client(s).login()
        self.assertIn('아이디 또는 비밀번호를 확인해 주세요.', str(e.exception))
        self.assertNotIn('pw-secret', str(e.exception))

    def test_unrecognized_page_after_login_is_not_a_credential_error(self):
        s = FakeSession(routes() | {('POST', bnk.LOGIN): Res(bnk.LOGIN_PAGE, LOGIN_HTML)})   # 문구 없는 화면(점검 등)
        with self.assertRaises(bnk.BnkError) as e:
            client(s).login()
        self.assertNotIsInstance(e.exception, bnk.BnkLoginError)

    def test_missing_credentials_raise_login_error(self):
        with self.assertRaises(bnk.BnkLoginError):
            bnk.BnkClient('', '', session=FakeSession({}))

    def test_context_manager_logs_out_even_when_a_query_fails(self):
        s = FakeSession(routes() | {('POST', bnk.SALES_DAY): Res(bnk.SALES_DAY, 'html')})
        with self.assertRaises(bnk.BnkError):
            with client(s) as c:
                c.sales_on(date(2026, 9, 28))
        self.assertEqual(s.calls[-1][:3], ('POST', bnk.LOGOUT, {'_csrf': 'tok-sales'}))

    @override_settings(MARKETING={'KPIPA_BNK_ID': 'id-from-settings', 'KPIPA_BNK_PASSWORD': 'pw-from-settings'})
    def test_client_from_settings_reads_marketing_keys(self):
        c = bnk.client_from_settings()
        self.assertEqual(c.user_id, 'id-from-settings')


class QueryTest(SimpleTestCase):
    def test_sales_on_asks_one_day_with_page_token(self):
        s = FakeSession(routes())
        with client(s) as c:
            rows = c.sales_on(date(2026, 9, 28))
        post = next(x for x in s.calls if x[1] == bnk.SALES_DAY)
        self.assertEqual({k: post[2][k] for k in ('searchDateType', 'txtFromDate', 'txtToDate', 'pageNo',
                                                  'recordCountPerPage', '_csrf')},
                         {'searchDateType': 'D', 'txtFromDate': '20260928', 'txtToDate': '20260928', 'pageNo': '1',
                          'recordCountPerPage': '200', '_csrf': 'tok-sales'})
        self.assertEqual((post[3]['X-CSRF-TOKEN'], post[3]['X-Requested-With']), ('tok-sales', 'XMLHttpRequest'))
        self.assertEqual(rows, [
            {'isbn': '9791190178716', 'title': '밥은 먹고 다니냐는 말', 'kyobo': 1, 'yes24': 22, 'aladin': 2, 'ypbooks': 1,
             'local': 0, 'total': 26},
            {'isbn': '9791192455877', 'title': '무지개를 변호하다', 'kyobo': 1, 'yes24': 1, 'aladin': 1, 'ypbooks': 0,
             'local': 0, 'total': 3}])

    def test_page_token_is_fetched_once_per_session(self):
        s = FakeSession(routes())
        with client(s) as c:
            c.sales_on(date(2026, 9, 27))
            c.sales_on(date(2026, 9, 28))
        self.assertEqual(sum(1 for x in s.calls if x[:2] == ('GET', bnk.SALES_PAGE)), 1)

    def test_sales_follow_pages_until_totcnt(self):
        page1 = {'ajaxResult': 'succ', 'bookList': [book_row('9791190178716', 'A', 1, totcnt=201)] * 200}
        page2 = {'ajaxResult': 'succ', 'bookList': [book_row('9791192455877', 'B', 1, totcnt=201)]}
        s = FakeSession(routes() | {('POST', bnk.SALES_DAY): [Res(bnk.SALES_DAY, data=page1),
                                                              Res(bnk.SALES_DAY, data=page2)]})
        with client(s) as c:
            rows = c.sales_on(date(2026, 9, 28))
        self.assertEqual(len(rows), 201)
        self.assertEqual([x[2]['pageNo'] for x in s.calls if x[1] == bnk.SALES_DAY], ['1', '2'])

    def test_failed_ajax_result_raises(self):
        s = FakeSession(routes() | {('POST', bnk.SALES_DAY): Res(bnk.SALES_DAY, data={'ajaxResult': 'fail'})})
        with self.assertRaises(bnk.BnkError):
            with client(s) as c:
                c.sales_on(date(2026, 9, 28))

    def test_rows_without_a_13_digit_isbn_are_skipped(self):
        data = {'ajaxResult': 'succ', 'bookList': [book_row('', '빈 ISBN', 1), book_row('97911901787', '짧음', 1)]}
        self.assertEqual(bnk.parse_sales(data), [])

    def test_readers_are_sorted_shares(self):
        s = FakeSession(routes())
        with client(s) as c:
            r = c.readers(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(r['age'][:3], [('50대', 35.64), ('40대', 15.96), ('60대 이상', 15.96)])
        self.assertEqual((r['female'], r['male'], r['buyers']), (61.17, 37.77, 188))
        self.assertEqual(r['region'][:3], [('경기', 54), ('서울', 31), ('충북', 14)])
        post = next(x for x in s.calls if x[1] == bnk.READERS)
        self.assertEqual((post[2]['txtFromDate'], post[2]['txtToDate'], post[2]['_csrf']),
                         ('20260901', '20260930', 'tok-readers'))
