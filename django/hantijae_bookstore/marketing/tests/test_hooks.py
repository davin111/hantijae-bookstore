import io
from datetime import date

from django.core.management import call_command
from django.test import TestCase

from marketing.hooks import SEED, add_hook, seed, upcoming
from marketing.models import HookDate
from marketing.tests.fakes import make_book


class HookTest(TestCase):
    def test_seed_links_books_by_title_ignoring_spaces(self):
        make_book(title='커밍아웃 스토리', isbn='979-11-00000-01-1', author=None)
        make_book(title='1.5 :  그레타 툰베리와 함께', isbn='979-11-00000-02-1', author=None)
        created, missing = seed()
        self.assertEqual(created, len(SEED))
        self.assertEqual([b.title for b in HookDate.objects.get(name='커밍아웃의 날').books.all()], ['커밍아웃 스토리'])
        self.assertEqual(HookDate.objects.get(name='지구의 날').books.count(), 1)
        self.assertIn('무지개를 변호하다', missing)

    def test_seed_is_repeatable(self):
        seed()
        created, _ = seed()
        self.assertEqual(created, 0)
        self.assertEqual(HookDate.objects.count(), len(SEED))

    def test_memorial_flags(self):
        seed()
        self.assertTrue(HookDate.objects.get(name='트랜스젠더 추모의 날').memorial)
        self.assertFalse(HookDate.objects.get(name='한글날').memorial)

    def test_upcoming_sorted_within_days(self):
        seed()
        names = [h.name for h, on in upcoming(date(2026, 9, 28), 21)]
        self.assertEqual(names, ['대구 10월항쟁', '한글날', '커밍아웃의 날', '세계 식량의 날'])

    def test_add_hook_reports_missing_titles(self):
        make_book(title='글쓰기의 태도', isbn='979-11-00000-03-1', author=None)
        hook, missing = add_hook(10, 9, '한글날 특집', ['글쓰기의 태도', '없는 책'])
        self.assertEqual((hook.books.count(), missing), (1, ['없는 책']))

    def test_add_hook_clips_long_name(self):
        hook, _ = add_hook(10, 9, '가' * 150, [])
        self.assertEqual(len(hook.name), 100)

    def test_seed_command_prints_counts(self):
        call_command('marketing_seed_hooks', stdout=io.StringIO())
        self.assertEqual(HookDate.objects.count(), len(SEED))
