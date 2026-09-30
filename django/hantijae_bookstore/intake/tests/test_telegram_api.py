from unittest import mock

import requests
from django.test import SimpleTestCase

from intake.telegram_api import TelegramAPI, TelegramError


class TelegramAPISecretTest(SimpleTestCase):
    def test_network_errors_do_not_leak_token(self):
        session = mock.Mock()
        session.post.side_effect = requests.ConnectionError('Max retries exceeded with url: /botSECRET123/getUpdates')
        with self.assertRaises(TelegramError) as ctx:
            TelegramAPI('SECRET123', session=session).get_updates(0)
        self.assertNotIn('SECRET123', str(ctx.exception))

    def test_download_errors_do_not_leak_token(self):
        session = mock.Mock()
        session.post.return_value = mock.Mock(json=lambda: {'ok': True, 'result': {'file_path': 'a.jpg'}})
        session.get.side_effect = requests.ConnectionError('url: /file/botSECRET123/a.jpg')
        with self.assertRaises(TelegramError) as ctx:
            TelegramAPI('SECRET123', session=session).download_file('f', '/tmp/x.jpg')
        self.assertNotIn('SECRET123', str(ctx.exception))

    def test_edit_text_calls_edit_message_text(self):
        session = mock.Mock()
        session.post.return_value = mock.Mock(json=lambda: {'ok': True, 'result': True})
        TelegramAPI('T', session=session).edit_text(1, 2, '본문')
        self.assertTrue(session.post.call_args.args[0].endswith('/editMessageText'))

    def test_get_updates_asks_for_edited_messages(self):
        session = mock.Mock()
        session.post.return_value = mock.Mock(json=lambda: {'ok': True, 'result': []})
        TelegramAPI('T', session=session).get_updates(5)
        self.assertEqual(session.post.call_args.kwargs['json']['allowed_updates'],
                         ['message', 'edited_message', 'callback_query'])


def _answers(*payloads):
    session = mock.Mock()
    session.post.side_effect = [mock.Mock(json=(lambda p=p: p)) for p in payloads]
    return session


class TelegramHtmlTest(SimpleTestCase):
    def test_html_message_uses_parse_mode_and_no_link_preview(self):
        session = _answers({'ok': True, 'result': {'message_id': 1}})
        TelegramAPI('T', session=session).send_message(5, '<b>굵게</b> &amp; 보통', html=True)
        sent = session.post.call_args.kwargs['json']
        self.assertEqual((sent['parse_mode'], sent['link_preview_options'], sent['text']),
                         ('HTML', {'is_disabled': True}, '<b>굵게</b> &amp; 보통'))

    def test_rejected_html_is_sent_again_as_plain_text(self):
        session = _answers({'ok': False, 'description': "Bad Request: can't parse entities: unexpected end tag"},
                           {'ok': True, 'result': {'message_id': 2}})
        with self.assertLogs('intake', 'WARNING'):
            result = TelegramAPI('T', session=session).send_message(5, '<b>굵게</i> &lt;지역서점&gt;', html=True)
        plain = session.post.call_args.kwargs['json']
        self.assertEqual((result['message_id'], plain['text'], 'parse_mode' in plain), (2, '굵게 <지역서점>', False))

    def test_other_errors_are_not_swallowed(self):
        session = _answers({'ok': False, 'description': 'Forbidden: bot was blocked by the user'})
        with self.assertRaises(TelegramError):
            TelegramAPI('T', session=session).send_message(5, '<b>x</b>', html=True)

    def test_too_long_html_goes_straight_to_plain_text(self):
        session = _answers({'ok': True, 'result': {'message_id': 3}})
        TelegramAPI('T', session=session).send_message(5, '<b>' + '가' * 5000 + '</b>', html=True)
        plain = session.post.call_args.kwargs['json']
        self.assertEqual((len(plain['text']), 'parse_mode' in plain), (4096, False))

    def test_edit_text_html(self):
        session = _answers({'ok': True, 'result': True})
        TelegramAPI('T', session=session).edit_text(1, 2, '<b>카드</b>', html=True)
        self.assertEqual(session.post.call_args.kwargs['json']['parse_mode'], 'HTML')

    def test_plain_messages_are_unchanged(self):
        session = _answers({'ok': True, 'result': {'message_id': 1}})
        TelegramAPI('T', session=session).send_message(5, '<그대로>')
        sent = session.post.call_args.kwargs['json']
        self.assertEqual((sent['text'], 'parse_mode' in sent), ('<그대로>', False))
