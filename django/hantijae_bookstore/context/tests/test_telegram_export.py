import tempfile
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from context.telegram_export import KST, parse_date, parse_export
from context.tests.export_fixture import write_fixture


class ParseExportTest(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_fixture(self.dir)
        self.messages, self.errors = parse_export(self.dir)
        self.by_id = {m.id: m for m in self.messages}

    def test_reads_messages_skips_service_and_counts_broken(self):
        self.assertEqual([m.id for m in self.messages], [100, 101, 102, 103, 104])
        self.assertEqual(self.errors, 1)

    def test_text_keeps_line_breaks_and_unescapes(self):
        m = self.by_id[100]
        self.assertEqual((m.author, m.text), ('대표님', '다음 주 북토크 010-1234-5678\n장소 & 시간'))
        self.assertEqual(m.at, datetime(2026, 9, 27, 22, 14, 10, tzinfo=KST))

    def test_joined_message_inherits_author_and_reply(self):
        m = self.by_id[101]
        self.assertEqual((m.author, m.reply_to, m.text), ('대표님', 100, '이어서 씀'))
        self.assertEqual(m.at.utcoffset(), timedelta(hours=9))

    def test_joined_message_inherits_author_across_files(self):
        m = self.by_id[103]
        self.assertEqual((m.author, m.media, m.media_name), ('한티재봇', 'document', '보도자료_010-9999-8888.pdf'))
        self.assertEqual(m.at, datetime(2026, 9, 27, 22, 17, tzinfo=KST))

    def test_forwarded_contact_keeps_no_details(self):
        m = self.by_id[104]
        self.assertEqual((m.forwarded, m.media, m.media_name, m.text, m.reply_to), (True, 'contact', '', '', 102))

    def test_parse_date_formats(self):
        self.assertEqual(parse_date('1 July 2026, 09:05:00 UTC+00:00'), datetime(2026, 7, 1, 9, 5, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            parse_date('어제')

    def test_missing_files(self):
        with self.assertRaises(FileNotFoundError):
            parse_export(tempfile.mkdtemp())
