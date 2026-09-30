import json
import os
import tempfile
from datetime import date
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from books.models import Book, Category
from intake import review
from intake.bot import REPLY_GUIDE, Bot
from intake.messages import review_buttons, review_text
from intake.models import ReviewItem, TelegramChat, WorkerState
from intake.tests.test_bot import ADMIN, CONFIG, GROUP, FakeTG, cb, msg

PAGE = 'page-1'


class TG(FakeTG):
    def edit_text(self, chat_id, message_id, text, buttons=None, html=False):
        self.calls.append(('edit_text', chat_id, text, buttons))


class FakeNotion:
    """노션 페이지 속성을 API 읽기 형식({'type': t, t: 값})으로 들고 있다."""
    def __init__(self, **props):
        self.pages = {PAGE: {'id': PAGE, 'properties': props}}
        self.updates, self.fail = [], False

    def get_page(self, page_id):
        return self.pages[page_id]

    def update_page(self, page_id, properties):
        if self.fail:
            raise RuntimeError('notion down')
        self.updates.append((page_id, properties))
        for k, v in properties.items():
            (t, val), = v.items()
            if t == 'rich_text':
                val = [{'plain_text': x['text']['content']} for x in val]
            self.pages[page_id]['properties'][k] = {'type': t, t: val}


def number(n):
    return {'type': 'number', 'number': n}


def text(s):
    return {'type': 'rich_text', 'rich_text': [{'plain_text': s}] if s else []}


def item_spec(**kw):
    spec = {'book_id': None, 'notion_page_id': PAGE, 'title': '『성서, 퀴어를 옹호하다』 쪽수',
            'body': '노션 320 · 사이트 368\n알라딘 368 · 예스24 368',
            'options': [{'label': '368으로 맞추기', 'set': {'쪽수': 368}},
                        {'label': '320으로 맞추기', 'set': {'쪽수': 320}},
                        {'label': '지금대로 두기', 'set': {}}]}
    spec.update(kw)
    return spec


