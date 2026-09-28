"""검수 방·관리자 방에서의 마케팅 비서. intake.Bot이 명령·콜백·답장을 이 객체로 넘긴다(host = intake.Bot)."""
import io
import logging
import re
from datetime import date, datetime

from django.utils import timezone
from PIL import Image

from books.models import Book
from intake.llm import LLMError, complete_json
from intake.models import TelegramChat, WorkerState
from marketing import briefing as briefing_mod
from marketing import kit as kit_mod
from marketing import messages
from marketing.hooks import add_hook, upcoming
from marketing.models import BookProfile, Briefing, CopyNote, Draft, DraftMessage, Proposal, WatchQuery
from marketing.prompts import REWRITE_SYSTEM, build_rewrite_user
from marketing.text import fix_title_marks, title_key
from marketing.timeutil import KST, in_quiet_hours, kst_today, week_start
from web.blog import fetch_rss, parse_rss

log = logging.getLogger('intake')
COMMANDS = ('/brief', '/kit', '/mk', '/hook', '/quiet', '/watch')
MODES = ('off', 'admin_only', 'live')
KIT_DAILY_CAP = 2
USAGE = ('사용법: /mk off|admin_only|live · /brief [send] · /kit <제목 일부> · /kit send <번호> · '
         '/hook <MM-DD> <이름> | <책1>, <책2> · /hook list · /quiet <제목 일부> <YYYY-MM-DD> [이유] · /quiet list · '
         '/watch <이름> · /watch list · /watch off <번호>')


def cover_jpeg(book):
    field = book.cover_image_3d or book.cover_image
    if not field:
        return None
    try:
        with field.open('rb') as fh:
            img = Image.open(io.BytesIO(fh.read()))
            img.load()
    except Exception:
        return None
    if img.mode in ('RGBA', 'LA', 'P'):  # 투명 배경은 흰 바탕에 얹는다
        img = img.convert('RGBA')
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert('RGB')
    img.thumbnail((1280, 1280))
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=88)
    return out.getvalue()


def find_books(fragment):
    fragment = (fragment or '').strip()
    if not fragment:
        return []
    return list(Book.objects.filter(is_published=True, title__icontains=fragment).order_by('-published_date')[:5])


def _narrow(books):
    return '책을 하나로 좁혀 주세요: ' + (', '.join(f'『{b.title}』' for b in books) if books else '찾은 책 없음')


def _book_for_query(query):
    """R6: /watch 로 추가하는 질의를 책에 연결한다 — 저자 이름이 정확히 같은 책, 없으면 제목이 같은 책."""
    by_author = (Book.objects.filter(is_published=True, authors__author__name=query)
                 .order_by('-published_date').first())
    if by_author:
        return by_author
    key = title_key(query)
    if not key:
        return None
    for book in Book.objects.filter(is_published=True).order_by('-published_date'):
        if title_key(book.title) == key:
            return book
    return None


