import io
from datetime import date
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from books.preview import make_preview_token
from web.tests import factories as f

DESC = ('갈릴레이 온도계부터,\n일기예보의 시대\n\n사람은 지구 대기 속에서 살아간다.\n'
        '■ 저자 소개\n김해동\n■ 차례\n들어가는 글\n제1장')


def png():
    buf = io.BytesIO()
    Image.new('RGB', (40, 40), (250, 200, 0)).save(buf, 'PNG')
    return SimpleUploadedFile('c.png', buf.getvalue(), content_type='image/png')


class DetailTest(TestCase):
    def setUp(self):
        patcher = mock.patch('web.views.blog.latest_posts', return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.book = f.book('내일 날씨, 어떻습니까?', date(2021, 7, 12), in_series='교양문고',
                           subtitle='기상학자가 들려주는 과학과 세상 이야기', full_price=14000, page_count=256,
                           size='125*188', isbn='979-11-90178-60-0  04450', description=DESC,
                           short_description='기후위기 시대, 모든 시민의 교양', cover_image_3d=png(),
                           authors=(('김해동', 1),))
        self.sibling = f.book('시대의 끝에서', date(2020, 1, 1), in_series='교양문고')

    def get(self, book, query=''):
        return self.client.get(f'/book={book.id}{query}')

    def test_detail_renders_info_spec_and_store_buttons(self):
        r = self.get(self.book)
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        for text in ('<h1 class="detail-title serif">내일 날씨, 어떻습니까?</h1>', '김해동 지음', '14,000원',
                     '2021년 7월 12일', '256쪽', '125×188mm', '979-11-90178-60-0 04450', '서점에서 만나기',
                     f'href="/go/{self.book.id}/aladin"', '<a href="/series=', '교양문고</a>'):
            self.assertIn(text, body)
        self.assertIn('class="btn btn-fill" href="/go/', body)   # 첫 서점 버튼만 채움

    def test_sections_nav_and_collapsed_toc(self):
        body = self.get(self.book).content.decode()
        # 구획이 셋이라 첫 구획 제목이 '책 소개' → 리드 문단엔 id가 붙지 않는다
        self.assertIn('<p class="lead">갈릴레이 온도계부터,<br>일기예보의 시대</p>', body)
        self.assertIn('<a href="#section-2">저자 소개</a>', body)
        self.assertIn('<h2 id="section-3">차례</h2>', body)
        self.assertIn('<details><summary>펼쳐 보기</summary><p>들어가는 글<br>제1장</p></details>', body)

    def test_meta_is_book_type_with_absolute_cover(self):
        body = self.get(self.book).content.decode()
        self.assertIn('<title>내일 날씨, 어떻습니까? — 도서출판 한티재</title>', body)
        self.assertIn('<meta property="og:type" content="book">', body)
        self.assertIn('<meta property="book:isbn" content="9791190178600">', body)
        self.assertIn('<meta property="book:release_date" content="2021-07-12">', body)
        self.assertIn('<meta property="book:author" content="김해동">', body)
        self.assertIn('<meta property="og:image" content="https://hantijae-bookstore.com/', body)
        self.assertIn('<meta name="description" content="기후위기 시대, 모든 시민의 교양">', body)

    def test_translator_and_planner_are_credited(self):
        b = f.book('사그라다 파밀리아, 가족의 탄생', authors=(('나카야마 가호', 1), ('해강', 2)))
        self.assertIn('나카야마 가호 지음 · 해강 옮김', self.get(b).content.decode())
        b2 = f.book('내란 앞에서', authors=(('김해원', 1), ('헌법공부모임 제1조', 3)))
        self.assertIn('김해원 지음 · 헌법공부모임 제1조 기획', self.get(b2).content.decode())

    def test_out_of_print_has_no_buttons(self):
        b = f.book('절판 책', visible=False)
        body = self.get(b).content.decode()
        self.assertIn('절판된 책입니다', body)
        self.assertNotIn('/go/', body)
        self.assertNotIn('서점에서 만나기', body)

    def test_detail_without_store_links_has_no_buttons(self):
        body = self.get(f.book('서지 없음', isbn=None)).content.decode()
        self.assertNotIn('store-buttons', body)
        self.assertNotIn('서점에서 만나기', body)

    def test_detail_escapes_html_in_description(self):
        b = f.book('위험한 글', description='첫 문단\n\n<script>alert(1)</script>')
        body = self.get(b).content.decode()
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', body)
        self.assertNotIn('<script>alert(1)</script>', body)

    def test_same_series_excludes_self(self):
        r = self.get(self.book)
        self.assertEqual(r.context['same_series'], [self.sibling])
        self.assertIn('교양문고의 다른 책', r.content.decode())

    def test_unpublished_requires_valid_preview_token(self):
        draft = f.book('초안', is_published=False)
        self.assertEqual(self.get(draft).status_code, 404)
        self.assertEqual(self.get(draft, '?preview=bad').status_code, 404)
        r = self.get(draft, f'?preview={make_preview_token(draft.id)}')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('검수용 미리보기 — 아직 사이트에 공개되지 않은 책입니다', body)
        self.assertIn('<meta name="robots" content="noindex">', body)
        self.assertIn('href="https://www.aladin.co.kr/search/', body)   # 미리보기는 /go/를 거치지 않음
        self.assertNotIn('/go/', body)

    def test_author_video_only_for_known_book(self):
        video = f.book('영상 있는 책', id=109)
        self.assertIn('youtube-nocookie.com/embed/SGU5AzdzMNg', self.get(video).content.decode())
        self.assertNotIn('youtube-nocookie', self.get(self.book).content.decode())   # 푸터 유튜브 채널 링크와 구분

    def test_missing_book_is_404(self):
        self.assertEqual(self.client.get('/book=999999').status_code, 404)
