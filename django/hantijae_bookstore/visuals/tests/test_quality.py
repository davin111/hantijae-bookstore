import copy
import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from intake.models import TelegramChat, WorkerState
from marketing.models import Draft, Proposal
from marketing.tests.fakes import make_book
from visuals import quality
from visuals.delivery import deliver
from visuals.handoff import deliver_handoff, package
from visuals.models import CardJob
from visuals.pipeline import enqueue, eligible, run_once

SOURCE = '학교급식이 멈추자 끼니를 놓치는 아이들을 걱정합니다. 청년 라이더에게 헬멧을 꼭 쓰라고 부탁합니다. 농약을 뿌리는 농민의 우비와 마스크를 걱정합니다. 먹는 이야기에서 시작해 일하는 사람들의 안부를 묻는 책입니다. ' * 2
EXCERPT = '청년 라이더에게 헬멧을 꼭 쓰라고 부탁합니다.'
CARDS = [
    {'layout': 'opening', 'heading': '누가 끼니를 놓쳤을까요', 'body': '급식이 멈추자 아이들의 끼니를 걱정합니다.'},
    {'layout': 'detail', 'heading': '일하는 사람의 안부', 'body': '농약을 뿌리는 농민의 우비와 마스크를 걱정합니다.'},
    {'layout': 'quote', 'heading': '안전을 바라는 마음', 'body': EXCERPT, 'credit': '한티재 공식 책 소개'},
]
for c in CARDS:
    c['evidence'] = [{'source': 's1', 'excerpt': EXCERPT}]


def review(ok=True):
    return {'checks': {k: ok for k in quality.CHECKS},
            'observations': [{'card': i, 'visible_text': c['heading'], 'assessment': '제목과 본문이 다른 크기로 분리되어 읽힙니다.'} for i, c in enumerate(CARDS, 1)],
            'issues': [] if ok else ['내용이 반복되어 장마다 구체적인 정보를 더해야 합니다.']}


class QualityTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        config = override_settings(VISUALS_ROOT=self.tmp.name)
        config.enable(); self.addCleanup(config.disable)
        clock = mock.patch('django.utils.timezone.now', return_value=timezone.now().replace(hour=4))
        clock.start(); self.addCleanup(clock.stop)
        WorkerState.put('visuals_mode', 'live'); WorkerState.put('marketing_mode', 'live')
        TelegramChat.objects.create(kind='reviewers', chat_id=-200)
        TelegramChat.objects.create(kind='admin', chat_id=100)
        self.book = make_book(description=SOURCE)
        p = Proposal.objects.create(book=self.book, kind='kit')
        self.draft = Draft.objects.create(proposal=p, channel='instagram', body='기존 소개', extra={'cards':[{'show':'글','text':'소개'}]})
        self.job = enqueue(self.draft, -200, 50)
        self.llm = mock.Mock()
        self.llm.complete.return_value = json.dumps({'cards': CARDS}, ensure_ascii=False)
        self.llm.review.return_value = json.dumps(review(), ensure_ascii=False)
        self.tg = mock.Mock()
        self.tg.call.side_effect = [[{'message_id':i} for i in (1,2,3)], {'message_id':4}]

    def test_reviewed_pixels_only_are_delivered_and_review_is_separate(self):
        run_once(self.llm, self.tg)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'sent')
        self.assertEqual(self.llm.complete.call_count, 1)
        self.assertEqual(self.llm.review.call_count, 1)
        images = self.llm.review.call_args.args[2]
        self.assertEqual(len(images), 6)
        self.assertEqual(Image.open(io.BytesIO(images[-1].data)).size, (360,450))
        self.assertTrue(quality.files_approved(self.job))

    def test_failed_review_never_sends_cards_to_room(self):
        self.llm.review.return_value = json.dumps(review(False), ensure_ascii=False)
        self.tg.call.side_effect = None; self.tg.call.return_value = {'message_id':90}
        run_once(self.llm, self.tg)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'handed_off')
        self.assertEqual(self.llm.review.call_count, 2)
        self.assertEqual(self.tg.call.call_count, 1)
        self.assertEqual(self.tg.call.call_args.kwargs['chat_id'], 100)
        self.assertEqual(self.job.receipt['handoff']['message_id'], 90)

    def test_image_api_failure_hands_off_without_automatic_pass_or_repeat(self):
        self.llm.review.side_effect = RuntimeError('private upstream detail')
        self.tg.call.side_effect = None; self.tg.call.return_value = {'message_id':90}
        run_once(self.llm, self.tg); run_once(self.llm, self.tg)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'handed_off')
        self.assertEqual(self.llm.review.call_count, 1)
        self.assertNotIn('private', self.job.error)
        self.assertEqual(self.tg.call.call_count, 1)

    def test_ambiguous_handoff_does_not_resend(self):
        self.llm.complete.side_effect = RuntimeError('offline')
        self.tg.call.side_effect = RuntimeError('timeout')
        run_once(self.llm, self.tg); run_once(self.llm, self.tg)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'handoff_uncertain')
        self.assertEqual(self.tg.call.call_count, 1)

    def test_claimed_sources_and_quotes_must_actually_exist(self):
        sources = quality.source_bundle(self.draft)
        for mutation in ('excerpt', 'quote', 'number'):
            cards = copy.deepcopy(CARDS)
            if mutation == 'excerpt': cards[0]['evidence'][0]['excerpt'] = '책에 없는 문장을 실제 발췌라고 꾸밉니다.'
            if mutation == 'quote': cards[-1]['body'] = '작가는 그런 말을 하지 않았습니다.'
            if mutation == 'number': cards[0]['body'] = '59명이 이 책을 빌렸습니다.'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                quality.validate_cards({'cards': cards}, sources, False)

    def test_unread_or_string_true_review_is_not_a_pass(self):
        for change in ('type', 'read'):
            data = review()
            if change == 'type': data['checks']['grounded'] = 'true'
            else: data['observations'][0]['visible_text'] = '실제 카드에 없는 내용'
            with self.assertRaises(ValueError): quality.checked_review(data, CARDS)

    def test_source_change_rechecks_only_unsent_and_does_not_resend_history(self):
        quality.assess(self.job, self.llm)
        type(self.book).objects.filter(pk=self.book.pk).update(description='변경된 원문 ' + SOURCE)
        self.assertFalse(eligible(self.job, timezone.now()))
        self.draft.refresh_from_db(); self.draft.proposal.book.refresh_from_db()
        same = enqueue(self.draft, -200, 50)
        self.assertEqual(same.pk, self.job.pk); self.assertEqual(same.state, 'queued')
        same.state, same.receipt = 'sent', {'images':[1],'document':2}; same.save()
        self.assertEqual(enqueue(self.draft, -200, 50).state, 'sent')
        self.assertEqual(CardJob.objects.count(), 1)

    def test_file_change_after_review_blocks_send(self):
        quality.assess(self.job, self.llm)
        (Path(self.tmp.name)/str(self.job.pk)/self.job.files[0]).write_bytes(b'changed')
        deliver(self.job, self.tg, lambda:True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'handoff'); self.tg.call.assert_not_called()

    def test_missing_original_still_produces_request_and_no_group_fallback(self):
        self.book.cover_image = 'missing.jpg'
        type(self.book).objects.filter(pk=self.book.pk).update(cover_image='missing.jpg')
        self.job.draft.proposal.book = self.book
        with mock.patch('django.db.models.fields.files.FieldFile.open', side_effect=OSError('missing')):
            archive = package(self.job)
        with zipfile.ZipFile(archive) as z:
            self.assertIn('제작 요청.md',z.namelist()); self.assertIn('출처.md',z.namelist())
            self.assertIn('표지 파일 수신 실패',z.read('원본 자료 안내.txt').decode())
        TelegramChat.objects.filter(kind='admin').delete()
        quality.hold(self.job,'확인 필요')
        deliver_handoff(self.job,self.tg,lambda:True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state,'handoff_waiting'); self.tg.call.assert_not_called()

    def test_cancelled_during_review_sends_neither_images_nor_request(self):
        def changed(*args):
            Draft.objects.filter(pk=self.draft.pk).update(status='posted')
            return json.dumps(review(False),ensure_ascii=False)
        self.llm.review.side_effect=changed
        run_once(self.llm,self.tg)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state,'cancelled'); self.tg.call.assert_not_called()

    def test_event_is_handed_off_without_turning_it_into_generic_book_promotion(self):
        self.draft.proposal.candidate_key = 'news:1'
        self.draft.proposal.save()
        quality.assess(self.job, self.llm)
        self.assertEqual(self.job.state, 'handoff')
        self.llm.complete.assert_not_called()

    def test_preexisting_unreviewed_ready_cannot_send_directly(self):
        self.job.state = 'ready'; self.job.save()
        deliver(self.job, self.tg, lambda: True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'handoff')
        self.tg.call.assert_not_called()

    def test_quiet_hours_do_not_send_personal_requests(self):
        quality.hold(self.job, '확인 필요')
        with mock.patch('visuals.handoff.in_quiet_hours', return_value=True):
            deliver_handoff(self.job, self.tg, lambda: True)
        self.tg.call.assert_not_called()

    def test_package_local_failure_uses_small_request_and_does_not_block_queue(self):
        quality.hold(self.job, '확인 필요')
        self.tg.call.side_effect = None; self.tg.call.return_value = {'message_id': 99}
        with mock.patch('visuals.handoff.package', side_effect=OSError('disk full')):
            deliver_handoff(self.job, self.tg, lambda: True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'handed_off')
        raw = self.tg.call.call_args.kwargs['_files']['document'][1]
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertIn('제작 요청.md', z.namelist())
            self.assertIn('게시글 초안.txt', z.namelist())

    def test_handoff_includes_other_books_and_event_source(self):
        from marketing.models import Signal
        other = make_book(title='다른 책', isbn='9791234567899', description='다른 책의 실제 소개 내용')
        p = self.draft.proposal
        p.extra = {'book_ids': [self.book.pk, other.pk]}
        p.signal = Signal.objects.create(kind='moment', key='event', title='저자와 만나는 자리', relevant=True,
                    url='https://example.org/event', detail={'event': {'location': '책방', 'status':'confirmed'}})
        p.save()
        with zipfile.ZipFile(package(self.job)) as z:
            sources = z.read('출처.md').decode()
        self.assertIn('다른 책의 실제 소개 내용', sources)
        self.assertIn('https://example.org/event', sources)
        self.assertIn('책방', sources)

    def test_changed_admin_during_packaging_is_not_sent_to_old_recipient(self):
        quality.hold(self.job, '확인 필요')
        real = package
        def changed(job):
            result = real(job)
            TelegramChat.objects.filter(chat_id=100).update(chat_id=101)
            return result
        with mock.patch('visuals.handoff.package', side_effect=changed):
            deliver_handoff(self.job, self.tg, lambda: True)
        self.tg.call.assert_not_called()

    def test_quiet_hours_starting_during_packaging_defer_delivery(self):
        quality.hold(self.job, '확인 필요')
        with mock.patch('visuals.handoff.in_quiet_hours', side_effect=[False, True]):
            deliver_handoff(self.job, self.tg, lambda: True)
        self.tg.call.assert_not_called()

    def test_reviewer_can_read_multiple_real_fields_separated_by_slash(self):
        data = review(False)
        for o, c in zip(data['observations'], CARDS):
            o['visible_text'] = c['heading'] + ' / ' + c['body']
        self.assertFalse(quality.checked_review(data, CARDS))
        data['observations'][0]['visible_text'] += ' / 이미지에 없는 새 문장'
        with self.assertRaises(ValueError):
            quality.checked_review(data, CARDS)

    def test_failed_revision_keeps_complete_preview_and_matching_copy(self):
        from visuals.editorial import render_editorial
        self.llm.review.return_value = json.dumps(review(False), ensure_ascii=False)
        count = 0
        def fail_second(cards, assets, folder, title):
            nonlocal count
            count += 1
            if count == 2:
                Path(folder).mkdir(parents=True, exist_ok=True)
                (Path(folder)/'01.png').write_bytes(b'incomplete replacement')
                raise ValueError('다시 편집 필요')
            return render_editorial(cards, assets, folder, title)
        with mock.patch('visuals.quality.render_editorial', side_effect=fail_second):
            quality.assess(self.job, self.llm)
        self.assertEqual(self.job.state, 'handoff')
        for name in self.job.files:
            with Image.open(Path(self.tmp.name)/str(self.job.pk)/name) as im:
                self.assertEqual(im.size, (1080,1350))
