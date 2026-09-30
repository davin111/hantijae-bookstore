from unittest import mock

import requests
from django.test import SimpleTestCase

from intake.telegram_api import TelegramAPI, TelegramError, keyboard


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


def _session(*replies):
    session = mock.Mock()
    session.post.side_effect = [mock.Mock(json=(lambda r=r: r)) for r in replies]
    return session


class TelegramAPIQuoteTest(SimpleTestCase):
    def test_quote_goes_into_reply_parameters(self):
        s = _session({'ok': True, 'result': {'message_id': 7}})
        TelegramAPI('T', session=s).send_message(1, '글', reply_to=5, quote='2. 항목')
        self.assertEqual(s.post.call_args.kwargs['json']['reply_parameters'],
                         {'message_id': 5, 'allow_sending_without_reply': True, 'quote': '2. 항목'})

    def test_rejected_quote_is_sent_again_without_quote(self):
        s = _session({'ok': False, 'description': 'Bad Request: QUOTE_TEXT_INVALID'},
                     {'ok': True, 'result': {'message_id': 8}})
        sent = TelegramAPI('T', session=s).send_message(1, '글', reply_to=5, quote='9. 없는 줄')
        self.assertEqual(sent['message_id'], 8)
        self.assertEqual(s.post.call_args.kwargs['json']['reply_parameters'],
                         {'message_id': 5, 'allow_sending_without_reply': True})

    def test_other_errors_are_not_retried(self):
        s = _session({'ok': False, 'description': 'Forbidden: bot was kicked from the group chat'})
        with self.assertRaises(TelegramError):
            TelegramAPI('T', session=s).send_message(1, '글', reply_to=5, quote='2. 항목')
        self.assertEqual(s.post.call_count, 1)

    def test_edit_markup_ignores_not_modified(self):
        s = _session({'ok': False, 'description': 'Bad Request: message is not modified'})
        TelegramAPI('T', session=s).edit_markup(1, 2, {'inline_keyboard': []})
        self.assertTrue(s.post.call_args.args[0].endswith('/editMessageReplyMarkup'))

    def test_keyboard_keeps_url_buttons(self):
        kb = keyboard([[('1번 글 보기', 'mk:b:1')], [{'text': '노션에서 크게 보기 ↗', 'url': 'https://n/p'}]])
        self.assertEqual(kb['inline_keyboard'][0][0], {'text': '1번 글 보기', 'callback_data': 'mk:b:1'})
        self.assertEqual(kb['inline_keyboard'][1][0], {'text': '노션에서 크게 보기 ↗', 'url': 'https://n/p'})
