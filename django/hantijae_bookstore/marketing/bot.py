"""검수 방·관리자 방에서의 마케팅 비서. intake.Bot이 명령·콜백·답장을 이 객체로 넘긴다(host = intake.Bot)."""
import io
import logging
import re
from datetime import date, datetime
from types import SimpleNamespace

from django.db.models import Q
from django.utils import timezone
from PIL import Image

from books.models import Book
from intake.llm import LLMError, complete_json
from intake.models import TelegramChat, WorkerState
from marketing import board
from marketing import briefing as briefing_mod
from marketing import kit as kit_mod
from marketing import grants, messages, midweek, moments, notion_sync, social
from marketing.hooks import add_hook, upcoming
from marketing.models import BookProfile, Briefing, CopyNote, Draft, DraftMessage, GrantCall, Proposal, WatchQuery
from marketing.prompts import REWRITE_SYSTEM, build_rewrite_user
from marketing.text import fix_title_marks, is_acknowledgement, title_key
from marketing.timeutil import KST, in_quiet_hours, kst_now, kst_today, week_start
from web.blog import fetch_rss, parse_rss

log = logging.getLogger('intake')
COMMANDS = ('/brief', '/kit', '/mk', '/hook', '/quiet', '/watch', '/moment', '/grant')
MODES = ('off', 'admin_only', 'live')
KIT_DAILY_CAP = 2
REMIND_AT = (9, 30)   # 지원사업 마감 이틀 전 알림을 보내기 시작하는 시각(KST)
KIT_SEND_MAX_FAILURES = 3  # 이 횟수에 닿으면 관리자에게 알리고 더는 자동으로 시도하지 않는다
BUILDING = '만들고 있어요. 몇 분 걸려요.'
USAGE = ('사용법: /mk off|admin_only|live · /mk social on|off · /brief [send] · /kit <제목 일부> · /kit send <번호> · '
         '/hook <MM-DD> <이름> | <책1>, <책2> · /hook list · /quiet <제목 일부> <YYYY-MM-DD> [이유] · /quiet list · '
         '/watch <이름> [+ 좁히기 조건] · /watch list · /watch off <번호> · /moment · /grant · /mk notion on|off')
