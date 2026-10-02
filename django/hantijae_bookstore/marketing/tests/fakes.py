import html
import json
import re
from datetime import date

import requests
from books.models import Author, Book, BookAuthor, Category


class FakeTG:
    def __init__(self):
        self.calls, self.next_id = [], 1000

    def _msg(self):
        self.next_id += 1
        return {'message_id': self.next_id}

    def send_message(self, chat_id, text, reply_to=None, buttons=None, quote=None, html=False, quote_entities=None):
        self.calls.append({'kind': 'send', 'chat': chat_id, 'text': text, 'reply_to': reply_to, 'buttons': buttons,
                           'quote': quote, 'html': html, 'quote_entities': quote_entities})
        return self._msg()

    def send_photo(self, chat_id, photo, caption, buttons=None, reply_to=None):
        self.calls.append({'kind': 'photo', 'chat': chat_id, 'text': caption, 'reply_to': reply_to, 'buttons': buttons})
        return self._msg()

    def edit_text(self, chat_id, message_id, text, buttons=None, html=False):
        self.calls.append({'kind': 'edit', 'chat': chat_id, 'message_id': message_id, 'text': text, 'buttons': buttons,
                           'html': html})

    def edit_markup(self, chat_id, message_id, buttons):
        self.calls.append({'kind': 'markup', 'chat': chat_id, 'message_id': message_id, 'buttons': buttons})

    def answer_callback(self, callback_id, text=''):
        self.calls.append({'kind': 'answer', 'text': text})

    def send_typing(self, chat_id):
        pass

    def sent(self, kind=None):
        return [c for c in self.calls if kind is None or c['kind'] == kind]


def tg_message(html_text):
    """텔레그램이 parse_mode=HTML 메시지를 돌려주는 모양: (서식 없는 text, 굵게 entities). 길이·위치는 UTF-16 단위.
    이 모듈이 쓰는 <b>만 안다(다른 태그면 시험이 먼저 알게 멈춘다)."""
    from marketing.text import tg_len
    text, entities, start = '', [], None
    for part in re.split(r'(<[^>]+>)', html_text):
        if part == '<b>':
            start = tg_len(text)
        elif part == '</b>':
            entities.append({'type': 'bold', 'offset': start, 'length': tg_len(text) - start})
        elif part.startswith('<'):
            raise ValueError(f'tg_message: unknown tag {part}')
        else:
            text += html.unescape(part)
    return text, entities


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


class FakeApify:
    """start_run 답(차례로), get_run 답(차례로), 데이터셋 내용. 답이 예외면 던진다. 남은 답이 없으면 IndexError."""

    def __init__(self, starts=(), polls=(), datasets=None):
        self.starts, self.polls, self.datasets = list(starts), list(polls), dict(datasets or {})
        self.started, self.aborted = [], []

    @staticmethod
    def _next(queue):
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def start_run(self, actor, run_input, **kw):
        self.started.append((actor, run_input, kw))
        return self._next(self.starts)

    def get_run(self, run_id):
        if not self.polls:  # 준비한 답이 떨어지면 네트워크 오류처럼(코드는 이 경우 다음에 다시 본다)
            from marketing.apify import ApifyError
            raise ApifyError('no more polls')
        return self._next(self.polls)

    def abort_run(self, run_id):
        self.aborted.append(run_id)
        return {}

    def dataset_items(self, dataset_id, limit=500):
        return self.datasets[dataset_id]


def make_call(no='2167', state='ready', until=date(2026, 10, 12), posted=date(2026, 9, 29), **kw):
    """지원사업 공고 한 건(제3차 전자책 제작 지원 모양)."""
    from marketing.models import GrantCall
    verdict = {'relevant': True, 'reason': '종이책이 있는 책이면 신청할 수 있어요',
               'support': '전자책 제작비 지원(출판사당 10종까지)', 'prep': '출판유통통합전산망 가입, 종이책 정보 등록',
               'apply_from': '2026-10-02', 'until_time': '16:00', 'date_checked': until is not None}
    verdict.update(kw.pop('verdict', {}))
    return GrantCall.objects.create(key=f'kpipa:{no}', title=kw.pop('title', '2026년 제3차 전자책 제작 지원 사업 공고'),
                                    url=f'https://www.kpipa.or.kr/p/g1_2/{no}', posted_on=posted, state=state,
                                    apply_until=until, verdict=verdict, **kw)


def http_error(status):
    res = requests.Response()
    res.status_code = status
    return requests.HTTPError(str(status), response=res)


