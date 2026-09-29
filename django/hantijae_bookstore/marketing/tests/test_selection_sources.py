import urllib.parse
from datetime import date

from django.test import SimpleTestCase

from marketing.selection_sources import (KPIPA_LIST, KPIPA_VIEW, TKPF_LIST, TKPF_VIEW, NAS_URL, NL_URL, SCANNERS,
                                         is_selection_title, kpipa_files, kpipa_label, kpipa_posts, scan_kpipa,
                                         scan_tkpf, tkpf_files, tkpf_label, tkpf_posted, tkpf_posts, nas_rows,
                                         scan_nas, nl_rows, scan_nl, months_ago)
from marketing.tests.fakes import tiny_pdf, tiny_xlsx

KPIPA_LIST_HTML = """<ul class="fz-list">
<li class=""><div class="fz-subject">
<a href='https://www.kpipa.or.kr/p/g1_2/2145?sca=%EA%B2%B0%EA%B3%BC%EA%B3%B5%EA%B3%A0' class='list-subject'><span class="bo-cate-link">[결과공고]</span>2026년 세종도서 교양부문 선정 결과 공고<span class='icon-pack-wrap'><span class='jyk_b_new'>새글</span></span></a></div>
<div class="fz-writer"><span class="sv_member">도서유통팀</span></div>
<div class="fz-date">26.08.25.</div></li>
<li class=""><div class="fz-subject">
<a href='https://www.kpipa.or.kr/p/g1_2/2133?sca=%EA%B2%B0%EA%B3%BC%EA%B3%B5%EA%B3%A0' class='list-subject'><span class="bo-cate-link">[결과공고]</span>2026년 문학나눔 도서 보급 사업 선정 철회 공고</a></div>
<div class="fz-date">26.08.10.</div></li>
<li class=""><div class="fz-subject">
<a href='https://www.kpipa.or.kr/p/g1_2/2166?sca=%EA%B2%B0%EA%B3%BC%EA%B3%B5%EA%B3%A0' class='list-subject'><span class="bo-cate-link">[결과공고]</span>2026년 글로벌 출판전문인력 양성 교육 참가자 선발 최종 심사 결과 공고</a></div>
<div class="fz-date">26.09.29.</div></li>
</ul>"""

KPIPA_VIEW_HTML = """<h2>첨부파일</h2>
<a href="https://www.kpipa.or.kr/p/download/g1_2/2145/0/" class="view_file_download">
  <strong>2026년 세종도서 지원 사업 교양부문 도서 선정 결과 공고문.pdf</strong>   (285.5K)</a>
<a href="https://www.kpipa.or.kr/p/download/g1_2/2145/1/" class="view_file_download">
  <strong>2026년 세종도서 지원 사업 교양부문 선정도서 목록429종.pdf</strong>   (206.1K)</a>
<a href="https://www.kpipa.or.kr/p/download/g1_2/2145/2/" class="view_file_download">
  <strong>2026년 세종도서 지원 사업 교양부문 심사 총평.pdf</strong>   (149.5K)</a>"""

LIST_FILE = 'https://www.kpipa.or.kr/p/download/g1_2/2145/1/'
PAGES = {KPIPA_LIST: KPIPA_LIST_HTML, KPIPA_VIEW.format(no='2145'): KPIPA_VIEW_HTML,
         KPIPA_VIEW.format(no='2133'): '<h2>첨부파일</h2>'}
FILES = {LIST_FILE: tiny_pdf('1 9791192455808')}


def no_sleep(_):
    pass


