from datetime import date

from django.test import SimpleTestCase

from marketing.selection_sources import (KPIPA_LIST, KPIPA_VIEW, is_selection_title, kpipa_files, kpipa_label,
                                         kpipa_posts, scan_kpipa)
from marketing.tests.fakes import tiny_pdf

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
