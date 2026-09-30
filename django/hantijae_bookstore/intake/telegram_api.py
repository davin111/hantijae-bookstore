"""Telegram Bot API 얇은 클라이언트 (requests)."""
import html
import json
import logging
import re

import requests


class TelegramError(Exception):
    pass


log = logging.getLogger('intake')
TEXT_LIMIT = 4096
HTML_OPTIONS = {'parse_mode': 'HTML', 'link_preview_options': {'is_disabled': True}}


def plain_text(html_text):
    """HTML 서식 글에서 태그를 벗기고 &amp; 같은 글자를 되돌린다(서식이 거부됐을 때 일반 글로 다시 보내려고)."""
    return html.unescape(re.sub(r'<[^>]+>', '', html_text))


def keyboard(rows):
    """버튼 줄. (글, 콜백) 짝은 콜백 버튼, dict는 그대로 둔다(예: {'text': …, 'url': …} 링크 버튼)."""
    return {'inline_keyboard': [[b if isinstance(b, dict) else {'text': b[0], 'callback_data': b[1]} for b in row]
                                for row in rows]}


class TelegramAPI:
    def __init__(self, token, session=None, base='https://api.telegram.org'):
        self.token, self.base = token, base
        self.session = session or requests.Session()

    def call(self, method, _files=None, _http_timeout=60, **params):
        url = f'{self.base}/bot{self.token}/{method}'
        params = {k: v for k, v in params.items() if v is not None}
        try:
            if _files:
                data = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                        for k, v in params.items()}
                res = self.session.post(url, data=data, files=_files, timeout=_http_timeout)
            else:
                res = self.session.post(url, json=params, timeout=_http_timeout)
            payload = res.json()
        except (requests.RequestException, ValueError) as e:
            # requests 예외 문구에는 URL(= 봇 토큰)이 들어간다. from None 으로 원본 예외 체인도 끊는다.
            raise TelegramError(f'{method}: {self._redact(e)}') from None
        if not payload.get('ok'):
            raise TelegramError(f"{method}: {payload.get('description')}")
        return payload['result']

    def _redact(self, e):
        return str(e).replace(self.token, '***') if self.token else str(e)

    @staticmethod
    def _reply(reply_to, quote=None, quote_entities=None):
        if not reply_to:
            return None
        params = {'message_id': reply_to, 'allow_sending_without_reply': True}
        if quote:  # 답장 위에 원래 메시지의 이 줄만 보인다(복사할 때는 따라오지 않는다)
            params['quote'] = quote
            if quote_entities:  # 굵게 줄은 서식까지 같아야 인용을 받아 준다(2026-09-30 확인)
                params['quote_entities'] = quote_entities
        return params

    def get_updates(self, offset, timeout=50):
        return self.call('getUpdates', _http_timeout=timeout + 15, offset=offset, timeout=timeout,
                         allowed_updates=['message', 'edited_message', 'callback_query'])

    def send_message(self, chat_id, text, reply_to=None, buttons=None, quote=None, html=False, quote_entities=None):
        """html=True: 굵게·접기 같은 HTML 서식. 너무 길거나 텔레그램이 서식을 거부하면 태그를 벗긴 일반 글로 보낸다.
        quote: 답장 위에 보일 원래 메시지의 줄(quote_entities: 그 줄의 굵게 같은 서식 — 원래 메시지가 서식 글이면 같아야
        받아 준다). 텔레그램이 인용을 거절하면(QUOTE_TEXT_INVALID 등) 인용 없이 한 번 더 보낸다."""
        try:
            return self._send_text(chat_id, text, reply_to, buttons, html, quote, quote_entities)
        except TelegramError as e:
            if not (quote and 'quote' in str(e).lower()):  # 오류 글의 대소문자는 믿지 않는다
                raise
            log.warning('telegram quote rejected, sending without quote: %s', e)
        return self._send_text(chat_id, text, reply_to, buttons, html)

    def _send_text(self, chat_id, text, reply_to, buttons, html, quote=None, quote_entities=None):
        common = {'chat_id': chat_id, 'reply_parameters': self._reply(reply_to, quote, quote_entities),
                  'reply_markup': buttons}
        if html and len(text) <= TEXT_LIMIT:
            try:
                return self.call('sendMessage', text=text, **HTML_OPTIONS, **common)
            except TelegramError as e:
                if "can't parse entities" not in str(e):
                    raise
                log.warning('telegram html rejected, sending plain text: %s', e)
        return self.call('sendMessage', text=(plain_text(text) if html else text)[:TEXT_LIMIT], **common)

    def edit_markup(self, chat_id, message_id, buttons):
        try:
            self.call('editMessageReplyMarkup', chat_id=chat_id, message_id=message_id, reply_markup=buttons)
        except TelegramError as e:
            if 'message is not modified' not in str(e):
                raise

    def send_photo(self, chat_id, photo, caption, buttons=None, reply_to=None):
        return self.call('sendPhoto', _files={'photo': ('cover.jpg', photo, 'image/jpeg')}, chat_id=chat_id,
                         caption=caption, reply_markup=buttons, reply_parameters=self._reply(reply_to))

    def edit_caption(self, chat_id, message_id, caption, buttons=None):
        try:
            self.call('editMessageCaption', chat_id=chat_id, message_id=message_id, caption=caption, reply_markup=buttons)
        except TelegramError as e:
            if 'message is not modified' not in str(e):
                raise

    def edit_text(self, chat_id, message_id, text, buttons=None, html=False):
        common = {'chat_id': chat_id, 'message_id': message_id, 'reply_markup': buttons}
        try:
            if html and len(text) <= TEXT_LIMIT:
                try:
                    return self.call('editMessageText', text=text, **HTML_OPTIONS, **common)
                except TelegramError as e:
                    if "can't parse entities" not in str(e):
                        raise
                    log.warning('telegram html rejected, editing as plain text: %s', e)
            self.call('editMessageText', text=(plain_text(text) if html else text)[:TEXT_LIMIT], **common)
        except TelegramError as e:
            if 'message is not modified' not in str(e):
                raise

    def answer_callback(self, callback_id, text=''):
        self.call('answerCallbackQuery', callback_query_id=callback_id, text=text[:200] or None)

    def send_typing(self, chat_id):
        self.call('sendChatAction', chat_id=chat_id, action='typing')

    def download_file(self, file_id, dest_path):
        info = self.call('getFile', file_id=file_id)   # 봇 API는 20MB까지
        try:
            with self.session.get(f"{self.base}/file/bot{self.token}/{info['file_path']}", stream=True,
                                  timeout=120) as res:
                res.raise_for_status()
                with open(dest_path, 'wb') as fh:
                    for chunk in res.iter_content(1 << 16):
                        fh.write(chunk)
        except requests.RequestException as e:
            raise TelegramError(f'download: {self._redact(e)}') from None
        return dest_path