class Marketing:
    def __init__(self, tg, llm, host):
        self.tg, self.llm, self.host = tg, llm, host

    # ---- 받는 곳 ----
    @staticmethod
    def mode():
        return WorkerState.get('marketing_mode', 'off')

    def target_chat(self):
        mode = self.mode()
        if mode == 'live':
            return self.host.review_chat_id()
        if mode == 'admin_only':
            return self.host._chat(TelegramChat.ADMIN)
        return None

    def owns_message(self, chat_id, message_id):
        return any(model.objects.filter(chat_id=chat_id, message_id=message_id).exists()
                   for model in (DraftMessage, Draft, Proposal, Briefing))

    @staticmethod
    def blog_posts():
        """블로그 최근 글 50개. 못 읽으면 None(블로그 공백 판단을 건너뛰게)."""
        try:
            return parse_rss(fetch_rss(timeout=10), limit=50)
        except Exception:
            return None

    # ---- 보내기 ----
    def send_kit(self, proposal, chat):
        drafts = list(proposal.drafts.filter(parent__isnull=True).order_by('id'))
        caption = messages.kit_caption(proposal.book, drafts, proposal.extra.get('missing_stores', []),
                                       proposal.extra.get('blog_exists', False))
        buttons = messages.kit_buttons(proposal, drafts)
        photo = cover_jpeg(proposal.book)
        sent = (self.tg.send_photo(chat, photo, caption, buttons=buttons) if photo
                else self.tg.send_message(chat, caption, buttons=buttons))
        return sent['message_id']

    def _mark_sent(self, proposal, chat, message_id, now):
        proposal.chat_id, proposal.message_id, proposal.sent_at, proposal.status = chat, message_id, now, Proposal.SHOWN
        proposal.save(update_fields=['chat_id', 'message_id', 'sent_at', 'status', 'updated_at'])

    @staticmethod
    def _day_start(now):
        return datetime.combine(kst_today(now), datetime.min.time(), tzinfo=KST)

    def send_pending_kits(self, now):
        chat = self.target_chat()
        if chat is None or in_quiet_hours(now):
            return 0
        room = KIT_DAILY_CAP - Proposal.objects.filter(kind=Proposal.KIT, sent_at__gte=self._day_start(now)).count()
        pending = (Proposal.objects.filter(kind=Proposal.KIT, sent_at__isnull=True, status=Proposal.PROPOSED)
                   .exclude(book__marketing__quiet_until__gte=kst_today(now))  # 쉬는 책은 쉬는 날이 지나면 보낸다
                   .select_related('book').order_by('id')[:max(room, 0)])
        n = 0
        for p in pending:
            try:
                self._mark_sent(p, chat, self.send_kit(p, chat), now)
            except Exception:  # 카드 하나가 실패해도 나머지는 보낸다. 실패한 것은 다음 바퀴에 다시 해 본다
                log.exception('marketing kit %s send failed', p.id)
                continue
            n += 1
        return n

    def send_briefing(self, briefing, now, chat=None, record=True):
        chat = chat or self.target_chat()
        if chat is None or (record and (briefing.sent_at or in_quiet_hours(now))):
            return False
        items = list(briefing.items.order_by('rank'))
        if not items:
            return False
        sent = self.tg.send_message(chat, messages.briefing_text(briefing.week_start, items, briefing.measure),
                                    buttons=messages.briefing_buttons(briefing, items))
        if record:
            briefing.chat_id, briefing.message_id, briefing.sent_at, briefing.mode = chat, sent['message_id'], now, self.mode()
            briefing.save(update_fields=['chat_id', 'message_id', 'sent_at', 'mode'])
            Proposal.objects.filter(briefing=briefing).update(status=Proposal.SHOWN, chat_id=chat)
        return True

    def _send_draft(self, draft, chat_id, reply_to=None, note=''):
        sent = self.tg.send_message(chat_id, messages.draft_text(draft, note), reply_to=reply_to,
                                    buttons=messages.draft_buttons(draft))
        Draft.objects.filter(pk=draft.pk).update(chat_id=chat_id, message_id=sent['message_id'])  # 마지막 사본
        DraftMessage.objects.create(draft=draft, chat_id=chat_id, message_id=sent['message_id'])

    @staticmethod
    def _draft_for_message(chat_id, message_id):
        """답장한 메시지가 보낸 초안 사본이면 그 초안. 예전 기록(Draft.chat_id/message_id)도 본다."""
        sent = (DraftMessage.objects.filter(chat_id=chat_id, message_id=message_id)
                .select_related('draft__proposal__book').first())
        if sent:
            return sent.draft
        return Draft.objects.filter(chat_id=chat_id, message_id=message_id).select_related('proposal__book').first()

    @staticmethod
    def _newest(proposal_id, channel=None):
        qs = Draft.objects.filter(proposal_id=proposal_id)
        if channel:
            qs = qs.filter(channel=channel)
        return qs.order_by('-version', '-id').first()

    # ---- 버튼 ----
    def handle_callback(self, data, chat_id, cq, actor):
        action, pk = messages.parse_cb(data)
        here = cq['message']['message_id']
        if action == 'v':
            d = Draft.objects.filter(pk=pk).first()
            if d:
                self._send_draft(self._newest(d.proposal_id, d.channel), chat_id, reply_to=here)
            return ''
        if action == 'b':
            d = self._newest(pk)
            if d:
                self._send_draft(d, chat_id, reply_to=here)
            return ''
        if action == 'm':
            p = Proposal.objects.filter(pk=pk).first()
            if p:
                if p.caution:
                    self.tg.send_message(chat_id, '조심할 점\n\n' + p.caution, reply_to=here)
                for d in p.drafts.filter(channel__in=(Draft.LINKS, Draft.SHORT, Draft.LETTER), parent__isnull=True).order_by('id'):
                    self._send_draft(self._newest(p.id, d.channel), chat_id, reply_to=here)
            return ''
        if action == 'p':
            d = Draft.objects.filter(pk=pk).first()
            if not d:
                return ''
            Draft.objects.filter(pk=pk).update(status=Draft.POSTED, posted_at=timezone.now(), posted_by=actor[:100])
            Proposal.objects.filter(pk=d.proposal_id).update(status=Proposal.ACTED)
            self.tg.send_message(chat_id, '기록해 둘게요. 2주쯤 뒤 판매 지수가 어떻게 달라졌는지 브리핑에 적어 드릴게요.', reply_to=here)
            return '기록했어요'
        if action == 'e':
            return '이 초안에 답장으로 고칠 점을 적어 주세요'
        if action == 'l':
            Draft.objects.filter(pk=pk).update(status=Draft.SKIPPED)
            return '알겠어요'
        if action == 'sk':
            Proposal.objects.filter(pk=pk, kind=Proposal.KIT).update(status=Proposal.SKIPPED)
            return '이번엔 넘길게요'
        if action == 'sw':
            Proposal.objects.filter(briefing_id=pk).update(status=Proposal.SKIPPED)
            return '이번 주는 넘길게요'
        return ''

    # ---- 답장으로 고치기 ----
    def handle_reply(self, chat_id, reply_id, msg, text, actor):
        draft = self._draft_for_message(chat_id, reply_id)
        if draft is None:  # 카드·브리핑에 단 답장: 어느 글을 고칠지 모른다
            self.tg.send_message(chat_id, '고칠 점은 초안 메시지에 답장으로 적어 주세요.', reply_to=msg['message_id'])
            return
        if not text:
            return
        CopyNote.objects.create(draft=draft, text=text, by=actor[:100])
        self.tg.send_message(chat_id, '고치고 있어요. 2~3분쯤 걸려요.', reply_to=msg['message_id'])
        book = draft.proposal.book
        source = (book.description or book.short_description or '') if book else ''
        try:
            out = complete_json(self.llm, REWRITE_SYSTEM, build_rewrite_user(draft, text, source))
        except LLMError as e:
            self.host.notify_admin(f'⚠️ 마케팅 초안 고치기 실패: {type(e).__name__}: {e}')
            self.tg.send_message(chat_id, '지금은 고치지 못했어요. 잠시 뒤에 다시 적어 주세요.', reply_to=msg['message_id'])
            return
        new = Draft.objects.create(proposal=draft.proposal, channel=draft.channel,
                                   title=fix_title_marks(str(out.get('title') or '').strip()),
                                   body=fix_title_marks(str(out.get('body') or '').strip()) or draft.body,
                                   version=draft.version + 1, parent=draft)
        self._send_draft(new, chat_id, reply_to=msg['message_id'], note=str(out.get('note') or '').strip())

    # ---- 관리자 명령 ----
    def admin_command(self, chat_id, cmd, arg, now=None):
        now = now or timezone.now()
        handler = {'/mk': self._mk, '/brief': self._brief, '/kit': self._kit, '/hook': self._hook,
                   '/quiet': self._quiet, '/watch': self._watch}[cmd]
        self.tg.send_message(chat_id, handler(chat_id, (arg or '').strip(), now, kst_today(now)) or '완료')

    def _mk(self, chat_id, arg, now, today):
        if arg in MODES:
            WorkerState.put('marketing_mode', arg)
            return f'marketing_mode={arg}'
        b = Briefing.objects.filter(week_start=week_start(today)).first()
        pending = Proposal.objects.filter(kind=Proposal.KIT, sent_at__isnull=True, status=Proposal.PROPOSED).count()
        keys = ('marketing_last_sales_scan', 'marketing_last_news_scan', 'marketing_last_brief_week',
                'marketing_last_kit_check')
        week = '없음' if not b else ('보냄' if b.sent_at else f'미발송 {b.items.count()}건')
        return '\n'.join([f'mode={self.mode()}', *[f'{k}={WorkerState.get(k)}' for k in keys],
                          f'pending_kits={pending}', f'this_week_briefing={week}', USAGE])

    def _brief(self, chat_id, arg, now, today):
        b = Briefing.objects.filter(week_start=week_start(today)).first()
        if arg == 'send':
            review = self.host.review_chat_id()
            if not b or b.sent_at or not review:
                return '보낼 브리핑이 없어요 (/brief 로 먼저 만들기)'
            return '검수 방에 보냈어요' if self.send_briefing(b, now, chat=review) else '보내지 못했어요 (항목 없음 또는 조용한 시간)'
        if b and b.sent_at:
            return '이번 주 브리핑은 이미 보냈어요'
        b, dropped = briefing_mod.build_weekly(self.llm, today, now, self.blog_posts())
        note = f'\n버린 항목: {"; ".join(dropped)}' if dropped else ''
        if not self.send_briefing(b, now, chat=chat_id, record=False):
            return '이번 주는 제안할 항목이 없어요' + note
        return '미리보기예요. 검수 방에 보내려면 /brief send' + note

    def _kit(self, chat_id, arg, now, today):
        m = re.fullmatch(r'send\s+(\d+)', arg)
        if m:
            p = Proposal.objects.filter(pk=int(m.group(1)), kind=Proposal.KIT).select_related('book').first()
            review = self.host.review_chat_id()
            if not p or not review:
                return '그런 묶음이 없어요'
            if p.sent_at and p.chat_id == review:
                return '이미 검수 방에 보낸 묶음이에요'
            until = kit_mod.quiet_until(p.book, today)
            if until:
                return f'이 책은 {until}까지 홍보를 쉬는 중이라 보내지 않았어요'
            if in_quiet_hours(now):
                return '조용한 시간(21:00~08:00)이라 보내지 않았어요. 08:00 뒤에 다시 보내 주세요'
            sent_today = Proposal.objects.filter(kind=Proposal.KIT, chat_id=review,
                                                 sent_at__gte=self._day_start(now)).count()
            if sent_today >= KIT_DAILY_CAP:
                return f'오늘은 검수 방에 묶음 카드를 이미 {KIT_DAILY_CAP}장 보냈어요. 내일 다시 보내 주세요'
            self._mark_sent(p, review, self.send_kit(p, review), now)
            return '검수 방에 보냈어요'
        books = find_books(arg)
        if len(books) != 1:
            return _narrow(books)
        p = kit_mod.build_kit(books[0], self.llm, self.blog_posts(), today)
        p.status = Proposal.SHOWN  # 미리보기로 만든 묶음은 자동 발송하지 않는다
        p.save(update_fields=['status', 'updated_at'])
        self.send_kit(p, chat_id)
        until = kit_mod.quiet_until(books[0], today)
        return (f'미리보기예요 (묶음 {p.id}). 검수 방에 보내려면 /kit send {p.id}'
                + (f'\n(이 책은 {until}까지 홍보를 쉬는 중이에요)' if until else ''))

    def _hook(self, chat_id, arg, now, today):
        if arg in ('', 'list'):
            rows = [f'{on:%m-%d} {h.name}{" (추모)" if h.memorial else ""}: ' + ', '.join(b.title for b in h.books.all())
                    for h, on in upcoming(today, 60)]
            return '\n'.join(rows) or '앞으로 60일 안의 기념일이 없어요'
        m = re.fullmatch(r'(\d{1,2})-(\d{1,2})\s+([^|]+?)\s*(?:\|\s*(.+))?', arg)
        if not m:
            return '형식: /hook 10-11 커밍아웃의 날 | 커밍아웃 스토리, 웰컴 투 레인보우'
        month, day = int(m.group(1)), int(m.group(2))
        try:
            date(2028, month, day)  # 윤년 기준으로 날짜가 맞는지만 본다
        except ValueError:
            return '날짜가 이상해요'
        titles = [t.strip() for t in (m.group(4) or '').split(',') if t.strip()]
        hook, missing = add_hook(month, day, m.group(3).strip(), titles)
        return (f'추가했어요: {month}-{day} {hook.name} (책 {hook.books.count()}권)'
                + (f'\n찾지 못한 책: {", ".join(missing)}' if missing else ''))

    def _quiet(self, chat_id, arg, now, today):
        if arg in ('', 'list'):
            rows = [f'『{p.book.title}』 ~{p.quiet_until} {p.quiet_reason}'
                    for p in BookProfile.objects.filter(quiet_until__gte=today).select_related('book')]
            return '\n'.join(rows) or '보류 중인 책이 없어요'
        m = re.fullmatch(r'(.+?)\s+(\d{4}-\d{2}-\d{2})(?:\s+(.+))?', arg)
        if not m:
            return '형식: /quiet 성서, 퀴어 2026-11-30 이유'
        try:
            until = date.fromisoformat(m.group(2))
        except ValueError:
            return '날짜가 이상해요'
        books = find_books(m.group(1))
        if len(books) != 1:
            return _narrow(books)
        BookProfile.objects.update_or_create(book=books[0], defaults={'quiet_until': until,
                                                                      'quiet_reason': (m.group(3) or '')[:200]})
        return f'『{books[0].title}』 {until}까지 홍보 제안을 쉬어요'

    def _watch(self, chat_id, arg, now, today):
        if arg in ('', 'list'):
            rows = [f'{w.id}. {w.query}{"" if w.active else " (꺼짐)"}' for w in WatchQuery.objects.order_by('id')]
            return '\n'.join(rows) or '질의가 없어요'
        m = re.fullmatch(r'off\s+(\d+)', arg)
        if m:
            return '껐어요' if WatchQuery.objects.filter(pk=int(m.group(1))).update(active=False) else '그런 번호가 없어요'
        book = _book_for_query(arg)
        w, made = WatchQuery.objects.get_or_create(query=arg[:200], defaults={'book': book})
        fields = []
        if not w.active:
            w.active, fields = True, fields + ['active']
        if not made and w.book_id is None and book is not None:
            w.book, fields = book, fields + ['book']
        if fields:
            w.save(update_fields=[*fields, 'updated_at'])
        verb = '추가했어요' if made else '이미 있어요'
        if w.book_id:
            return f'{verb}: {w.query} → 『{w.book.title}』'
        return f'{verb}: {w.query} (연결된 책 없음 — 소식이 와도 브리핑 후보가 되지 않아요. 저자 이름이나 책 제목 그대로 적어 주세요)'
