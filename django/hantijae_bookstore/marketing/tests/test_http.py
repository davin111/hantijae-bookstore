from unittest import mock

from django.test import SimpleTestCase

from marketing.http import http_get_bytes, http_get_json


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


class GetJsonTest(SimpleTestCase):
    def test_sends_extra_headers_and_returns_json(self):
        res = mock.Mock(**{'json.return_value': {'items': []}})
        with mock.patch('marketing.http.requests.get', return_value=res) as get:
            self.assertEqual(http_get_json('https://api.example/x?q=1', {'Authorization': 'KakaoAK k'}), {'items': []})
        headers = get.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'KakaoAK k')
        self.assertIn('User-Agent', headers)
        res.raise_for_status.assert_called_once()

    def test_http_error_raises(self):
        res = mock.Mock(**{'raise_for_status.side_effect': RuntimeError('429')})
        with mock.patch('marketing.http.requests.get', return_value=res), self.assertRaises(RuntimeError):
            http_get_json('https://api.example/x')