class KpipaParseTest(SimpleTestCase):
    def test_posts_have_clean_titles_and_dates(self):
        posts = kpipa_posts(KPIPA_LIST_HTML)
        self.assertEqual(posts[0], ('2145', '2026년 세종도서 교양부문 선정 결과 공고', date(2026, 8, 25)))
        self.assertEqual([p[0] for p in posts], ['2145', '2133', '2166'])

    def test_selection_titles_only(self):
        self.assertEqual([is_selection_title(t) for _, t, _ in kpipa_posts(KPIPA_LIST_HTML)], [True, True, False])

    def test_label(self):
        self.assertEqual(kpipa_label('2026년 세종도서 교양부문 선정 결과 공고'), '2026년 세종도서 교양부문')
        self.assertEqual(kpipa_label('2026년 문학나눔 도서 보급 사업 도서 선정 결과 공고'), '2026년 문학나눔')
        self.assertEqual(kpipa_label('2026년 문학나눔 도서 보급 사업 선정 철회 공고'), '2026년 문학나눔')

    def test_files(self):
        self.assertEqual(kpipa_files(KPIPA_VIEW_HTML)[1], (LIST_FILE, '2026년 세종도서 지원 사업 교양부문 선정도서 목록429종.pdf'))


class KpipaScanTest(SimpleTestCase):
    def test_reads_only_list_files_of_new_selection_posts(self):
        fetched = []
        anns = scan_kpipa(date(2026, 9, 30), set(), PAGES.__getitem__, lambda u: fetched.append(u) or FILES[u], no_sleep)
        self.assertEqual([a.key for a in anns], ['kpipa:2145', 'kpipa:2133'])
        self.assertEqual(fetched, [LIST_FILE])
        a = anns[0]
        self.assertEqual((a.source, a.label, a.url, a.posted_on, a.fresh, a.withdrawal),
                         ('kpipa', '2026년 세종도서 교양부문', KPIPA_VIEW.format(no='2145'), date(2026, 8, 25), True, False))
        self.assertIn('9791192455808', a.texts[0])
        self.assertTrue(anns[1].withdrawal)

    def test_skips_seen_posts(self):
        self.assertEqual(scan_kpipa(date(2026, 9, 30), {'kpipa:2145', 'kpipa:2133'}, PAGES.__getitem__,
                                    FILES.__getitem__, no_sleep), [])

    def test_post_older_than_60_days_is_not_fresh(self):
        anns = scan_kpipa(date(2027, 1, 30), set(), PAGES.__getitem__, FILES.__getitem__, no_sleep)
        self.assertFalse(anns[0].fresh)

    def test_unreadable_list_page_raises(self):
        with self.assertRaises(RuntimeError):
            scan_kpipa(date(2026, 9, 30), set(), lambda _: '<html>바뀐 형식</html>', FILES.__getitem__, no_sleep)

    def test_broken_post_is_skipped_and_the_rest_still_read(self):
        def raising_get_bytes(u):
            if u == LIST_FILE:
                raise ValueError('boom')
            return FILES[u]

        with self.assertLogs('intake', level='WARNING'):
            anns = scan_kpipa(date(2026, 9, 30), set(), PAGES.__getitem__, raising_get_bytes, no_sleep)
        self.assertEqual([a.key for a in anns], ['kpipa:2133'])


TKPF_LIST_HTML = """<a href="/contents/readCountN.php?no=143&cp=1&searchSelect=&searchText=">2026년 하반기 올해의 청소년 교양도서 선정ㆍ보급사업 신청 안내</a>
<a href="/contents/readCountN.php?no=137&cp=1&searchSelect=&searchText=">제159차 2026년 상반기 올해의 청소년 교양도서 선정ㆍ보급사업 선정 결과 발표</a>"""
XLSX_NAME = '202605/1778483519674094_2026년 상반기 올해의 청소년 교양도서 목록(우수선정도서)_공개용.xlsx'
TKPF_VIEW_HTML = f"""<div class="date">2026.05.11</div>
<a href="/contents/download.php?filename=202605/1778483519673650_(260511)보도자료_제159차.pdf">보도자료</a>
<a href="/contents/download.php?filename={XLSX_NAME}">목록</a>"""
XLSX_URL = 'http://www.tkpf.or.kr/contents/download.php?filename=' + urllib.parse.quote(XLSX_NAME)