class FakeNotion:
    """노션 블록 나무를 메모리에 둔다. 진짜 API처럼 rich_text에 plain_text를 채워 돌려준다."""

    def __init__(self):
        self.blocks, self.kids, self.pages, self.calls, self.fail, self.n = {}, {}, {}, [], {}, 0
        self.timeouts = {}
        self.sticky = {}  # 메서드 이름 → 예외: 부를 때마다 계속 낸다(지워진 페이지처럼)
        self.bad_blocks = {}  # (메서드 이름, 블록 id) → 예외: 그 블록에만 계속 낸다(지워진 제목처럼)

    def _check(self, name, block_id=None):
        self.calls.append(name)
        if (name, block_id) in self.bad_blocks:
            raise self.bad_blocks[(name, block_id)]
        if name in self.sticky:
            raise self.sticky[name]
        if name in self.fail:
            raise self.fail.pop(name)

    def _plain(self, data):
        for r in data.get('rich_text', []):
            r['plain_text'] = r['text']['content']

    def _add(self, parent, block):
        block = json.loads(json.dumps(block))
        data = block[block['type']]
        children = data.pop('children', [])
        self._plain(data)
        self.n += 1
        bid = f'blk{self.n}'
        block.update(id=bid, object='block')
        self.blocks[bid] = block
        self.kids.setdefault(parent, []).append(bid)
        self.kids.setdefault(bid, [])
        for c in children:
            self._add(bid, c)
        return block

    def create_database(self, parent_page_id, title, properties):
        self._check('create_database')
        return {'id': 'db1', 'url': 'https://notion.test/db1', 'data_sources': [{'id': 'ds1'}]}

    def create_page(self, data_source_id, properties, children=()):
        self._check('create_page')
        self.n += 1
        pid = f'page{self.n}'
        self.pages[pid] = {'ds': data_source_id, 'properties': json.loads(json.dumps(properties)), 'in_trash': False}
        self.kids[pid] = []
        for c in children:
            self._add(pid, c)
        return {'id': pid, 'url': f'https://notion.test/{pid}'}

    def children(self, block_id, timeout=30):
        self._check('children')
        if block_id not in self.kids:
            raise http_error(404)
        return [self.blocks[i] for i in self.kids[block_id]]

    def append_children(self, block_id, children, timeout=10):
        self._check('append_children', block_id)
        if block_id not in self.kids:
            raise http_error(404)
        return [self._add(block_id, c) for c in children]

    def update_block(self, block_id, payload):
        self._check('update_block', block_id)
        for key, value in json.loads(json.dumps(payload)).items():
            self.blocks[block_id][key].update(value)
            self._plain(self.blocks[block_id][key])

    def update_page(self, page_id, properties, timeout=30):
        self._check('update_page', page_id)
        self.timeouts['update_page'] = timeout
        self.pages[page_id]['properties'].update(properties)

    def trash_page(self, page_id):
        self._check('trash_page')
        self.pages[page_id]['in_trash'] = True

    # ---- 시험용: 운영진이 노션에서 고친 것처럼 ----
    def edit(self, block_id, text):
        b = self.blocks[block_id]
        b[b['type']]['rich_text'] = [{'type': 'text', 'text': {'content': text}, 'plain_text': text}]

    def remove(self, block_id):
        for kids in self.kids.values():
            if block_id in kids:
                kids.remove(block_id)
        self.kids.pop(block_id, None)

    def text_of(self, block_id):
        b = self.blocks[block_id]
        return ''.join(r['plain_text'] for r in b[b['type']]['rich_text'])


class FakeBnkClient:
    """전산망 클라이언트 흉내. days: 날짜 → 행 목록 또는 예외(없는 날짜는 빈 목록). with 문을 쓸 수 있다."""
    def __init__(self, days=None, readers=None):
        self.days, self._readers = dict(days or {}), readers
        self.asked, self.entered, self.exited = [], False, False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.exited = True
        return False

    def sales_on(self, day):
        self.asked.append(day)
        value = self.days.get(day, [])
        if isinstance(value, Exception):
            raise value
        return value

    def readers(self, start, end):
        self.asked.append((start, end))
        return self._readers


def make_sale(day, total, book=None, isbn=None, title='책', **stores):
    from marketing.models import BnkSale
    from web.presenters import isbn13
    return BnkSale.objects.create(day=day, isbn=isbn or isbn13(book.isbn), book=book,
                                  title=book.title if book else title, total=total, **stores)
