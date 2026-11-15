import os
import shutil
import tempfile
from unittest import mock

import docx
from django.test import TestCase, override_settings

from intake.bot import Bot
from intake.extract import extract_text
from intake.models import PendingPatch
from intake.tests import test_bot as helpers


@override_settings(INTAKE=helpers.CONFIG)
class SourceUpdatesTest(TestCase):
    setUp = helpers.BotTest.setUp

    def document(self, title='무지개를 변호하다'):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        path = os.path.join(root.name, '보도자료.docx')
        doc = docx.Document()
        doc.add_paragraph(title)
        doc.add_table(rows=1, cols=1).cell(0, 0).text = '책 정보 표'
        doc.add_paragraph('추천의 글\n원문 추천 문장입니다.')
        doc.save(path)
        return path

    def send(self, path, text='', reply_to=777, message_id=10):
        def download(file_id, dest):
            shutil.copyfile(path, dest)
            return dest
        with mock.patch.object(self.tg, 'download_file', side_effect=download):
            Bot(self.tg, helpers.FakeLLM({}), config=helpers.CONFIG).handle_update(helpers.msg(
                helpers.GROUP, text, reply_to=reply_to, message_id=message_id,
                document={'file_id': 'document', 'file_name': '보도자료.docx',
                          'mime_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}))

    def test_docx_tables_preserve_original_reading_order(self):
        self.assertEqual(extract_text(self.document()), '무지개를 변호하다\n책 정보 표\n추천의 글\n원문 추천 문장입니다.')

    def test_docx_nested_tables_preserve_all_text_in_document_order(self):
        path = self.document()
        document = docx.Document(path)
        cell = document.tables[0].cell(0, 0)
        cell.text = '표 안의 앞 문단'
        nested = cell.add_table(rows=1, cols=1)
        nested.cell(0, 0).text = '중첩 표의 원문'
        nested.cell(0, 0).add_paragraph('중첩 표의 다음 문단')
        cell.add_paragraph('표 안의 뒤 문단')
        document.save(path)
        expected = ('무지개를 변호하다\n표 안의 앞 문단\n중첩 표의 원문\n'
                    '중첩 표의 다음 문단\n표 안의 뒤 문단\n추천의 글\n원문 추천 문장입니다.')
        self.assertEqual(extract_text(path), expected)
        self.send(path)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.source_text, expected)

    def test_document_without_caption_updates_source_without_changing_book(self):
        self.send(self.document())
        self.draft.refresh_from_db()
        self.assertIn('추천의 글\n원문 추천 문장입니다.', self.draft.source_text)
        self.assertIn('sha256', self.draft.files['source_revision'])
        self.draft.book.refresh_from_db()
        self.assertEqual(self.draft.book.description, '')
        self.assertFalse(self.draft.book.is_published)

    def test_another_books_document_preserves_source_and_pending(self):
        self.draft.source_text = '기존 원자료'
        self.draft.save()
        p = PendingPatch.objects.create(draft=self.draft, base_version=1,
                                        changes=[{'field': 'subtitle', 'new_value': '대기 수정'}])
        self.send(self.document('다른 책 제목'))
        self.draft.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual(self.draft.source_text, '기존 원자료')
        self.assertEqual(p.status, PendingPatch.PROPOSED)
        self.assertIn('확인', self.tg.texts()[-1])

    def test_target_isbn_in_related_books_cannot_replace_another_books_source(self):
        self.draft.book.isbn = '979-11-92455-97-6'
        self.draft.book.save()
        for title in ('다른 책 제목', self.draft.book.title):
            with self.subTest(title=title):
                self.draft.source_text = '기존 원자료'
                self.draft.save()
                pending = PendingPatch.objects.create(draft=self.draft, base_version=1,
                    changes=[{'field': 'subtitle', 'new_value': '대기 수정'}])
                path = self.document(title)
                document = docx.Document(path)
                document.add_paragraph('ISBN: 979-11-92455-87-7')
                document.add_paragraph('함께 읽을 책: 무지개를 변호하다 ISBN 979-11-92455-97-6')
                document.save(path)
                self.send(path)
                self.draft.refresh_from_db()
                pending.refresh_from_db()
                self.assertEqual(self.draft.source_text, '기존 원자료')
                self.assertEqual(pending.status, PendingPatch.PROPOSED)

    def test_matching_isbn_without_matching_title_preserves_source_and_pending(self):
        self.draft.book.isbn = '979-11-92455-97-6'
        self.draft.book.save()
        self.draft.source_text = '기존 원자료'
        self.draft.save()
        pending = PendingPatch.objects.create(draft=self.draft, base_version=1,
            changes=[{'field': 'subtitle', 'new_value': '대기 수정'}])
        path = self.document('다른 책 제목')
        document = docx.Document(path)
        document.add_paragraph('ISBN: 979-11-92455-97-6')
        document.save(path)
        self.send(path)
        self.draft.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(self.draft.source_text, '기존 원자료')
        self.assertEqual(pending.status, PendingPatch.PROPOSED)

    def test_matching_title_and_single_isbn_accepts_source_replacement(self):
        self.draft.book.isbn = '979-11-92455-97-6'
        self.draft.book.save()
        path = self.document()
        document = docx.Document(path)
        document.add_paragraph('ISBN: 979-11-92455-97-6')
        document.save(path)
        self.send(path)
        self.draft.refresh_from_db()
        self.assertIn('ISBN: 979-11-92455-97-6', self.draft.source_text)
        self.assertIn('source_revision', self.draft.files)

    def test_corrupt_document_has_replyable_error_and_no_source_write(self):
        path = self.document()
        with open(path, 'wb') as out:
            out.write(b'broken')
        self.send(path)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.source_text, '')
        self.assertTrue(self.tg.texts())
        reply_id = self.tg.next_id
        bot = Bot(self.tg, helpers.FakeLLM({'changes': [{'field': 'subtitle', 'new_value': '재시도'}]}), config=helpers.CONFIG)
        bot.handle_update(helpers.msg(helpers.GROUP, '부제 변경', reply_to=reply_id, message_id=11))
        self.assertEqual(PendingPatch.objects.last().changes, [{'field': 'subtitle', 'new_value': '재시도'}])

    def test_source_that_cannot_fit_with_current_book_preserves_source_and_pending(self):
        self.draft.book.description = '기존 긴 본문. ' * 2800
        self.draft.book.save()
        self.draft.source_text = '기존 자료'
        self.draft.save()
        p = PendingPatch.objects.create(draft=self.draft, base_version=1,
            changes=[{'field': 'subtitle', 'new_value': '대기 부제'}])
        path = self.document()
        doc = docx.Document(path)
        doc.add_paragraph('새 원문. ' * 4000)
        doc.save(path)
        self.send(path)
        self.draft.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual(self.draft.source_text, '기존 자료')
        self.assertEqual(p.status, PendingPatch.PROPOSED)

    def test_download_failure_gives_replyable_error(self):
        from intake.telegram_api import TelegramError
        bot = Bot(self.tg, helpers.FakeLLM({}), config=helpers.CONFIG)
        with mock.patch.object(self.tg, 'download_file', side_effect=TelegramError('getFile timeout')):
            bot.handle_update(helpers.msg(helpers.GROUP, reply_to=777, document={
                'file_id': 'failed', 'file_name': '자료.docx', 'mime_type': 'application/octet-stream'}))
        self.assertTrue(any(c[0] == 'send' and c[1] == helpers.GROUP for c in self.tg.calls))
        reply_id = self.tg.next_id
        bot.llm = helpers.FakeLLM({'changes': [{'field': 'subtitle', 'new_value': '다시 요청'}]})
        bot.handle_update(helpers.msg(helpers.GROUP, '부제 변경', reply_to=reply_id, message_id=20))
        self.assertEqual(PendingPatch.objects.last().changes, [{'field': 'subtitle', 'new_value': '다시 요청'}])
