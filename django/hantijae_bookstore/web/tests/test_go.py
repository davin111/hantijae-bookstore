from unittest import mock

from django.db import DatabaseError
from django.test import TestCase, override_settings

from accounts.models import User
from web.models import StoreClick
from web.tests import factories as f

UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)'


class StoreRedirectTest(TestCase):
    def setUp(self):
        self.book = f.book('내일 날씨, 어떻습니까?', isbn='979-11-90178-60-0  04450')

    def go(self, path, **headers):
        return self.client.get(path, HTTP_USER_AGENT=headers.pop('ua', UA), **headers)

    def test_redirects_and_records_store_and_referrer_host_only(self):
        r = self.go(f'/go/{self.book.id}/yes24', HTTP_REFERER='https://hantijae-bookstore.com/book=1?utm=x')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], 'https://www.yes24.com/product/search?domain=ALL&query=9791190178600')
        click = StoreClick.objects.get()
        self.assertEqual((click.book, click.store, click.referrer_host), (self.book, 'yes24', 'hantijae-bookstore.com'))

    def test_bots_are_not_recorded(self):
        for ua in ('facebookexternalhit/1.1', 'Mozilla/5.0 (compatible; Yeti/1.1; +https://naver.me/spd)',
                   'kakaotalk-scrap/1.0', 'Googlebot/2.1'):
            self.assertEqual(self.go(f'/go/{self.book.id}/aladin', ua=ua).status_code, 302)
        self.assertEqual(StoreClick.objects.count(), 0)

    @override_settings(DEBUG=True)
    def test_debug_mode_is_not_recorded(self):
        self.go(f'/go/{self.book.id}/aladin')
        self.assertEqual(StoreClick.objects.count(), 0)

    def test_unknown_store_unpublished_missing_links_are_404(self):
        hidden = f.book('비공개', is_published=False)
        bare = f.book('서지 없음', isbn=None)
        for path in (f'/go/{self.book.id}/amazon', f'/go/{hidden.id}/aladin', f'/go/{bare.id}/kyobo', '/go/999999/aladin'):
            self.assertEqual(self.go(path).status_code, 404, path)

    def test_ebook_store_redirects_and_records(self):
        b = f.book('기독교 본질 논쟁', visible=False, ebook_ridi_url='https://ridibooks.com/books/754042189')
        r = self.go(f'/go/{b.id}/ridi')
        self.assertEqual((r.status_code, r['Location']), (302, 'https://ridibooks.com/books/754042189'))
        self.assertEqual(StoreClick.objects.get().store, 'ridi')
        self.assertEqual(self.go(f'/go/{b.id}/e_yes24').status_code, 404)   # 저장 주소도, 믿을 만한 검색 주소도 없음

    def test_db_error_still_redirects(self):
        with mock.patch('web.views.StoreClick.objects.create', side_effect=DatabaseError('down')):
            self.assertEqual(self.go(f'/go/{self.book.id}/kyobo').status_code, 302)

    def test_admin_changelist_shows_totals(self):
        for store in ('aladin', 'aladin', 'kyobo'):
            self.go(f'/go/{self.book.id}/{store}')
        User.objects.create_superuser('관리자', 'admin@example.com', 'pw-for-test')
        self.client.login(username='관리자', password='pw-for-test')
        body = self.client.get('/admin/web/storeclick/').content.decode()
        self.assertIn('서점별', body)
        self.assertIn('<td>알라딘</td><td>2</td>', body)
        self.assertIn('<td>내일 날씨, 어떻습니까?</td><td>3</td>', body)
