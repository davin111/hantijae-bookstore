from datetime import datetime, timezone

from django.test import TestCase

from context.models import ContextEntry, Participant
from context.record import apply_edit, forget, record_telegram

GROUP, DATE = -259, 1790000000


def tg_msg(message_id=10, text='안녕하세요', **extra):
    m = {'message_id': message_id, 'date': DATE, 'chat': {'id': GROUP, 'type': 'group'},
         'from': {'id': 11, 'is_bot': False, 'first_name': '검수자A'}}
    if text is not None:
        m['text'] = text
    m.update(extra)
    return m


class RecordTest(TestCase):
    def test_text_is_redacted_and_role_resolved(self):
        Participant.objects.create(role='운영진A', telegram_user_id=11)
        e = record_telegram(tg_msg(text='연락처 010-1234-5678'))
        self.assertEqual((e.text, e.redactions, e.role), ('연락처 [전화]', {'phone': 1}, '운영진A'))
        self.assertEqual((e.key, e.origin, e.chat_id, e.message_id), (f'tg:{GROUP}:10', 'live', GROUP, 10))
        self.assertEqual(e.at, datetime.fromtimestamp(DATE, tz=timezone.utc))
        self.assertEqual(e.author_name, '검수자A')

    def test_same_message_twice_keeps_one_row(self):
        record_telegram(tg_msg())
        record_telegram(tg_msg())
        self.assertEqual(ContextEntry.objects.count(), 1)

    def test_photo_caption_and_largest_file_id(self):
        e = record_telegram(tg_msg(text=None, photo=[{'file_id': 'small'}, {'file_id': 'big'}], caption='포스터예요'))
        self.assertEqual((e.media, e.file_id, e.text), ('photo', 'big', '포스터예요'))

    def test_document_name_is_redacted(self):
        e = record_telegram(tg_msg(text=None, document={'file_id': 'd1', 'file_name': '주문_010-1234-5678.xlsx'}))
        self.assertEqual((e.media, e.media_name, e.redactions), ('document', '주문_[전화].xlsx', {'phone': 1}))

    def test_contact_keeps_no_phone(self):
        e = record_telegram(tg_msg(text=None, contact={'phone_number': '01012345678', 'first_name': '독자'}))
        self.assertEqual((e.media, e.text, e.media_name, e.file_id), ('contact', '', '', ''))

    def test_sticker_only_message(self):
        e = record_telegram(tg_msg(text=None, sticker={'file_id': 's1'}))
        self.assertEqual((e.media, e.text), ('sticker', ''))

    def test_reply_and_forward_flags(self):
        e = record_telegram(tg_msg(reply_to_message={'message_id': 5, 'from': {'is_bot': True}},
                                   forward_origin={'type': 'hidden_user', 'sender_user_name': '누군가'}))
        self.assertEqual((e.reply_to_id, e.reply_to_bot, e.forwarded), (5, True, True))

    def test_anonymous_sender_uses_chat_title(self):
        m = tg_msg(sender_chat={'id': GROUP, 'title': '한티재'})
        del m['from']
        e = record_telegram(m)
        self.assertEqual((e.author_id, e.author_name, e.role), (None, '한티재', '참여자'))

    def test_other_bot_is_labelled_bot(self):
        e = record_telegram(tg_msg(**{'from': {'id': 5, 'is_bot': True, 'first_name': '다른봇'}}))
        self.assertEqual(e.role, '봇')

    def test_edit_updates_text(self):
        record_telegram(tg_msg())
        e = apply_edit(tg_msg(text='고친 글 010-1111-2222', edit_date=DATE + 60))
        self.assertEqual((e.text, e.redactions), ('고친 글 [전화]', {'phone': 1}))
        self.assertEqual(e.edited_at, datetime.fromtimestamp(DATE + 60, tz=timezone.utc))

    def test_edit_of_unrecorded_message_is_ignored(self):
        self.assertIsNone(apply_edit(tg_msg(message_id=99, edit_date=DATE + 60)))
        self.assertFalse(ContextEntry.objects.exists())

    def test_forget_blanks_the_record_and_keeps_a_tombstone(self):
        record_telegram(tg_msg(text='비밀 이야기'))
        self.assertTrue(forget(GROUP, 10))
        e = ContextEntry.objects.get()
        self.assertEqual((e.forgotten, e.text, e.media_name, e.file_id, e.redactions), (True, '', '', '', {}))
        self.assertFalse(forget(GROUP, 11))

    def test_forgotten_record_is_not_restored_by_redelivery_or_edit(self):
        record_telegram(tg_msg(text='비밀 이야기'))
        forget(GROUP, 10)
        record_telegram(tg_msg(text='비밀 이야기'))
        apply_edit(tg_msg(text='고친 비밀 이야기', edit_date=DATE + 60))
        e = ContextEntry.objects.get()
        self.assertEqual((e.forgotten, e.text), (True, ''))

    def test_forget_falls_back_to_imported_row_by_time(self):
        ContextEntry.objects.create(key=f'tgx:{GROUP}:500', origin='export', chat_id=GROUP, text='옛 글',
                                    at=datetime.fromtimestamp(DATE, tz=timezone.utc))
        self.assertTrue(forget(GROUP, 77, sent_at=datetime.fromtimestamp(DATE, tz=timezone.utc)))
        self.assertEqual(ContextEntry.objects.get(key=f'tgx:{GROUP}:500').text, '')
