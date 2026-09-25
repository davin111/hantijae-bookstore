import json
import os
import tempfile

from django.test import TestCase, override_settings
from PIL import Image

from books.models import Book, BookAuthor, Category, Series
from intake import drafts
from intake.extraction import ExtractionResult
from intake.models import BookDraft, IntakeSource, PendingPatch

WORK = tempfile.mkdtemp()
DATA = {
    'title': '무지개를 변호하다', 'subtitle': '트랜스젠더 변호사 박한희의 삶과 생각',
    'authors': [{'name': '박한희', 'role': '지은이'}], 'series': None, 'series_number': None,
    'category': '에세이', 'size': '130×200', 'page_count': 264, 'price': 22000,
    'isbn': '979-11-92455-87-7', 'isbn_addon': '03300', 'published_date': '2026-06-01',
    'short_description': '한국 최초로 커밍아웃한', 'description': '트랜스젠더 변호사인 저자는',
}
SOURCE_TEXT = '한국 최초로 커밍아웃한\n트랜스젠더 변호사인 저자는'


def image(name):
    path = os.path.join(WORK, name)
    Image.new('RGB', (400, 600), 'white').save(path, 'JPEG')
    return path


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)

    def complete(self, system, user, attachments=()):
        return json.dumps(self.replies.pop(0), ensure_ascii=False)


@override_settings(INTAKE={'WORK_DIR': WORK})
class DraftsTest(TestCase):
    def setUp(self):
        Category.objects.create(name='에세이')
        Category.objects.create(name='사회과학')
        Series.objects.create(name='단행본', series_type=Series.NORMAL)
        Series.objects.create(name='팸플릿')
        self.source = IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='보도자료_무지개를변호하다')

    def result(self, **data):
        a, b = image('3d-a.jpg'), image('3d-b.jpg')
        return ExtractionResult(data=dict(DATA, **data), root=WORK, press_release=os.path.join(WORK, 'x.pdf'),
                                front_cover=image('front.jpg'), cover_3d=a, cover_3d_alternatives=[a, b],
                                source_text=SOURCE_TEXT, source_quality=0.9)

    def test_create_draft_builds_unpublished_book(self):
        draft = drafts.create_draft(self.source, self.result())
        book = draft.book
        self.assertFalse(book.is_published)
        self.assertEqual((book.full_price, book.size, book.category.name), (22000, '130*200', '에세이'))
        self.assertEqual([ba.author.name for ba in book.authors.all()], ['박한희'])
        self.assertEqual(book.series.get().series.name, '단행본')
        self.assertTrue(book.cover_image and book.cover_image_3d)
        self.assertEqual(draft.state, BookDraft.REVIEW)
        self.assertFalse([w for w in draft.warnings if w['blocking']])

    def test_missing_price_blocks_until_patched(self):
        draft = drafts.create_draft(self.source, self.result(price=None))
        self.assertIn('missing:full_price', {w['code'] for w in draft.warnings if w['blocking']})
        patch = drafts.propose_patch(draft, '가격은 22000원', '엄마',
                                     FakeLLM({'changes': [{'field': 'full_price', 'new_value': 22000}], 'questions': []}))
        draft, rev = drafts.apply_patch(patch.id, '엄마')
        self.assertEqual(draft.book.full_price, 22000)
        self.assertEqual(rev.changes, [{'field': 'full_price', 'old': 0, 'new': 22000}])
        self.assertFalse([w for w in draft.warnings if w['blocking']])
        self.assertEqual(draft.version, 2)

    def test_propose_drops_unknown_and_noop_fields(self):
        draft = drafts.create_draft(self.source, self.result())
        patch = drafts.propose_patch(draft, '...', '엄마', FakeLLM({'changes': [
            {'field': 'visible', 'new_value': False},
            {'field': 'title', 'new_value': '무지개를 변호하다'},
            {'field': 'subtitle', 'new_value': '트랜스젠더 변호사 박한희의 삶과 싸움'}], 'questions': []}))
        self.assertEqual([c['field'] for c in patch.changes], ['subtitle'])

    def test_stale_patch_is_rejected(self):
        draft = drafts.create_draft(self.source, self.result())
        reply = {'changes': [{'field': 'subtitle', 'new_value': '가'}], 'questions': []}
        p1 = drafts.propose_patch(draft, 'a', '엄마', FakeLLM(reply))
        p2 = drafts.propose_patch(draft, 'b', '아빠', FakeLLM(dict(reply, changes=[{'field': 'subtitle', 'new_value': '나'}])))
        drafts.apply_patch(p1.id, '엄마')
        with self.assertRaises(drafts.StaleError):
            drafts.apply_patch(p2.id, '아빠')
        self.assertEqual(PendingPatch.objects.get(pk=p2.id).status, PendingPatch.STALE)
        with self.assertRaises(drafts.StaleError):
            drafts.apply_patch(p1.id, '엄마')   # 같은 제안 두 번 반영도 거절

    def test_revert_restores_old_values(self):
        draft = drafts.create_draft(self.source, self.result())
        p = drafts.propose_patch(draft, 'x', '엄마', FakeLLM({'changes': [
            {'field': 'authors', 'new_value': [{'name': '박한희', 'role': '지은이'}, {'name': '홍길동', 'role': '옮긴이'}]},
            {'field': 'category', 'new_value': '사회과학'}], 'questions': []}))
        draft, rev = drafts.apply_patch(p.id, '엄마')
        self.assertEqual(draft.book.authors.count(), 2)
        draft, _ = drafts.revert_revision(rev.id, '나')
        self.assertEqual([ba.author.name for ba in draft.book.authors.all()], ['박한희'])
        self.assertEqual(draft.book.category.name, '에세이')

    def test_invalid_patch_value_raises_and_rolls_back(self):
        draft = drafts.create_draft(self.source, self.result())
        p = drafts.propose_patch(draft, 'x', '엄마', FakeLLM({'changes': [
            {'field': 'subtitle', 'new_value': '새 부제'}, {'field': 'isbn', 'new_value': '123'}], 'questions': []}))
        with self.assertRaises(drafts.PatchError):
            drafts.apply_patch(p.id, '엄마')
        self.assertEqual(Book.objects.get(pk=draft.book_id).subtitle, DATA['subtitle'])

    def test_cycle_3d_and_discard(self):
        draft = drafts.create_draft(self.source, self.result())
        draft = drafts.cycle_3d(draft.id, draft.version, '엄마')
        self.assertEqual(draft.files['cover_3d_index'], 1)
        book_id = draft.book_id
        draft = drafts.discard(draft.id, draft.version)
        self.assertEqual(draft.state, BookDraft.DISCARDED)
        self.assertFalse(Book.objects.filter(pk=book_id).exists())