class TkpfTest(SimpleTestCase):
    def test_only_result_posts(self):
        self.assertEqual(tkpf_posts(TKPF_LIST_HTML),
                         [('137', '제159차 2026년 상반기 올해의 청소년 교양도서 선정ㆍ보급사업 선정 결과 발표')])

    def test_files_are_percent_encoded(self):
        self.assertEqual(tkpf_files(TKPF_VIEW_HTML)[1],
                         (XLSX_URL, '1778483519674094_2026년 상반기 올해의 청소년 교양도서 목록(우수선정도서)_공개용.xlsx'))

    def test_posted_date_and_label(self):
        self.assertEqual(tkpf_posted(TKPF_VIEW_HTML), date(2026, 5, 11))
        self.assertEqual(tkpf_label('제159차 2026년 상반기 올해의 청소년 교양도서 선정ㆍ보급사업 선정 결과 발표'),
                         '2026년 상반기 청소년 교양도서')

    def test_scan_downloads_only_xlsx(self):
        pages = {TKPF_LIST: TKPF_LIST_HTML, TKPF_VIEW.format(no='137'): TKPF_VIEW_HTML}
        fetched = []
        anns = scan_tkpf(date(2026, 6, 1), set(), pages.__getitem__,
                         lambda u: fetched.append(u) or tiny_xlsx(['무궁화호를 위하여'], ['9791192455808']), no_sleep)
        self.assertEqual(fetched, [XLSX_URL])
        a = anns[0]
        self.assertEqual((a.key, a.label, a.posted_on, a.fresh, a.withdrawal), ('tkpf:137', '2026년 상반기 청소년 교양도서',
                                                                  date(2026, 5, 11), True, False))
        self.assertIn('9791192455808', a.texts[0])
        self.assertEqual(scan_tkpf(date(2026, 6, 1), {'tkpf:137'}, pages.__getitem__, None, no_sleep), [])

    def test_scan_flags_withdrawn_selection(self):
        withdrawal_html = """<a href="/contents/readCountN.php?no=138&cp=1&searchSelect=&searchText=">제159차 2026년 상반기 올해의 청소년 교양도서 선정ㆍ보급사업 선정 결과 철회 공고</a>"""
        withdrawal_view_html = f"""<div class="date">2026.05.15</div>
<a href="/contents/download.php?filename=202605/withdraw.xlsx">목록</a>"""
        pages = {TKPF_LIST: withdrawal_html, TKPF_VIEW.format(no='138'): withdrawal_view_html}
        anns = scan_tkpf(date(2026, 6, 1), set(), pages.__getitem__,
                         lambda u: tiny_xlsx(['책'], ['9791111111111']), no_sleep)
        self.assertTrue(anns[0].withdrawal)

    def test_unreadable_list_page_raises(self):
        with self.assertRaises(RuntimeError):
            scan_tkpf(date(2026, 6, 1), set(), lambda _: '<html>바뀐 형식</html>', None, no_sleep)

    def test_broken_post_is_skipped_and_the_rest_still_read(self):
        xlsx_name2 = '202611/1778483519674099_2026년 하반기 올해의 청소년 교양도서 목록(우수선정도서)_공개용.xlsx'
        view_html2 = f"""<div class="date">2026.11.05</div>
<a href="/contents/download.php?filename={xlsx_name2}">목록</a>"""
        list_html = ('<a href="/contents/readCountN.php?no=137&cp=1">제159차 2026년 상반기 올해의 청소년 교양도서 '
                    '선정ㆍ보급사업 선정 결과 발표</a>\n<a href="/contents/readCountN.php?no=140&cp=1">제160차 2026년 '
                    '하반기 올해의 청소년 교양도서 선정ㆍ보급사업 선정 결과 발표</a>')
        pages = {TKPF_LIST: list_html, TKPF_VIEW.format(no='137'): TKPF_VIEW_HTML,
                TKPF_VIEW.format(no='140'): view_html2}

        def raising_get_bytes(u):
            if u == XLSX_URL:
                raise ValueError('boom')
            return tiny_xlsx(['무궁화호를 위하여'], ['9791192455808'])

        with self.assertLogs('intake', level='WARNING'):
            anns = scan_tkpf(date(2026, 6, 1), set(), pages.__getitem__, raising_get_bytes, no_sleep)
        self.assertEqual([a.key for a in anns], ['tkpf:140'])