@override_settings(INTAKE=CONFIG)
class ReviewApplyTest(TestCase):
    def setUp(self):
        cat = Category.objects.create(name='종교')
        self.book = Book.objects.create(title='성서, 퀴어를 옹호하다', subtitle='', full_price=16000, page_count=368,
                                        category=cat, published_date=date(2020, 9, 14), size='130*204')
        self.notion = FakeNotion(쪽수=number(320), 부제=text(''), 발행일={'type': 'date', 'date': {'start': '2020-09-14'}},
                                 판형={'type': 'select', 'select': {'name': '130*204'}})
        self.item = review.create_item('b1', 1, item_spec(book_id=self.book.id), self.notion)

    def fresh(self):
        return Book.objects.get(pk=self.book.id)

    def test_create_item_snapshots_current_values(self):
        self.assertEqual(self.item.before, {'쪽수': {'notion': 320, 'site': 368}})
        self.assertEqual(self.item.status, ReviewItem.PENDING)

    def test_choose_writes_only_the_side_that_differs(self):
        item, changed = review.choose(self.item.id, 0, '검수자A', self.notion)
        self.assertEqual(self.notion.updates, [(PAGE, {'쪽수': {'number': 368}})])
        self.assertEqual(self.fresh().page_count, 368)
        self.assertEqual(item.status, ReviewItem.APPLIED)
        self.assertEqual(changed, [('노션', '쪽수', 320, 368)])

        self.notion.updates.clear()
        other = review.create_item('b1', 2, item_spec(book_id=self.book.id, options=[
            {'label': '320', 'set': {'쪽수': 368}}, {'label': '140', 'set': {'쪽수': 140}}]), self.notion)
        _, changed = review.choose(other.id, 1, '검수자A', self.notion)
        self.assertEqual(self.fresh().page_count, 140)
        self.assertEqual(changed, [('노션', '쪽수', 368, 140), ('사이트', '쪽수', 368, 140)])

    def test_keep_option_writes_nothing(self):
        item, changed = review.choose(self.item.id, 2, '검수자B', self.notion)
        self.assertEqual((item.status, changed, self.notion.updates), (ReviewItem.KEPT, [], []))

    def test_value_changed_since_posting_is_not_overwritten(self):
        self.notion.pages[PAGE]['properties']['쪽수'] = number(300)   # 누가 노션을 직접 고침
        with self.assertRaises(review.ReviewError):
            review.choose(self.item.id, 0, '검수자A', self.notion)
        self.assertEqual(self.notion.updates, [])
        self.assertEqual(ReviewItem.objects.get(pk=self.item.id).status, ReviewItem.STALE)

    def test_decided_item_cannot_be_chosen_again(self):
        review.choose(self.item.id, 2, '검수자B', self.notion)
        with self.assertRaises(review.ReviewError):
            review.choose(self.item.id, 0, '검수자A', self.notion)

    def test_notion_failure_leaves_site_and_item_untouched(self):
        other = review.create_item('b1', 2, item_spec(book_id=self.book.id, options=[{'label': 'x', 'set': {'쪽수': 140}}]),
                                   self.notion)
        self.notion.fail = True
        with self.assertRaises(RuntimeError):
            review.choose(other.id, 0, '검수자A', self.notion)
        self.assertEqual(self.fresh().page_count, 368)
        self.assertEqual(ReviewItem.objects.get(pk=other.id).status, ReviewItem.PENDING)

    def test_undo_restores_both_sides_and_reopens(self):
        other = review.create_item('b1', 2, item_spec(book_id=self.book.id, options=[{'label': 'x', 'set': {'쪽수': 140}}]),
                                   self.notion)
        review.choose(other.id, 0, '검수자A', self.notion)
        item = review.undo(other.id, '검수자A', self.notion)
        self.assertEqual(item.status, ReviewItem.PENDING)
        self.assertEqual(self.notion.pages[PAGE]['properties']['쪽수']['number'], 320)
        self.assertEqual(self.fresh().page_count, 368)

    def test_undo_refuses_when_values_changed_after_choice(self):
        review.choose(self.item.id, 0, '검수자A', self.notion)
        self.notion.pages[PAGE]['properties']['쪽수'] = number(999)
        with self.assertRaises(review.ReviewError):
            review.undo(self.item.id, '검수자A', self.notion)

    def test_blank_fill_sets_text_date_and_select(self):
        Book.objects.filter(pk=self.book.id).update(subtitle='성서학자가 들려주는 이야기')
        self.notion.pages[PAGE]['properties'].update(발행일={'type': 'date', 'date': None}, 판형={'type': 'select', 'select': None},
                                                      ISBN=text(''))
        spec = item_spec(book_id=self.book.id, options=[
            {'label': '채우기', 'set': {'부제': '성서학자가 들려주는 이야기', '발행일': '2020-09-14', '판형': '130*204',
                                     'ISBN': '979-11-90178-35-8 03230'}}, {'label': '비워 두기', 'set': {}}])
        item = review.create_item('b1', 2, spec, self.notion)
        _, changed = review.choose(item.id, 0, '검수자A', self.notion)
        props = self.notion.pages[PAGE]['properties']
        self.assertEqual(props['부제']['rich_text'][0]['plain_text'], '성서학자가 들려주는 이야기')
        self.assertEqual(props['발행일']['date'], {'start': '2020-09-14'})
        self.assertEqual(props['판형']['select'], {'name': '130*204'})
        self.assertEqual(props['ISBN']['rich_text'][0]['plain_text'], '979-11-90178-35-8 03230')
        self.assertEqual({c[0] for c in changed}, {'노션'})


