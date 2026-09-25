import base64
from unittest import mock

from django.test import SimpleTestCase

from intake import llm


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload


class SidecarClientTest(SimpleTestCase):
    def make(self, *responses):
        session = mock.Mock()
        session.post.side_effect = list(responses)
        return llm.SidecarClient('https://sidecar.example', 'tok', 'claude-opus-5-5[1m]', session=session), session

    def test_posts_complete_with_base64_attachments(self):
        client, session = self.make(FakeResponse(200, {'text': 'hi'}))
        out = client.complete('sys', 'user', [llm.Attachment('pdf', 'application/pdf', b'%PDF', 'a.pdf')])
        self.assertEqual(out, 'hi')
        url = session.post.call_args.args[0]
        body = session.post.call_args.kwargs['json']
        self.assertEqual(url, 'https://sidecar.example/complete')
        self.assertEqual(session.post.call_args.kwargs['headers']['Authorization'], 'Bearer tok')
        self.assertEqual(body['attachments'][0], {'kind': 'pdf', 'mediaType': 'application/pdf',
                                                  'data': base64.b64encode(b'%PDF').decode(), 'name': 'a.pdf'})
        self.assertNotIn('history', body)

    def test_status_mapping(self):
        for status, exc in ((401, llm.LLMAuthError), (403, llm.LLMAuthError), (429, llm.LLMTransientError),
                            (502, llm.LLMTransientError), (400, llm.LLMError)):
            client, _ = self.make(FakeResponse(status, {'error': 'x', 'message': 'm'}))
            with self.assertRaises(exc):
                client.complete('s', 'u')

    def test_retry_only_transient(self):
        client = mock.Mock()
        client.complete.side_effect = [llm.LLMTransientError('a'), llm.LLMTransientError('b'), 'ok']
        self.assertEqual(llm.complete_with_retry(client, 's', 'u', sleep=lambda s: None), 'ok')
        client.complete.side_effect = [llm.LLMAuthError('no')]
        with self.assertRaises(llm.LLMAuthError):
            llm.complete_with_retry(client, 's', 'u', sleep=lambda s: None)

    def test_parse_json_object_tolerates_fences_and_prose(self):
        self.assertEqual(llm.parse_json_object('```json\n{"a": 1}\n```'), {'a': 1})
        self.assertEqual(llm.parse_json_object('결과입니다:\n{"a": {"b": "}"}}\n이상입니다.'), {'a': {'b': '}'}})
        with self.assertRaises(llm.LLMInvalidJSON):
            llm.parse_json_object('JSON 없음')

    def test_complete_json_retries_once_with_reminder(self):
        client = mock.Mock()
        client.complete.side_effect = ['설명만 했어요', '{"ok": true}']
        self.assertEqual(llm.complete_json(client, 's', 'u', sleep=lambda s: None), {'ok': True})
        self.assertIn('JSON 객체 하나만', client.complete.call_args_list[1].args[1])