NAS_HTML = """<ul class="data__list">
<li class="data__item"><div class="data__contents"><div class="data__cell classify--books"><div class="data__books_year">2026</div></div>
<div class="data__cell"><div class="data__books_info"><span class="books__field">사회과학/법학</span>
<strong class="books__name">내란 앞에서 : 한 헌법학자의 일지</strong><ul><li><span>출판사명</span> <em>도서출판 한티재</em></li>
<li><span>저자명</span> <em>김해원 저</em></li></ul></div></div></div></li>
<li class="data__item"><div class="data__contents"><div class="data__cell classify--books"><div class="data__books_year">2024</div></div>
<div class="data__cell"><div class="data__books_info"><strong class="books__name">도심재생의 미래</strong><ul>
<li><span>출판사명</span> <em>한티재</em></li><li><span>저자명</span> <em>이권희 저</em></li></ul></div></div></div></li>
</ul>"""

NL_ITEM_HTML = """<li class="uccst14_item"><a href="#none" onclick="fn_goView('20260728101010000100')">
<div class="inner"><div class="cont"><div class="bx"><div class="title_inner">
<span class="date">2026.8</span> <span class="category">사회과학</span> <strong
	class="title"
	title="무궁화호를 위하여 : 기차가 멈추는 곳">
	무궁화호를 위하여 : 기차가 멈추는 곳</strong></div>
<div class="info_inner"><dl><dt>지은이</dt><dd class="author">하승우</dd><dt>출판사</dt><dd class="publisher">한티재</dd>
</dl></div></div></div></div></a></li>
"""
NL_HTML = NL_ITEM_HTML * 2   # 사이트는 썸네일·목록 두 번 그린다


class NasNlTest(SimpleTestCase):
    def test_nas_rows(self):
        self.assertEqual(nas_rows(NAS_HTML)[0], (2026, '내란 앞에서 : 한 헌법학자의 일지', '도서출판 한티재', '김해원 저'))

    def test_scan_nas_marks_only_this_year_fresh(self):
        anns = scan_nas(date(2026, 9, 30), set(), {NAS_URL: NAS_HTML}.__getitem__, None, no_sleep)
        self.assertEqual([(a.key, a.fresh) for a in anns],
                         [('nas:2026:내란앞에서:한헌법학자의일지', True), ('nas:2024:도심재생의미래', False)])
        self.assertEqual(anns[0].label, '2026년 학술원 우수학술도서')
        self.assertIn('한티재', anns[0].texts[0])

    def test_nl_rows_dedupe_and_scan(self):
        self.assertEqual(len(nl_rows(NL_HTML)), 1)
        anns = scan_nl(date(2026, 9, 30), set(), {NL_URL: NL_HTML}.__getitem__, None, no_sleep)
        self.assertEqual([(a.key, a.label, a.fresh) for a in anns],
                         [('nl:20260728101010000100', '국립중앙도서관 사서추천도서(2026.8)', True)])
        self.assertEqual(scan_nl(date(2026, 9, 30), {'nl:20260728101010000100'}, {NL_URL: NL_HTML}.__getitem__,
                                 None, no_sleep), [])

    def test_months_ago(self):
        self.assertEqual([months_ago('2026.8', date(2026, 9, 30)), months_ago('2025.12', date(2026, 2, 1)),
                          months_ago('', date(2026, 2, 1))], [1, 2, 999])

    def test_scanners_registry(self):
        self.assertEqual([s[0] for s in SCANNERS], ['kpipa', 'tkpf', 'nas', 'nl'])