@override_settings(INTAKE=CONFIG)
class SaleStateReviewTest(TestCase):
    """'판매 상태'는 사이트에만 있는 항목(노션 쪽 값 없음). 절판이면 책 페이지가 서점 버튼 대신 '절판된 책입니다'를 보인다."""
    def setUp(self):
        cat = Category.objects.create(name='교양')
        self.book = Book.objects.create(title='기독교 본질 논쟁', subtitle='', full_price=12000, page_count=200,
                                        category=cat, published_date=date(2017, 10, 10))
        self.spec = {'book_id': self.book.id, 'title': '『기독교 본질 논쟁』 절판 표시', 'body': '',
                     'options': [{'label': '절판으로 표시', 'set': {'판매 상태': False}},
                                 {'label': '그대로 두기', 'set': {}}]}

    def test_out_of_print_is_applied_to_site_only_and_undoable(self):
        item = review.create_item('op', 1, self.spec, notion=None)
        self.assertEqual(item.before, {'판매 상태': {'notion': None, 'site': True}})
        item, changed = review.choose(item.id, 0, '운영진A', notion=None)
        self.assertEqual(changed, [('사이트', '판매 상태', True, False)])
        self.assertFalse(Book.objects.get(pk=self.book.id).visible)
        self.assertIn('• 사이트 판매 상태 판매 중 → 절판', review_text(item, 1))
        review.undo(item.id, '운영진A', notion=None)
        self.assertTrue(Book.objects.get(pk=self.book.id).visible)

    def test_notion_page_is_never_written_for_site_only_field(self):
        notion = FakeNotion()
        item = review.create_item('op', 1, {**self.spec, 'notion_page_id': PAGE}, notion)
        _, changed = review.choose(item.id, 0, '운영진A', notion)
        self.assertEqual((notion.updates, changed), ([], [('사이트', '판매 상태', True, False)]))


@override_settings(INTAKE=CONFIG)
class ReviewBotTest(TestCase):
    def setUp(self):
        self.tg = TG()
        cat = Category.objects.create(name='종교')
        self.book = Book.objects.create(title='성서', full_price=16000, page_count=368, category=cat,
                                        published_date=date(2020, 9, 14))
        self.notion = FakeNotion(쪽수=number(320))
        TelegramChat.objects.create(chat_id=ADMIN, kind=TelegramChat.ADMIN)
        TelegramChat.objects.create(chat_id=GROUP, kind=TelegramChat.REVIEWERS)
        self.item = review.create_item('b1', 1, item_spec(book_id=self.book.id), self.notion)
        ReviewItem.objects.filter(pk=self.item.id).update(chat_id=GROUP, message_id=555)
        self.bot = Bot(self.tg, None, notion=self.notion, config=CONFIG)

    def test_buttons_fit_callback_limit(self):
        for row in review_buttons(ReviewItem.objects.get(pk=self.item.id))['inline_keyboard']:
            for b in row:
                self.assertLessEqual(len(b['callback_data'].encode()), 64)

    def test_choice_button_applies_and_edits_message(self):
        self.bot.handle_update(cb(GROUP, f'rv:{self.item.id}:0'))
        edits = [c for c in self.tg.calls if c[0] == 'edit_text']
        self.assertIn('✅', edits[-1][2])
        self.assertIn('노션 쪽수 320 → 368', edits[-1][2])
        self.assertIn('rvu:', json.dumps(edits[-1][3]))
        self.assertEqual(self.notion.pages[PAGE]['properties']['쪽수']['number'], 368)

    def test_undo_button_reopens_choices(self):
        self.bot.handle_update(cb(GROUP, f'rv:{self.item.id}:0'))
        self.bot.handle_update(cb(GROUP, f'rvu:{self.item.id}'))
        last = [c for c in self.tg.calls if c[0] == 'edit_text'][-1]
        self.assertIn(f'rv:{self.item.id}:0', json.dumps(last[3]))
        self.assertEqual(self.notion.pages[PAGE]['properties']['쪽수']['number'], 320)

    def test_stale_choice_is_reported_to_admin(self):
        self.notion.pages[PAGE]['properties']['쪽수'] = number(300)
        self.bot.handle_update(cb(GROUP, f'rv:{self.item.id}:0'))
        self.assertTrue(any(c[1] == ADMIN for c in self.tg.calls if c[0] == 'send'))
        self.assertIn('바뀌', [c for c in self.tg.calls if c[0] == 'answer'][-1][2])

    def test_reply_to_review_message_is_kept_as_note_and_forwarded(self):
        self.bot.handle_update(msg(GROUP, '노션은 본문 기준이라 둘 다 맞아', reply_to=555))
        self.assertIn('본문 기준', ReviewItem.objects.get(pk=self.item.id).note)
        self.assertTrue(any(c[1] == ADMIN and '본문 기준' in c[2] for c in self.tg.calls if c[0] == 'send'))
        self.assertNotIn(REPLY_GUIDE, [c[2] for c in self.tg.calls if c[0] == 'send'])

    def test_admin_is_told_when_batch_is_done(self):
        self.bot.handle_update(cb(GROUP, f'rv:{self.item.id}:2'))
        self.assertTrue(any(c[1] == ADMIN and '모두' in c[2] for c in self.tg.calls if c[0] == 'send'))

    def test_status_counts_pending_reviews(self):
        self.bot.handle_update(msg(ADMIN, '/status', chat_type='private'))
        self.assertIn('확인 부탁 1건', self.tg.texts()[-1])


