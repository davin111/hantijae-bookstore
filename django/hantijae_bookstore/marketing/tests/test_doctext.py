from django.test import SimpleTestCase

from marketing.doctext import document_text, pdf_text, xlsx_text
from marketing.tests.fakes import tiny_pdf, tiny_xlsx


class DocTextTest(SimpleTestCase):
    def test_pdf_text_extracts_isbn(self):
        self.assertIn('9791192455808', pdf_text(tiny_pdf('1 Book 9791192455808 Hantijae')))

    def test_xlsx_text_reads_shared_strings_and_number_cells(self):
        text = xlsx_text(tiny_xlsx(['무궁화호를 위하여', '한티재'], ['9791192455808']))
        self.assertIn('무궁화호를 위하여', text)
        self.assertIn('9791192455808', text)

    def test_document_text_picks_reader_by_extension(self):
        self.assertIn('9791192455808', document_text('선정도서 목록.PDF', tiny_pdf('9791192455808')))
        self.assertIn('한티재', document_text('목록.xlsx', tiny_xlsx(['한티재'])))
        self.assertEqual(document_text('공고문.hwp', b'anything'), '')
