import io
from datetime import datetime, timezone

from django.test import TestCase
from PIL import Image

from context import photos as P
from context.models import ContextEntry

NOW = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)


def png(w=3200, h=1000):
    out = io.BytesIO()
    Image.new('RGB', (w, h), 'white').save(out, 'PNG')
    return out.getvalue()


def photo(n, media='photo', name='', file_id=None, **kw):
    return ContextEntry.objects.create(key=f'tg:1:{n}', chat_id=1, message_id=n, media=media, media_name=name,
                                       file_id=f'f{n}' if file_id is None else file_id,
                                       at=datetime(2026, 9, 29, 1, n, tzinfo=timezone.utc), **kw)


class FakeAsk:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def __call__(self, system, user, images):
        self.calls.append((system, user, images))
        if self.error:
            raise self.error
        return self.reply(len(images)) if callable(self.reply) else self.reply


def download_ok(file_id, path):
    with open(path, 'wb') as fh:
        fh.write(png())
    return path


def items(n, text='10월 2일(금) 저녁 7시 강연 문의 010-1234-5678'):
    return {'items': [{'n': i, 'kind': '포스터', 'text': text, 'desc': ''} for i in range(1, n + 1)]}


class PhotoTest(TestCase):
    def test_pending_picks_unread_images_only(self):
        a = photo(1)
        b = photo(2, media='document', name='포스터.JPG')
        photo(3, media='document', name='공문.pdf')
        photo(4, file_id='')
        photo(5, forgotten=True)
        photo(6, media_read_at=NOW)
        photo(7, media='sticker')
        self.assertEqual(P.pending(), [a, b])

    def test_shrink_limits_long_side_and_makes_jpeg(self):
        img = Image.open(io.BytesIO(P.shrink(png())))
        self.assertEqual((img.format, max(img.size)), ('JPEG', 1600))

    def test_reads_in_batches_of_eight_and_redacts(self):
        es = [photo(i) for i in range(1, 11)]
        ask = FakeAsk(items)
        self.assertEqual(P.read_pending(ask, download_ok, NOW), 10)
        self.assertEqual([len(c[2]) for c in ask.calls], [8, 2])
        self.assertIn('1번부터 8번', ask.calls[0][1])
        e = ContextEntry.objects.get(pk=es[0].pk)
        self.assertEqual(e.media_text, '[포스터] 10월 2일(금) 저녁 7시 강연 문의 [전화]')
        self.assertEqual(e.media_read_at, NOW)
        self.assertEqual(P.pending(), [])

    def test_missing_answer_and_failed_download_are_marked_unreadable(self):
        a, b = photo(1), photo(2)

        def download(file_id, path):
            if file_id == 'f2':
                raise RuntimeError('file is too big')
            return download_ok(file_id, path)
        P.read_pending(FakeAsk({'items': [{'n': 7, 'kind': '포스터', 'text': 'x'}]}), download, NOW)
        for e in (a, b):
            self.assertEqual(ContextEntry.objects.get(pk=e.pk).media_text, P.UNREADABLE)

    def test_llm_error_leaves_batch_for_tomorrow(self):
        photo(1)
        with self.assertRaises(RuntimeError):
            P.read_pending(FakeAsk(error=RuntimeError('sidecar down')), download_ok, NOW)
        self.assertEqual(len(P.pending()), 1)

    def test_text_less_photo_keeps_description_and_is_clipped(self):
        a, b = photo(1), photo(2)
        P.read_pending(FakeAsk({'items': [{'n': 1, 'kind': '행사 사진', 'text': '', 'desc': '강연장 모습'},
                                          {'n': 2, 'kind': '문서', 'text': '가' * 5000}]}), download_ok, NOW)
        self.assertEqual(ContextEntry.objects.get(pk=a.pk).media_text, '[행사 사진] 강연장 모습')
        self.assertEqual(len(ContextEntry.objects.get(pk=b.pk).media_text), P.KEEP)
