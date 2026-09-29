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


def tiny_pdf(text):
    """영문·숫자 한 줄짜리 최소 PDF. pdf_text 확인용(한글 글꼴은 넣지 않는다)."""
    stream = f'BT /F1 12 Tf 10 50 Td ({text}) Tj ET'.encode()
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R '
            b'/Resources << /Font << /F1 5 0 R >> >> >>',
            b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offsets = b'%PDF-1.4\n', []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % i + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
    out += b''.join(b'%010d 00000 n \n' % o for o in offsets)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)
    return out


def tiny_xlsx(strings, numbers=()):
    """sharedStrings에 strings, 첫 시트에 숫자 셀 numbers가 든 최소 엑셀."""
    import io
    import zipfile
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('xl/sharedStrings.xml', f'<sst xmlns="{ns}">' + ''.join(f'<si><t>{s}</t></si>' for s in strings)
                   + '</sst>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{ns}"><sheetData><row>'
                   + ''.join(f'<c><v>{n}</v></c>' for n in numbers) + '</row></sheetData></worksheet>')
    return buf.getvalue()


# ---- 운영진 개인 SNS(지어낸 계정·글. 실제 계정 주소·글은 공개 저장소에 넣지 않는다) ----
SOCIAL_ACCOUNTS = [
    {'role': 'editor', 'label': '편집장', 'facebook': 'https://www.facebook.com/editor.test', 'instagram': 'editor_ig'},
    {'role': 'ceo', 'label': '대표', 'facebook': 'https://www.facebook.com/ceo.test/', 'instagram': 'ceo_ig'},
]


def fb_item(post_id, account='editor.test', text='', time='2026-09-29T02:35:04.000Z', **extra):
    return {'postId': post_id, 'url': f'https://www.facebook.com/{account}/posts/{post_id}', 'time': time,
            'text': text, 'inputUrl': f'https://www.facebook.com/{account}',
            'facebookUrl': f'https://www.facebook.com/{account}', **extra}


def ig_item(post_id, owner='ceo_ig', caption='', ts='2026-09-18T09:15:24.000Z', **extra):
    return {'id': post_id, 'url': f'https://www.instagram.com/p/{post_id}/', 'timestamp': ts, 'caption': caption,
            'ownerUsername': owner, **extra}


def make_post(post_id, platform='facebook', account='editor', text='', posted_at=None, group_key=None, **extra):
    from datetime import datetime, timezone
    from marketing.models import SocialPost
    posted_at = posted_at or datetime(2026, 9, 18, 9, 10, tzinfo=timezone.utc)
    return SocialPost.objects.create(platform=platform, account=account, post_id=post_id,
                                     url=f'https://example.com/{platform}/{post_id}', posted_at=posted_at, text=text,
                                     first_seen=extra.pop('first_seen', posted_at), last_seen=posted_at,
                                     group_key=group_key if group_key is not None else f'post:{platform}:{post_id}',
                                     **extra)
