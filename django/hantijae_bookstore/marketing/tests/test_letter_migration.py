import importlib

from django.apps import apps
from django.test import SimpleTestCase, TestCase

from marketing.models import Draft, Proposal
from marketing.tests.fakes import make_book

mig = importlib.import_module('marketing.migrations.0010_notion_copy')

BRIEF = '알리면 좋을 곳\n· 농업·생협 단체\n· 귀농·귀촌 모임\n\n보낼 글\n안녕하세요. 도서출판 한티재입니다.'
KIT = ('알리면 좋을 곳\n· 청송 지역 신문 ― 지역 시인\n· 귀농·귀촌 단체 ― 귀농 이야기\n\n'
       '보낼 글 (청송 지역 신문)\n제목: 신간 소식\n\n안녕하세요.\n\n도서출판 한티재 드림')


class SplitLetterTest(SimpleTestCase):
    def test_briefing_letter(self):
        title, body, extra = mig.split_letter('부탁드립니다', BRIEF)
        self.assertEqual((title, body), ('부탁드립니다', '안녕하세요. 도서출판 한티재입니다.'))
        self.assertEqual((extra['places'], extra['to'], extra['legacy']), (['농업·생협 단체', '귀농·귀촌 모임'], '', 'brief'))

    def test_kit_letter_moves_title_and_recipient(self):
        title, body, extra = mig.split_letter('', KIT)
        self.assertEqual((title, body), ('신간 소식', '안녕하세요.\n\n도서출판 한티재 드림'))
        self.assertEqual(extra['places'], ['청송 지역 신문 ― 지역 시인', '귀농·귀촌 단체 ― 귀농 이야기'])
        self.assertEqual((extra['to'], extra['legacy'], extra['title_moved']), ('청송 지역 신문', 'kit', True))

    def test_places_only_and_other_shapes_are_left_alone(self):
        self.assertIsNone(mig.split_letter('', '알리면 좋을 곳\n· 청송 지역 신문 ― 지역 시인'))
        self.assertIsNone(mig.split_letter('', '안녕하세요.'))
        # 머리에 목록 말고 다른 문단이 끼어 있으면 글을 잃지 않게 그대로 둔다
        self.assertIsNone(mig.split_letter('', '알리면 좋을 곳\n· A\n\n메모 문단\n\n보낼 글\n본문'))

    def test_join_restores_both_shapes(self):
        for title, body in (('부탁드립니다', BRIEF), ('', KIT)):
            self.assertEqual(mig.join_letter(*mig.split_letter(title, body)), (title, body))


class LetterMigrationTest(TestCase):
    def test_forward_and_backward(self):
        p = Proposal.objects.create(kind=Proposal.KIT, book=make_book(), headline='h')
        old = Draft.objects.create(proposal=p, channel=Draft.LETTER, body=KIT)
        new = Draft.objects.create(proposal=p, channel=Draft.LETTER, title='새 제목', body='새 편지',
                                   extra={'places': ['농민회 ― 이유'], 'to': '농민회'})
        mig.forward(apps, None)
        old.refresh_from_db()
        self.assertEqual((old.title, old.body, old.places), ('신간 소식', '안녕하세요.\n\n도서출판 한티재 드림',
                                                             ['청송 지역 신문 ― 지역 시인', '귀농·귀촌 단체 ― 귀농 이야기']))
        mig.backward(apps, None)
        old.refresh_from_db()
        new.refresh_from_db()
        self.assertEqual((old.title, old.body), ('', KIT))
        self.assertEqual((new.title, new.body),
                         ('', '알리면 좋을 곳\n· 농민회 ― 이유\n\n보낼 글 (농민회)\n제목: 새 제목\n\n새 편지'))

    def test_new_fields_have_empty_defaults(self):
        d = Draft.objects.create(proposal=Proposal.objects.create(kind=Proposal.KIT, book=make_book(), headline='h'),
                                 channel=Draft.INSTAGRAM, body='글')
        self.assertEqual((d.origin, d.extra, d.notion, d.places), (Draft.BOT, {}, {}, []))
