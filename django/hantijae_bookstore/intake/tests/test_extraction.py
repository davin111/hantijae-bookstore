import json
import os
import tempfile
import zipfile
from unittest import mock

from django.test import SimpleTestCase
from PIL import Image

from intake import extraction
from intake.images import to_jpeg


def touch_image(path, size=(2000, 3000)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new('RGB', size, 'white').save(path, 'JPEG')


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, system, user, attachments=()):
        self.calls.append((system, user, list(attachments)))
        return json.dumps(self.reply, ensure_ascii=False)


class ImagesTest(SimpleTestCase):
    def test_to_jpeg_downscales_longest_side(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, 'a.png')
        Image.new('RGBA', (1000, 3000)).save(path)
        from io import BytesIO
        out = Image.open(BytesIO(to_jpeg(path, 1200)))
        self.assertEqual((out.format, max(out.size)), ('JPEG', 1200))


class RunExtractionTest(SimpleTestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        with open(os.path.join(self.root, '보도자료_무지개를변호하다.pdf'), 'wb') as f:
            f.write(b'%PDF-1.4 fake')
        touch_image(os.path.join(self.root, '무지개를변호하다_입체.jpeg'))
        touch_image(os.path.join(self.root, '무지개를변호하다_입체 그림자.jpeg'))
        with zipfile.ZipFile(os.path.join(self.root, '무지개를변호하다_미리보기.zip'), 'w') as z:
            src = os.path.join(self.root, 'tmp_front.jpg')
            touch_image(src)
            z.write(src, '무지개를변호하다_앞표지.jpg')
            os.remove(src)

    def test_pdf_and_images_are_attached_and_zip_is_expanded(self):
        client = FakeLLM({'title': '무지개를 변호하다', 'best_3d': '무지개를변호하다_입체 그림자.jpeg'})
        with mock.patch('intake.extraction.best_local_text', return_value=('원문', 0.9, 'x')):
            r = extraction.run_extraction(self.root, client, ['에세이'], ['단행본'])
        kinds = [a.kind for a in client.calls[0][2]]
        self.assertEqual(kinds[0], 'pdf')
        self.assertEqual(kinds.count('image'), 3)          # 앞표지 1 + 입체 후보 2
        self.assertTrue(r.front_cover.endswith('무지개를변호하다_앞표지.jpg'))
        self.assertTrue(r.cover_3d.endswith('입체 그림자.jpeg'))   # LLM 선택이 후보 안에 있으면 따른다
        self.assertEqual(r.data['title'], '무지개를 변호하다')
        self.assertEqual(r.source_text, '원문')

    def test_unknown_best_3d_falls_back_to_rule_order(self):
        client = FakeLLM({'title': 'x', 'best_3d': '없는파일.jpg'})
        with mock.patch('intake.extraction.best_local_text', return_value=('', 0.0, '')):
            r = extraction.run_extraction(self.root, client, [], [])
        self.assertTrue(r.cover_3d.endswith('무지개를변호하다_입체.jpeg'))

    def test_text_mode_when_no_pdf(self):
        os.remove(os.path.join(self.root, '보도자료_무지개를변호하다.pdf'))
        open(os.path.join(self.root, '보도자료_무지개를변호하다.hwp'), 'wb').close()
        client = FakeLLM({'title': 'x'})
        with mock.patch('intake.extraction.best_local_text', return_value=('헤더 본문', 0.9, 'a.hwp')):
            extraction.run_extraction(self.root, client, [], [])
        self.assertNotIn('pdf', [a.kind for a in client.calls[0][2]])
        self.assertIn('헤더 본문', client.calls[0][1])

    def test_ambiguous_press_release(self):
        open(os.path.join(self.root, '보도자료_다른책.pdf'), 'wb').close()
        with self.assertRaises(extraction.AmbiguousPressRelease) as ctx:
            extraction.run_extraction(self.root, FakeLLM({}), [], [])
        self.assertEqual(len(ctx.exception.candidates), 2)


class ZipNameTest(SimpleTestCase):
    def info(self, raw: bytes, flag=0):
        i = zipfile.ZipInfo(raw.decode('cp437'))
        i.flag_bits = flag
        return i

    def test_macos_utf8_names_without_flag_are_recovered(self):
        import unicodedata
        raw = unicodedata.normalize('NFD', '미리보기/사그라다파밀리아_앞표지.jpg').encode('utf-8')
        self.assertEqual(extraction.zip_member_name(self.info(raw)), '미리보기/사그라다파밀리아_앞표지.jpg')

    def test_windows_cp949_names_are_recovered(self):
        self.assertEqual(extraction.zip_member_name(self.info('앞표지.jpg'.encode('cp949'))), '앞표지.jpg')

    def test_junk_and_unsafe_entries_are_skipped(self):
        self.assertIsNone(extraction.zip_member_name(self.info(b'__MACOSX/._a.jpg')))
        self.assertIsNone(extraction.zip_member_name(self.info(b'dir/._a.jpg')))
        self.assertIsNone(extraction.zip_member_name(self.info(b'../../etc/passwd')))
        self.assertIsNone(extraction.zip_member_name(self.info(b'folder/')))


class TransparencyTest(SimpleTestCase):
    def test_transparent_png_becomes_white_not_black(self):
        from io import BytesIO
        path = os.path.join(tempfile.mkdtemp(), 't.png')
        Image.new('RGBA', (50, 50), (0, 0, 0, 0)).save(path)
        out = Image.open(BytesIO(to_jpeg(path, 100)))
        self.assertGreater(min(out.getpixel((10, 10))), 240)
