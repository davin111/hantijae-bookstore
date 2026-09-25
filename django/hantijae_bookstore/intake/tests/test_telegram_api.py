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
