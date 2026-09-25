"""Telegram Bot API 얇은 클라이언트 (requests)."""
import json

import requests


class TelegramError(Exception):
    pass


def keyboard(rows):
    return {'inline_keyboard': [[{'text': t, 'callback_data': d} for t, d in row] for row in rows]}


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
    def _reply(reply_to):
        return {'message_id': reply_to, 'allow_sending_without_reply': True} if reply_to else None

    def get_updates(self, offset, timeout=50):
        return self.call('getUpdates', _http_timeout=timeout + 15, offset=offset, timeout=timeout,
                         allowed_updates=['message', 'callback_query'])

    def send_message(self, chat_id, text, reply_to=None, buttons=None):
        return self.call('sendMessage', chat_id=chat_id, text=text[:4096],
                         reply_parameters=self._reply(reply_to), reply_markup=buttons)

    def send_photo(self, chat_id, photo, caption, buttons=None, reply_to=None):
        return self.call('sendPhoto', _files={'photo': ('cover.jpg', photo, 'image/jpeg')}, chat_id=chat_id,
                         caption=caption, reply_markup=buttons, reply_parameters=self._reply(reply_to))

    def edit_caption(self, chat_id, message_id, caption, buttons=None):
        try:
            self.call('editMessageCaption', chat_id=chat_id, message_id=message_id, caption=caption, reply_markup=buttons)
        except TelegramError as e:
            if 'message is not modified' not in str(e):
                raise

    def edit_text(self, chat_id, message_id, text, buttons=None):
        try:
            self.call('editMessageText', chat_id=chat_id, message_id=message_id, text=text[:4096], reply_markup=buttons)
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
