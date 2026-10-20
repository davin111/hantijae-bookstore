from unittest import mock

from django.test import SimpleTestCase

from intake.llm import LLMAuthError, LLMTransientError
from visuals.client import VisualClient


class ClientTest(SimpleTestCase):
    def make_client(self, lines, status=200):
        response = mock.MagicMock(status_code=status)
        response.__enter__.return_value = response
        response.iter_lines.return_value = iter(lines)
        session = mock.Mock()
        session.post.return_value = response
        return VisualClient('https://sidecar.test', 'test-token', 'claude-test', session=session), session

    def test_only_completed_text_is_returned_without_interview_history(self):
        client, session = self.make_client([b'event: delta', b'data: "<svg>"', b'',
                                      b'event: delta', b'data: "</svg>"', b'',
                                      b'event: done', b'data: {"usage":{}}'])
        self.assertEqual(client.complete('system', 'user'), '<svg></svg>')
        request = session.post.call_args
        self.assertNotIn('history', request.kwargs['json'])
        self.assertTrue(request.args[0].endswith('/chat'))

    def test_partial_or_error_stream_is_never_used_as_art(self):
        for end in ([], [b'event: error', b'data: {"message":"sensitive upstream detail"}']):
            client, _ = self.make_client([b'event: delta', b'data: "<svg>"', *end])
            with self.assertRaises(LLMTransientError) as error:
                client.complete('system', 'user')
            self.assertNotIn('sensitive', str(error.exception))

    def test_authentication_failure_is_not_hidden(self):
        client, _ = self.make_client([], status=401)
        with self.assertRaises(LLMAuthError):
            client.complete('system', 'user')

    def test_pixel_review_uses_attachment_api_without_interview_history(self):
        from intake.llm import Attachment
        session = mock.Mock()
        session.post.return_value = mock.Mock(status_code=200)
        session.post.return_value.json.return_value = {'text': 'review result'}
        client = VisualClient('https://sidecar.test', 'token', 'claude-test', timeout=150, session=session)
        self.assertEqual(client.review('reviewer', 'sources', [Attachment('image','image/png',b'pixels','01.png')]), 'review result')
        request = session.post.call_args
        self.assertTrue(request.args[0].endswith('/complete'))
        self.assertNotIn('history', request.kwargs['json'])
        self.assertEqual(request.kwargs['json']['attachments'][0]['data'], 'cGl4ZWxz')
        self.assertEqual(request.kwargs['timeout'], 150)
