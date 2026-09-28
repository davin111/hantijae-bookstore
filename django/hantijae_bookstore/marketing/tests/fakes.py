import json
from datetime import date

from books.models import Author, Book, BookAuthor, Category


class FakeTG:
    def __init__(self):
        self.calls, self.next_id = [], 1000

    def _msg(self):
        self.next_id += 1
        return {'message_id': self.next_id}

    def send_message(self, chat_id, text, reply_to=None, buttons=None):
        self.calls.append({'kind': 'send', 'chat': chat_id, 'text': text, 'reply_to': reply_to, 'buttons': buttons})
        return self._msg()

    def send_photo(self, chat_id, photo, caption, buttons=None, reply_to=None):
        self.calls.append({'kind': 'photo', 'chat': chat_id, 'text': caption, 'reply_to': reply_to, 'buttons': buttons})
        return self._msg()

    def edit_text(self, chat_id, message_id, text, buttons=None):
        self.calls.append({'kind': 'edit', 'chat': chat_id, 'text': text, 'buttons': buttons})

    def answer_callback(self, callback_id, text=''):
        self.calls.append({'kind': 'answer', 'text': text})

    def send_typing(self, chat_id):
        pass

    def sent(self, kind=None):
        return [c for c in self.calls if kind is None or c['kind'] == kind]


class FakeLLM:
    """replies: dict 하나(매번 같은 답) 또는 목록(차례로). 문자열이면 그대로 돌려준다."""

    def __init__(self, replies):
        self.queue = list(replies) if isinstance(replies, list) else None
        self.reply = None if isinstance(replies, list) else replies
        self.calls = []

    def complete(self, system, user, attachments=()):
        self.calls.append((system, user))
        reply = self.queue.pop(0) if self.queue is not None else self.reply
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)


def make_book(title='나는 산속으로 더 깊이 들어간다', subtitle='최정 시집', published=date(2026, 8, 21),
              isbn='979-11-92455-95-2', description='', author='최정', **extra):
    cat, _ = Category.objects.get_or_create(name='시')
    book = Book.objects.create(title=title, subtitle=subtitle, full_price=extra.pop('full_price', 12000),
                               page_count=extra.pop('page_count', 132), category=cat, published_date=published,
                               isbn=isbn, description=description, is_published=extra.pop('is_published', True),
                               **extra)
    if author:
        BookAuthor.objects.create(book=book, author=Author.objects.create(name=author))
    return book
