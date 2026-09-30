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


class TelegramAPIQuoteTest(SimpleTestCase):
    def test_quote_goes_into_reply_parameters(self):
        s = _answers({'ok': True, 'result': {'message_id': 7}})
        TelegramAPI('T', session=s).send_message(1, '글', reply_to=5, quote='2. 항목')
        self.assertEqual(s.post.call_args.kwargs['json']['reply_parameters'],
                         {'message_id': 5, 'allow_sending_without_reply': True, 'quote': '2. 항목'})

    def test_rejected_quote_is_sent_again_without_quote(self):
        s = _answers({'ok': False, 'description': 'Bad Request: QUOTE_TEXT_INVALID'},
                     {'ok': True, 'result': {'message_id': 8}})
        with self.assertLogs('intake', 'WARNING'):
            sent = TelegramAPI('T', session=s).send_message(1, '글', reply_to=5, quote='9. 없는 줄')
        self.assertEqual(sent['message_id'], 8)
        self.assertEqual(s.post.call_args.kwargs['json']['reply_parameters'],
                         {'message_id': 5, 'allow_sending_without_reply': True})

    def test_quote_rejection_is_recognized_in_any_case(self):
        s = _answers({'ok': False, 'description': 'Bad Request: quote_text_invalid'},
                     {'ok': True, 'result': {'message_id': 8}})
        with self.assertLogs('intake', 'WARNING'):
            sent = TelegramAPI('T', session=s).send_message(1, '글', reply_to=5, quote='9. 없는 줄')
        self.assertEqual((sent['message_id'], s.post.call_count), (8, 2))

    def test_other_errors_are_not_retried(self):
        s = _answers({'ok': False, 'description': 'Forbidden: bot was kicked from the group chat'})
        with self.assertRaises(TelegramError):
            TelegramAPI('T', session=s).send_message(1, '글', reply_to=5, quote='2. 항목')
        self.assertEqual(s.post.call_count, 1)

    def test_edit_markup_ignores_not_modified(self):
        s = _answers({'ok': False, 'description': 'Bad Request: message is not modified'})
        TelegramAPI('T', session=s).edit_markup(1, 2, {'inline_keyboard': []})
        self.assertTrue(s.post.call_args.args[0].endswith('/editMessageReplyMarkup'))

    def test_keyboard_keeps_url_buttons(self):
        kb = keyboard([[('1번 글 보기', 'mk:b:1')], [{'text': '노션에서 크게 보기 ↗', 'url': 'https://n/p'}]])
        self.assertEqual(kb['inline_keyboard'][0][0], {'text': '1번 글 보기', 'callback_data': 'mk:b:1'})
        self.assertEqual(kb['inline_keyboard'][1][0], {'text': '노션에서 크게 보기 ↗', 'url': 'https://n/p'})


class TelegramHtmlQuoteTest(SimpleTestCase):
    """서식(html)과 인용(quote)의 두 대체 경로가 함께 동작한다."""
    def test_quote_entities_go_with_the_quote(self):
        s = _answers({'ok': True, 'result': {'message_id': 7}})
        ents = [{'type': 'bold', 'offset': 0, 'length': 5}]
        TelegramAPI('T', session=s).send_message(1, '글', reply_to=5, quote='2. 항목', quote_entities=ents)
        self.assertEqual(s.post.call_args.kwargs['json']['reply_parameters'],
                         {'message_id': 5, 'allow_sending_without_reply': True, 'quote': '2. 항목',
                          'quote_entities': ents})

    def test_rejected_html_keeps_the_quote(self):
        s = _answers({'ok': False, 'description': "Bad Request: can't parse entities: unexpected end tag"},
                     {'ok': True, 'result': {'message_id': 8}})
        ents = [{'type': 'bold', 'offset': 0, 'length': 5}]
        with self.assertLogs('intake', 'WARNING'):
            TelegramAPI('T', session=s).send_message(1, '<b>글</i>', reply_to=5, quote='2. 항목', html=True,
                                                     quote_entities=ents)
        sent = s.post.call_args.kwargs['json']
        self.assertEqual((sent['text'], 'parse_mode' in sent, sent['reply_parameters']['quote'],
                          sent['reply_parameters']['quote_entities']), ('글', False, '2. 항목', ents))

    def test_rejected_quote_keeps_html_and_drops_quote_entities(self):
        s = _answers({'ok': False, 'description': 'Bad Request: QUOTE_TEXT_INVALID'},
                     {'ok': True, 'result': {'message_id': 9}})
        with self.assertLogs('intake', 'WARNING'):
            sent = TelegramAPI('T', session=s).send_message(1, '<b>글</b>', reply_to=5, quote='9. 없는 줄', html=True,
                                                            quote_entities=[{'type': 'bold', 'offset': 0, 'length': 6}])
        first, last = (c.kwargs['json'] for c in s.post.call_args_list)
        self.assertEqual((sent['message_id'], s.post.call_count, first['reply_parameters']['quote']), (9, 2, '9. 없는 줄'))
        self.assertEqual((last['text'], last['parse_mode'], last['reply_parameters']),
                         ('<b>글</b>', 'HTML', {'message_id': 5, 'allow_sending_without_reply': True}))

    def test_both_rejected_ends_plain_without_quote(self):
        parse = {'ok': False, 'description': "Bad Request: can't parse entities: x"}
        s = _answers(parse, {'ok': False, 'description': 'Bad Request: QUOTE_TEXT_INVALID'}, parse,
                     {'ok': True, 'result': {'message_id': 10}})
        with self.assertLogs('intake', 'WARNING'):
            sent = TelegramAPI('T', session=s).send_message(1, '<b>글</i>', reply_to=5, quote='9. 없는 줄', html=True)
        last = s.post.call_args.kwargs['json']
        self.assertEqual((sent['message_id'], last['text'], 'parse_mode' in last, 'quote' in last['reply_parameters']),
                         (10, '글', False, False))
