from unittest import mock

from django.test import SimpleTestCase

from marketing.http import http_get_bytes


class FakeResponse:
    """requests.get(..., stream=True) 로 받는 응답 흉내: with 블록 + iter_content."""

    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        return iter(self.chunks)


class HttpGetBytesTest(SimpleTestCase):
    def test_returns_joined_bytes_under_the_cap(self):
        resp = FakeResponse([b'abc', b'def'])
        with mock.patch('marketing.http.requests.get', return_value=resp) as get:
            self.assertEqual(http_get_bytes('https://x.kr/a.pdf'), b'abcdef')
        self.assertTrue(get.call_args.kwargs.get('stream'))

    def test_raises_when_total_size_passes_the_cap(self):
        resp = FakeResponse([b'a' * 10, b'b' * 10])
        with mock.patch('marketing.http.requests.get', return_value=resp):
            with self.assertRaises(ValueError):
                http_get_bytes('https://x.kr/a.pdf', max_bytes=10)