@override_settings(INTAKE=CONFIG)
class ReviewPostCommandTest(TestCase):
    def setUp(self):
        cat = Category.objects.create(name='종교')
        self.book = Book.objects.create(title='성서', full_price=16000, page_count=368, category=cat,
                                        published_date=date(2020, 9, 14))
        TelegramChat.objects.create(chat_id=ADMIN, kind=TelegramChat.ADMIN)
        TelegramChat.objects.create(chat_id=GROUP, kind=TelegramChat.REVIEWERS)
        WorkerState.put('mode', 'live')
        self.tg, self.notion = TG(), FakeNotion(쪽수=number(320))
        spec = {'batch': '2026-09-27 대조', 'intro': '안녕하세요',
                'items': [item_spec(book_id=self.book.id, expect={'쪽수': {'notion': 320, 'site': 368}}),
                          item_spec(book_id=self.book.id, title='바뀐 항목', expect={'쪽수': {'notion': 1, 'site': 368}})]}
        fd, self.path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w') as fh:
            json.dump(spec, fh, ensure_ascii=False)

    def run_cmd(self, *args):
        deps = mock.Mock(tg=self.tg, notion=self.notion, bot=Bot(self.tg, None, notion=self.notion, config=CONFIG))
        out = StringIO()
        with mock.patch('intake.management.commands.intake_review.build_deps', return_value=deps), \
                mock.patch('intake.management.commands.intake_review.time.sleep'):
            call_command('intake_review', self.path, *args, stdout=out)
        return out.getvalue()

    def test_posts_intro_and_items_to_reviewers_skipping_changed_ones(self):
        out = self.run_cmd()
        sent = [c for c in self.tg.calls if c[0] == 'send']
        self.assertEqual([c[1] for c in sent], [GROUP, GROUP])
        self.assertEqual(sent[0][2], '안녕하세요')
        self.assertIn('🔎 확인 부탁 1/1', sent[1][2])
        item = ReviewItem.objects.get()
        self.assertEqual((item.chat_id, item.message_id), (GROUP, 1002))
        self.assertIn('바뀐 항목', out)

    def test_dry_run_sends_nothing(self):
        out = self.run_cmd('--dry-run')
        self.assertEqual(self.tg.calls, [])
        self.assertFalse(ReviewItem.objects.exists())
        self.assertIn('확인 부탁 1/1', out)