MOMENT_USAGE = ('사용법: /moment off|admin_only|live · /moment midweek off|admin_only|live · /moment now (지금 한 번, 몇 분) · '
                '/moment list')


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
        return (any(model.objects.filter(chat_id=chat_id, message_id=message_id).exists()
                    for model in (DraftMessage, Draft, Proposal, Briefing, GrantCall))
                or GrantCall.objects.filter(chat_id=chat_id, reminder_message_id=message_id).exists())

    @staticmethod
    def blog_posts():
        """블로그 최근 글 50개. 못 읽으면 None(블로그 공백 판단을 건너뛰게)."""
        try:
            return parse_rss(fetch_rss(timeout=10), limit=50)
        except Exception:
            return None

    # ---- 노션 '홍보 비서 글 모음' ----
    def _notion(self):
        return notion_sync.client_for(self.host)

    def _is_room(self, chat):
        """검수 방으로 실제로 보내는가. 관리자 방 미리보기·admin_only에는 노션 페이지를 만들지 않는다(운영진 모두가 보는 곳)."""
        admin = self.host._chat(TelegramChat.ADMIN)
        return chat is not None and chat != admin and chat == self.host._chat(TelegramChat.REVIEWERS)

    def _notion_page(self, target, chat, now):
        """검수 방으로 보낼 때만 페이지를 만든다. 실패하면 ''(텔레그램은 버튼 없이 나가고 워커가 다시 시도)."""
        client = self._notion()
        if client is None or not self._is_room(chat):
            return ''
        try:
            return notion_sync.ensure_page(client, target, now)
        except Exception:
            log.warning('marketing notion page failed (%s)', target.name, exc_info=True)
            return ''

    # ---- 보내기 ----
    def send_kit(self, proposal, chat, now=None):
        now = now or timezone.now()
        drafts = board.kit_drafts(proposal)
        missing, blog = proposal.extra.get('missing_stores', []), proposal.extra.get('blog_exists', False)
        caption = messages.kit_caption(proposal.book, drafts, missing, blog)
        url = self._notion_page(notion_sync.kit_target(
            proposal, messages.kit_caption(proposal.book, drafts, missing, blog, guide=False), kst_today(now)), chat, now)
        states = {c: board.channel_state(proposal, c) for c in (Draft.BLOG, Draft.INSTAGRAM)}
        buttons = messages.kit_buttons(proposal, drafts, states, url or (proposal.notion or {}).get('url', ''))
        photo = cover_jpeg(proposal.book)
        sent = (self.tg.send_photo(chat, photo, caption, buttons=buttons) if photo
                else self.tg.send_message(chat, caption, buttons=buttons))
        return sent['message_id']

    def _mark_sent(self, proposal, chat, message_id, now):
        proposal.chat_id, proposal.message_id, proposal.sent_at, proposal.status = chat, message_id, now, Proposal.SHOWN
        fields = ['chat_id', 'message_id', 'sent_at', 'status', 'updated_at']
        if 'send_fail_day' in proposal.extra or 'send_fail_count' in proposal.extra:
            extra = dict(proposal.extra)
            extra.pop('send_fail_day', None)
            extra.pop('send_fail_count', None)
            proposal.extra = extra
            fields.append('extra')
        proposal.save(update_fields=fields)

    def _record_kit_send_failure(self, proposal, today_iso):
        count = proposal.extra.get('send_fail_count', 0) + 1
        proposal.extra = {**proposal.extra, 'send_fail_day': today_iso, 'send_fail_count': count}
        proposal.save(update_fields=['extra', 'updated_at'])
        if count == KIT_SEND_MAX_FAILURES:
            try:  # 이 알림 자체가 실패해도 원래 보내기 실패 예외는 그대로 올라가야 한다
                self.host.notify_admin(f'⚠️ 『{proposal.book.title}』 홍보 묶음 카드를 3번 보내지 못했어요. '
                                       f'확인한 뒤 /kit send {proposal.id} 로 보내 주세요')
            except Exception:
                log.exception('marketing kit %s 3rd-failure admin notice failed', proposal.id)

    @staticmethod
    def _day_start(now):
        return datetime.combine(kst_today(now), datetime.min.time(), tzinfo=KST)

    def send_pending_kits(self, now):
        chat = self.target_chat()
        if chat is None or in_quiet_hours(now):
            return 0
        today_iso = kst_today(now).isoformat()
        room = KIT_DAILY_CAP - Proposal.objects.filter(kind=Proposal.KIT, sent_at__gte=self._day_start(now)).count()
        candidates = (Proposal.objects.filter(kind=Proposal.KIT, sent_at__isnull=True, status=Proposal.PROPOSED)
                      .exclude(book__marketing__quiet_until__gte=kst_today(now))  # 쉬는 책은 쉬는 날이 지나면 보낸다
                      .select_related('book').order_by('id'))
        ready = [p for p in candidates if p.extra.get('send_fail_day') != today_iso
                and p.extra.get('send_fail_count', 0) < KIT_SEND_MAX_FAILURES]
        pending = ready[:max(room, 0)]
        n, first_exc = 0, None
        for p in pending:
            try:
                self._mark_sent(p, chat, self.send_kit(p, chat, now), now)
            except Exception as e:  # 카드 하나가 실패해도 나머지는 보낸다. 실패는 기록해 두고 다음 바퀴로 넘긴다
                log.exception('marketing kit %s send failed', p.id)
                self._record_kit_send_failure(p, today_iso)
                first_exc = first_exc or e
                continue
            n += 1
        if first_exc is not None:  # _guard('kit_send')가 하루 한 번 관리자에게 알리게 한다
            raise first_exc
        return n

    def send_briefing(self, briefing, now, chat=None, record=True):
        chat = chat or self.target_chat()
        already = briefing.sent_at and briefing.chat_id == chat  # 관리자 방에만 나간 것은 검수 방으로 또 보낼 수 있다
        if chat is None or (record and (already or in_quiet_hours(now))):
            return False
        items = list(briefing.items.order_by('rank'))
        today = kst_today(now)
        quiet_books = set(BookProfile.objects.filter(quiet_until__gte=today, book_id__in=[i.book_id for i in items if i.book_id])
                          .values_list('book_id', flat=True))

        def is_quiet(i):
            return bool(i.book_id and i.book_id in quiet_books)
        shown = [i for i in items if not is_quiet(i)]  # 보류 중인 책 항목은 상태와 무관하게 메시지에서 뺀다
        if not shown:  # 전부 보류 중이거나 애초에 항목이 없으면 지금의 '항목 없음' 경로와 같다
            return False
        # 이미 ACTED로 확정된 항목은 메시지에서는 빠지지만(위) 상태는 그대로 둔다(운영진 결정 보존)
        to_skip = [i for i in items if is_quiet(i) and i.status != Proposal.ACTED]
        grant_lines = self._grant_briefing_lines(today)
        states = [board.item_state(p) for p in shown]  # 관리자 방 사본에서 이미 누른 결정도 버튼에 보인다
        url = (briefing.notion or {}).get('url', '')
        if record:  # 상황판·노션이 같은 항목을 그리게, 보낼 항목 순서를 먼저 적는다
            briefing.shown = [i.id for i in shown]
            briefing.save(update_fields=['shown'])
            url = self._notion_page(notion_sync.brief_target(
                briefing, messages.briefing_text(briefing.week_start, shown, briefing.measure, grants=grant_lines,
                                                 guide=False)), chat, now) or url
        sent = self.tg.send_message(chat, messages.briefing_text(briefing.week_start, shown, briefing.measure,
                                                                 grants=grant_lines),
                                    buttons=messages.briefing_buttons(briefing, shown, states, url))
        if record:
            briefing.chat_id, briefing.message_id, briefing.sent_at, briefing.mode = chat, sent['message_id'], now, self.mode()
            briefing.save(update_fields=['chat_id', 'message_id', 'sent_at', 'mode'])
            if to_skip:  # 보내기 전에 미리 SKIPPED로 적어 두면 보내기가 실패했을 때도 그대로 남는다 — 보낸 뒤에만 적는다
                Proposal.objects.filter(pk__in=[i.id for i in to_skip]).update(status=Proposal.SKIPPED)
            # 운영진이 이미 관리자 방 사본에서 누른 ACTED/SKIPPED 결정은 검수 방으로 넘길 때도 덮지 않는다
            Proposal.objects.filter(briefing=briefing, status__in=(Proposal.PROPOSED, Proposal.SHOWN)).update(status=Proposal.SHOWN)
            Proposal.objects.filter(briefing=briefing).update(chat_id=chat)
        return True

    # ---- 지원사업 공고 ----
    @staticmethod
    def _grant_briefing_lines(today):
        """월요 브리핑에 붙일 열린 공고 줄. 꺼져 있으면 없고, 실패해도 브리핑은 나가게 비운다."""
        if grants.mode() == 'off':
            return []
        try:
            return messages.grant_briefing_lines(grants.open_calls(today))
        except Exception:
            log.warning('grant briefing lines failed', exc_info=True)
            return []

    def grant_target(self):
        """(받는 곳, 검수 방인가). grant_mode live이고 마케팅도 live면 검수 방, off면 없음, 그 밖에는 관리자 1:1 미리보기."""
        gm = grants.mode()
        if gm == 'off':
            return None, False
        if gm == 'live' and self.mode() == 'live':
            return self.host.review_chat_id(), True
        return self.host._chat(TelegramChat.ADMIN), False

    def send_grants(self, now):
        """매 바퀴. 알릴 공고(검수 방은 하루 한 메시지·최대 3건) + 신청하기로 한 공고의 마감 이틀 전 알림(09:30 뒤).
        보낸 메시지 수를 돌려준다."""
        chat, room = self.grant_target()
        if chat is None or in_quiet_hours(now):
            return 0
        today, sent = kst_today(now), 0
        calls = grants.to_send(today)
        if not room:
            fresh = [c for c in calls if c.preview_at is None][:grants.PER_MESSAGE]
            if fresh:
                self.tg.send_message(chat, messages.grant_preview_text(fresh))
                GrantCall.objects.filter(pk__in=[c.pk for c in fresh]).update(preview_at=now)
                sent += 1
            return sent
        if calls and not GrantCall.objects.filter(chat_id=chat, sent_at__gte=self._day_start(now)).exists():
            calls = calls[:grants.PER_MESSAGE]
            msg = self.tg.send_message(chat, messages.grant_card_text(calls), buttons=messages.grant_buttons(calls))
            GrantCall.objects.filter(pk__in=[c.pk for c in calls]).update(
                state=GrantCall.ANNOUNCED, chat_id=chat, message_id=msg['message_id'], sent_at=now)
            sent += 1
        local = kst_now(now)
        if (local.hour, local.minute) >= REMIND_AT:
            for call in grants.due_reminders(today):
                msg = self.tg.send_message(call.chat_id, messages.grant_reminder_text(call), reply_to=call.message_id)
                GrantCall.objects.filter(pk=call.pk).update(reminded_at=now, reminder_message_id=msg['message_id'])
                sent += 1
        return sent

    def send_midweek(self, now):
        """오늘 만든 주중 제안을 한 메시지로. 보낼 게 없거나 받는 곳이 없거나 조용한 시간이면 False."""
        chat = midweek.target(self.host, self.mode())
        if chat is None or in_quiet_hours(now):
            return False
        items = list(Proposal.objects.filter(kind=Proposal.NOW, sent_at__isnull=True, created_at__gte=self._day_start(now))
                     .order_by('rank', 'id'))
        if midweek.to_room(self.mode()) and WorkerState.get('moment_mode', 'off') != 'live':
            # 만든 뒤 모드가 바뀐 경우: 계기 항목은 계기 잡기가 live일 때만 검수 방에 간다(남은 것은 다음 날 풀림)
            items = [p for p in items if not p.candidate_key.startswith('moment:')]
        if not items:
            return False
        url = self._notion_page(notion_sync.now_target(items, messages.midweek_text(items, guide=False), kst_today(now)),
                                chat, now)
        sent = self.tg.send_message(chat, messages.midweek_text(items),
                                    buttons=messages.midweek_buttons(items, [board.item_state(p) for p in items], url))
        Proposal.objects.filter(pk__in=[p.id for p in items]).update(chat_id=chat, message_id=sent['message_id'],
                                                                     sent_at=now, status=Proposal.SHOWN)
        self._midweek_week_notice(now)
        return True

    def _midweek_week_notice(self, now):
        wk = week_start(kst_today(now))
        start = datetime.combine(wk, datetime.min.time(), tzinfo=KST)
        sent = Proposal.objects.filter(kind=Proposal.NOW, sent_at__gte=start).values('message_id').distinct().count()
        if sent >= 2 and WorkerState.get('moment_week_notice') != wk.isoformat():
            WorkerState.put('moment_week_notice', wk.isoformat())
            self.host.notify_admin('ℹ️ 이번 주 주중 제안이 두 번째예요. 너무 잦으면 /moment midweek 로 조정하세요')

    def _send_draft(self, draft, chat_id, reply_to=None, quote=None):
        places = messages.places_text(draft)
        if places:  # 편지: 보낼 곳을 먼저 짧게(올릴 글이 아니라 본문에서 뺐다). 여기에 단 답장도 편지 고치기로 간다
            sent = self.tg.send_message(chat_id, places, reply_to=reply_to, quote=quote)
            DraftMessage.objects.create(draft=draft, chat_id=chat_id, message_id=sent['message_id'])
        sent = self.tg.send_message(chat_id, messages.draft_text(draft), reply_to=reply_to, quote=quote,
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

    def _current(self, proposal, channel):
        """(보낼·기록할·고칠 최신 판, 알림). 노션이 켜져 있으면 📝 상자를 읽어 고친 글을 새 판으로 받는다."""
        return notion_sync.current(self._notion(), proposal, channel, host=self.host, now=timezone.now())

    def _after_status(self, proposal):
        """버튼을 누른 뒤 허브 버튼(진행 상황판)을 다시 그린다. 실패해도 버튼 처리는 끝난 것으로 둔다."""
        try:
            board.refresh(self.tg, board.hub_of(Proposal.objects.select_related('briefing').get(pk=proposal.pk)))
        except Exception:
            log.warning('marketing hub refresh failed for proposal %s', proposal.pk, exc_info=True)
        client = self._notion()
        if client is not None:
            try:  # 노션 쪽 진행 표시도 같이 고친다(실패해도 텔레그램은 이미 끝났다)
                notion_sync.refresh(client, notion_sync.target_of(
                    Proposal.objects.select_related('briefing').get(pk=proposal.pk)))
            except Exception:
                log.warning('marketing notion refresh failed for proposal %s', proposal.pk, exc_info=True)

    # ---- 버튼 ----
    def handle_callback(self, data, chat_id, cq, actor):
        action, pk = messages.parse_cb(data)
        here_msg = cq['message']
        here = here_msg['message_id']
        hub_text = here_msg.get('text') or here_msg.get('caption') or ''
        if action == 'v':
            d = Draft.objects.filter(pk=pk).select_related('proposal').first()
            if not d:
                return ''
            cur, note = self._current(d.proposal, d.channel)
            self._send_draft(cur, chat_id, reply_to=here, quote=messages.kit_line(hub_text, d.channel))
            return messages.sent_toast(None, cur, note)
        if action == 'b':
            p = Proposal.objects.filter(pk=pk).first()
            newest = self._newest(pk) if p else None
            if not newest:
                return ''
            cur, note = self._current(p, newest.channel)
            line = messages.item_line(hub_text, p.headline)
            self._send_draft(cur, chat_id, reply_to=here, quote=line)
            return messages.sent_toast(messages.line_number(line), cur, note)
        if action == 'm':
            p = Proposal.objects.filter(pk=pk).first()
            if not p:
                return ''
            if p.caution:
                self.tg.send_message(chat_id, '조심할 점\n\n' + p.caution, reply_to=here)
            notes = []
            for d in p.drafts.filter(channel__in=(Draft.LINKS, Draft.SHORT, Draft.LETTER), parent__isnull=True).order_by('id'):
                cur, note = self._current(p, d.channel)
                notes.append(note)
                self._send_draft(cur, chat_id, reply_to=here, quote=messages.kit_line(hub_text, d.channel))
            return '나머지 글을 보냈어요' + (' · 노션에서 고친 글이 있어요' if 'notion' in notes else '')
        if action == 'p':
            d = Draft.objects.filter(pk=pk).select_related('proposal').first()
            if not d:
                return ''
            cur, _ = self._current(d.proposal, d.channel)  # 올린 글 = 그 순간의 최신 판(노션 포함, 2026-09-30 사용자)
            Draft.objects.filter(pk=cur.pk).update(status=Draft.POSTED, posted_at=timezone.now(), posted_by=actor[:100])
            Proposal.objects.filter(pk=d.proposal_id).update(status=Proposal.ACTED)
            self._after_status(d.proposal)
            return messages.POSTED_TOAST
        if action == 'e':
            return '이 초안에 답장으로 고칠 점을 적어 주세요'
        if action == 'l':
            d = Draft.objects.filter(pk=pk).select_related('proposal').first()
            if not d:
                return ''
            # 누른 판만이 아니라 그 글의 아직 안 올린 판 모두(상황판 이름이 판마다 흔들리지 않게)
            Draft.objects.filter(proposal_id=d.proposal_id, channel=d.channel, status=Draft.DRAFT).update(status=Draft.SKIPPED)
            self._after_status(d.proposal)
            return '알겠어요'
        if action == 'sk':
            p = Proposal.objects.filter(pk=pk, kind=Proposal.KIT).first()
            if p:
                Proposal.objects.filter(pk=pk).exclude(status=Proposal.ACTED).update(status=Proposal.SKIPPED)
                self._after_status(p)
            return '이번엔 넘길게요'
        if action == 'sn':
            ps = Proposal.objects.filter(kind=Proposal.NOW, chat_id=chat_id, message_id=here)
            first = ps.order_by('rank', 'id').first()
            ps.exclude(status=Proposal.ACTED).update(status=Proposal.SKIPPED)  # 이미 올린 항목은 그대로
            if first:
                self._after_status(first)
            return '이번엔 넘길게요'
        if action == 'sw':
            items = Proposal.objects.filter(briefing_id=pk)
            first = items.order_by('rank', 'id').first()
            items.exclude(status=Proposal.ACTED).update(status=Proposal.SKIPPED)  # 이미 올린 항목은 그대로
            if first:
                self._after_status(first)
            return '이번 주는 넘길게요'
        if action in ('ga', 'gp'):
            call, answer = grants.decide(pk, action == 'ga', actor, timezone.now())
            if call and call.message_id:
                calls = grants.card_calls(call.chat_id, call.message_id)
                self.tg.edit_text(call.chat_id, call.message_id, messages.grant_card_text(calls),
                                  buttons=messages.grant_buttons(calls))
            return answer
        return ''

    # ---- 답장으로 고치기 ----
    def handle_reply(self, chat_id, reply_id, msg, text, actor):
        call = GrantCall.objects.filter(Q(message_id=reply_id) | Q(reminder_message_id=reply_id), chat_id=chat_id).first()
        if call is not None:  # 지원사업 카드·마감 알림에 단 답장: 관리자에게 전하고 짧게만 답한다
            if text and not is_acknowledgement(text):
                self.host.notify_admin(f'📝 지원사업 카드 답장 — {call.title}\n{actor}: {text}')
                self.tg.send_message(chat_id, '메모 남겼어요.', reply_to=msg['message_id'])
            return
        draft = self._draft_for_message(chat_id, reply_id)
        if draft is None:  # 카드·브리핑에 단 답장: 어느 글을 고칠지 모른다
            if not (text and is_acknowledgement(text)):  # 인사 답장이면 안내도 안 보낸다 — 운영진끼리 맞장구에 끼어들지 않는다
                self.tg.send_message(chat_id, '고칠 점은 초안 메시지에 답장으로 적어 주세요.', reply_to=msg['message_id'])
            return
        if not text or is_acknowledgement(text):  # 고맙다·좋다는 답뿐이면 고치지 않는다
            return
        base, _ = self._current(draft.proposal, draft.channel)  # 옛 사본에 답장해도 최신 판(노션 포함)을 고친다
        CopyNote.objects.create(draft=base, text=text, by=actor[:100])
        working = self.tg.send_message(chat_id, messages.WORKING, reply_to=msg['message_id'])
        book = base.proposal.book
        source = (book.description or book.short_description or '') if book else ''
        try:
            out = complete_json(self.llm, REWRITE_SYSTEM, build_rewrite_user(base, text, source))
        except LLMError as e:
            self.host.notify_admin(f'⚠️ 마케팅 초안 고치기 실패: {type(e).__name__}: {e}')
            self.tg.edit_text(chat_id, working['message_id'], messages.REWRITE_FAILED)
            return
        new = Draft.objects.create(proposal=base.proposal, channel=base.channel,
                                   title=fix_title_marks(str(out.get('title') or '').strip())[:300],
                                   body=fix_title_marks(str(out.get('body') or '').strip()) or base.body,
                                   version=base.version + 1, parent=base, origin=Draft.REWRITE, extra=base.extra)
        # '고치고 있어요'를 '고쳤어요: …'로 고쳐 써 방에 메시지가 하나만 늘게 하고, 새 글은 본문만
        self.tg.edit_text(chat_id, working['message_id'], messages.rewrite_done(str(out.get('note') or '').strip()))
        self._send_draft(new, chat_id, reply_to=msg['message_id'])
        client = self._notion()
        if client is not None:
            try:
                notion_sync.append_version(client, new, text)
            except Exception:  # 다음에 이 글을 읽을 때 다시 덧붙인다(notion_sync.current)
                log.warning('marketing notion append failed for draft %s', new.pk, exc_info=True)
        self._after_status(new.proposal)  # [다음에] 했던 글이 다시 열리면 버튼 이름도 돌아온다

    # ---- 관리자 명령 ----
    def admin_command(self, chat_id, cmd, arg, now=None):
        now = now or timezone.now()
        handler = {'/mk': self._mk, '/brief': self._brief, '/kit': self._kit, '/hook': self._hook,
                   '/quiet': self._quiet, '/watch': self._watch, '/moment': self._moment,
                   '/grant': self._grant}[cmd]
        self.tg.send_message(chat_id, handler(chat_id, (arg or '').strip(), now, kst_today(now)) or '완료')

    def _mk(self, chat_id, arg, now, today):
        if arg.split()[:1] == ['notion']:
            return notion_sync.switch(arg[len('notion'):].strip())
        if arg.split()[:1] == ['social']:
            return social.switch(arg[len('social'):].strip(), now)
        if arg in MODES:
            WorkerState.put('marketing_mode', arg)
            return f'marketing_mode={arg}'
        b = Briefing.objects.filter(week_start=week_start(today)).first()
        pending = Proposal.objects.filter(kind=Proposal.KIT, sent_at__isnull=True, status=Proposal.PROPOSED).count()
        keys = ('marketing_last_sales_scan', 'marketing_last_news_scan', 'marketing_last_brief_week',
                'marketing_last_kit_check')
        week = '없음' if not b else ('보냄' if b.sent_at else f'미발송 {b.items.count()}건')
        return '\n'.join([f'mode={self.mode()}', *[f'{k}={WorkerState.get(k)}' for k in keys],
                          f'pending_kits={pending}', f'this_week_briefing={week}', notion_sync.status_line(), *social.status_lines(now), USAGE])

    def _moment(self, chat_id, arg, now, today):
        parts = arg.split()
        if len(parts) == 2 and parts[0] == 'midweek' and parts[1] in MODES:
            WorkerState.put('midweek_mode', parts[1])
            return f'midweek_mode={parts[1]}'
        if arg in MODES:
            WorkerState.put('moment_mode', arg)
            return f'moment_mode={arg}'
        if arg == 'now':
            self.tg.send_message(chat_id, BUILDING)
            deps = SimpleNamespace(tg=self.tg, llm=self.llm, notion=getattr(self.host, 'notion', None))
            report = moments.daily(deps, now)
            return moments.digest(report, now) or '새로 찾은 계기가 없어요'
        if arg == 'list':
            opens = moments.open_moments(today, now)[:15]
            return '\n'.join(moments.open_line(s) for s in opens) or '열린 계기가 없어요'
        return moments.status_text(today, now) + '\n' + MOMENT_USAGE

    def _grant(self, chat_id, arg, now, today):
        if arg in grants.MODES:
            WorkerState.put('grant_mode', arg)
            return f'grant_mode={arg}'
        if arg == 'now':
            self.tg.send_message(chat_id, BUILDING)
            report = grants.scan(self.llm, today)
            WorkerState.put('grant_last_scan', today.isoformat())
            sent = self.send_grants(now)
            return '\n'.join(x for x in (f'새 글 {report.new}건', grants.digest(report), f'보낸 메시지 {sent}개') if x)
        return grants.status_text(today) + '\n' + grants.USAGE

    def _brief(self, chat_id, arg, now, today):
        b = Briefing.objects.filter(week_start=week_start(today)).first()
        review = self.host.review_chat_id()
        in_review = bool(b and b.sent_at and b.chat_id == review)
        if arg == 'send':  # admin_only 에서 관리자 방에만 나간 브리핑도 검수 방으로 보낸다
            if not b or not review:
                return '보낼 브리핑이 없어요 (/brief 로 먼저 만들기)'
            if in_review:
                return '이미 검수 방에 보낸 브리핑이에요'
            return '검수 방에 보냈어요' if self.send_briefing(b, now, chat=review) else '보내지 못했어요 (항목 없음 또는 조용한 시간)'
        if in_review:
            return '이번 주 브리핑은 이미 보냈어요'
        self.tg.send_message(chat_id, BUILDING)
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
            self._mark_sent(p, review, self.send_kit(p, review, now), now)
            return '검수 방에 보냈어요'
        books = find_books(arg)
        if len(books) != 1:
            return _narrow(books)
        self.tg.send_message(chat_id, BUILDING)
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
        note = self._quiet_briefing_note(books[0], today) if until >= today else ''  # 과거 날짜는 보류를 끝내는 쪽이라 뺄 게 없다
        return f'『{books[0].title}』 {until}까지 홍보 제안을 쉬어요' + note

    def _quiet_briefing_note(self, book, today):
        """이번 주 브리핑이 아직 검수 방으로 나가지 않았고 이 책 항목이 들어 있으면 한 줄 덧붙인다(B에서 보낼 때 뺀다)."""
        b = Briefing.objects.filter(week_start=week_start(today)).first()
        if not b:
            return ''
        in_review = bool(b.sent_at and b.chat_id == self.host.review_chat_id())
        if in_review or not Proposal.objects.filter(briefing=b, book=book).exists():
            return ''
        return '\n이번 주 브리핑에서 이 책 항목은 빼고 보낼게요'

    @staticmethod
    def _watch_label(w):
        return w.query + (f' + {w.narrow}' if w.narrow else '')

    def _watch(self, chat_id, arg, now, today):
        if arg in ('', 'list'):
            rows = [f'{w.id}. {self._watch_label(w)}{"" if w.active else " (꺼짐)"}' for w in WatchQuery.objects.order_by('id')]
            return '\n'.join(rows) or '질의가 없어요'
        m = re.fullmatch(r'off\s+(\d+)', arg)
        if m:
            return '껐어요' if WatchQuery.objects.filter(pk=int(m.group(1))).update(active=False) else '그런 번호가 없어요'
        narrow = None
        m = re.fullmatch(r'(.+?)\s*\+\s*(.*)', arg)  # '이름 + 조건': 동명이인 거르기. 빈 조건이면 이름만으로 찾기
        if m:
            arg, narrow = m.group(1).strip(), m.group(2).strip()[:300]
        book = _book_for_query(arg)
        w, made = WatchQuery.objects.get_or_create(query=arg[:200], defaults={'book': book})
        fields = []
        if not w.active:
            w.active, fields = True, fields + ['active']
        if not made and w.book_id is None and book is not None:
            w.book, fields = book, fields + ['book']
        if narrow is not None:  # 직접 정한 조건은 자동 좁히기가 덮지 않는다(narrowed_at)
            w.narrow, w.narrowed_at, fields = narrow, now, fields + ['narrow', 'narrowed_at']
        if fields:
            w.save(update_fields=[*fields, 'updated_at'])
        verb = '추가했어요' if made else ('고쳤어요' if narrow is not None else '이미 있어요')
        if w.book_id:
            return f'{verb}: {self._watch_label(w)} → 『{w.book.title}』'
        return (f'{verb}: {self._watch_label(w)} (연결된 책 없음 — 소식이 와도 브리핑 후보가 되지 않아요. '
                '저자 이름이나 책 제목 그대로 적어 주세요)')
