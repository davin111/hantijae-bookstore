from datetime import date
from unittest import mock

from django.test import TestCase

from marketing.models import SelectionAnnouncement, Signal
from marketing.selection_sources import Announcement
from marketing.selections import collect
from marketing.tests.fakes import make_book

TODAY = date(2026, 9, 30)


def ann(key='kpipa:2145', texts=('1 9791192455808',), fresh=True, withdrawal=False, label='2026년 세종도서 교양부문'):
    return Announcement('kpipa', key, label, 'https://www.kpipa.or.kr/p/g1_2/2145', date(2026, 8, 25), fresh,
                        list(texts), withdrawal)


def boom(*_):
    raise ValueError('page changed')


class CollectTest(TestCase):
    def setUp(self):
        self.book = make_book(title='무궁화호를 위하여', published=date(2026, 3, 16),
                              isbn='979-11-92455-80-8  03300', author='하승우')

    def run_with(self, *scanners):
        with mock.patch('marketing.selections.SCANNERS', list(scanners)):
            return collect(TODAY, get_text=None, get_bytes=None, sleep=lambda _: None)

    def test_records_announcement_and_signal_for_isbn_hit(self):
        found, failed = self.run_with(('kpipa', '출판진흥원 결과공고', lambda *a: [ann()]))
        self.assertEqual(failed, [])
        self.assertEqual([(f.how, f.signal.book) for f in found], [('isbn', self.book)])
        s = found[0].signal
        self.assertEqual((s.kind, s.key, s.title, s.happens_on, s.relevant),
                         (Signal.SELECTION, f'selection:kpipa:2145:{self.book.id}', '2026년 세종도서 교양부문',
                          date(2026, 8, 25), True))
        self.assertEqual(s.detail, {'source': 'kpipa', 'match': 'isbn', 'withdrawal': False, 'fresh': True})
        self.assertEqual(SelectionAnnouncement.objects.get().matched, 1)

    def test_announcement_without_hits_is_still_remembered(self):
        self.run_with(('kpipa', 'x', lambda *a: [ann(texts=['다른 책 9790000000000'])]))
        self.assertEqual((SelectionAnnouncement.objects.get().matched, Signal.objects.count()), (0, 0))

    def test_seen_keys_are_passed_to_scanners(self):
        SelectionAnnouncement.objects.create(key='kpipa:2145', source='kpipa', label='x', url='https://x.kr')
        box = []
        self.run_with(('kpipa', 'x', lambda today, seen, *a: box.append(set(seen)) or []))
        self.assertEqual(box, [{'kpipa:2145'}])

    def test_old_announcement_signal_is_not_relevant(self):
        found, _ = self.run_with(('kpipa', 'x', lambda *a: [ann(fresh=False)]))
        self.assertFalse(found[0].signal.relevant)

    def test_withdrawal_signal_is_not_relevant(self):
        found, _ = self.run_with(('kpipa', 'x', lambda *a: [ann(withdrawal=True)]))
        self.assertFalse(found[0].signal.relevant)
        self.assertTrue(SelectionAnnouncement.objects.get().withdrawal)

    def test_one_failing_source_is_reported_others_continue(self):
        found, failed = self.run_with(('tkpf', '청소년 교양도서', boom), ('kpipa', 'x', lambda *a: [ann()]))
        self.assertEqual((failed, len(found)), (['tkpf'], 1))

    def test_all_sources_failing_raises(self):
        with self.assertRaises(RuntimeError):
            self.run_with(('kpipa', '출판진흥원', boom), ('nl', '국립중앙도서관', boom))

    def test_duplicate_key_in_same_run_is_skipped(self):
        found, failed = self.run_with(('kpipa', 'x', lambda *a: [ann(), ann()]))
        self.assertEqual(failed, [])
        self.assertEqual(len(found), 1)
        self.assertEqual(SelectionAnnouncement.objects.count(), 1)
