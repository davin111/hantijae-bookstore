"""한티재 게시물 광고의 성과(Meta 광고 계정, 읽기 전용). 스펙 .claude/docs/specs/2026-10-03-ads-collector-design.md(로컬).
대표님 개인 광고 계정이라 한티재 페이지·인스타 게시물 광고만 저장한다. 다른 광고는 광고 번호·게시물 번호만 읽어 거르고,
이름·지표 칸은 요청하지 않으며 어디에도 남기지 않는다. 광고 토큰은 60일 사용자 토큰(scripts/meta_ads_token.py로 갱신)."""
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Optional

import requests
from django.conf import settings
from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone

from intake.models import TelegramChat, WorkerState
from marketing import ad_books, bnk_sales, meta
from marketing.messages import h
from marketing.models import Ad, AdDay
from marketing.social_parse import parse_time
from marketing.timeutil import kst_now

log = logging.getLogger('intake')
KEYS = ('META_ADS_TOKEN', 'META_AD_ACCOUNT_ID', 'META_APP_SECRET', 'META_PAGE_TOKEN', 'META_PAGE_ID', 'META_IG_USER_ID')
WINDOW_DAYS = 28        # 매일 이만큼을 다시 읽어 덮어쓴다(Meta가 최근 숫자를 고친다)
IDS_PER_CALL = 50
NOT_OURS_CODES = {10, 100, 200}   # 페이지 토큰으로 남의 인스타 글을 물으면 오는 코드(사전 확인 c)
UNKNOWN = 'unknown'
CREATIVE = 'creative{effective_object_story_id,effective_instagram_media_id}'
DAY_FIELDS = 'ad_id,spend,impressions,clicks,inline_link_clicks,actions'
TOTAL_FIELDS = 'spend,impressions,reach,clicks,inline_link_clicks,actions'
REACTION, ENGAGEMENT = 'post_reaction', 'post_engagement'


def config():
    cfg = getattr(settings, 'MARKETING', {})
    return cfg if all(cfg.get(k) for k in KEYS) else None


def configured():
    return config() is not None


def expires_on():
    """광고 토큰이 끝나는 날(토큰·데이터 접근 가운데 이른 날, 갱신 스크립트가 적는다). 없거나 틀리면 None."""
    value = getattr(settings, 'MARKETING', {}).get('META_ADS_EXPIRES') or ''
    try:
        return date.fromisoformat(value)
    except ValueError:
        if value:
            log.warning('META_ADS_EXPIRES is not YYYY-MM-DD: %s', value)
        return None


@dataclass
class Report:
    found: int = 0     # 기간에 노출이 있었던 광고(번호만)
    ours: int = 0      # 그 가운데 한티재 광고
    new: int = 0       # 새로 저장한 한티재 광고
    days: int = 0      # 덮어쓴 일별 줄
    unknown: int = 0   # 인스타 주인을 확인하지 못해 내일 다시 볼 광고
    unlisted: int = 0  # 광고 계정 목록에 없고(보관·삭제된 광고) 따로 읽어도 못 읽은 광고
    linked: int = 0    # 책·책 제목을 새로 정한 광고(ad_books.relink)


def _int(value):
    try:
        return round(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _action(row, kind):
    return sum(_int(a.get('value')) for a in row.get('actions') or [] if a.get('action_type') == kind)


def _metrics(row):
    return {'spend': _int(row.get('spend')), 'impressions': _int(row.get('impressions')),
            'clicks': _int(row.get('clicks')), 'link_clicks': _int(row.get('inline_link_clicks')),
            'reactions': _action(row, REACTION), 'engagement': _action(row, ENGAGEMENT)}


def _span(today, full):
    if full:
        return {'date_preset': 'maximum'}   # Meta 보관 기간(약 37개월) 전체
    since = today - timedelta(days=WINDOW_DAYS - 1)
    return {'time_range': json.dumps({'since': since.isoformat(), 'until': today.isoformat()})}


def _ads(get, path, params, cfg):
    return meta._call(get, path, params, cfg, token=cfg['META_ADS_TOKEN'])


def _which(creative, cfg, get):
    """(채널, 게시물 번호, 인스타 글 번호). 한티재 광고가 아니면 None, 인스타 주인을 확인하지 못했으면 UNKNOWN.
    페이지 토큰이 인스타 권한을 잃으면(10·200) 인스타 광고도 '아님'이 되지만 저장하지 않았으니 권한이 돌아오면 다시 잡힌다."""
    story = creative.get('effective_object_story_id') or ''
    media = creative.get('effective_instagram_media_id') or ''
    if story.startswith(f"{cfg['META_PAGE_ID']}_"):
        return Ad.FACEBOOK, story, media
    if not media:
        return None
    try:
        owner = (meta._call(get, media, {'fields': 'owner'}, cfg).get('owner') or {}).get('id')   # 페이지 토큰
    except meta.MetaError as e:
        if e.code in NOT_OURS_CODES:
            return None
        log.warning('ads instagram owner: %s', e)
        return UNKNOWN
    return (Ad.INSTAGRAM, media, media) if str(owner) == str(cfg['META_IG_USER_ID']) else None


def _post_info(channel, post_id, media, cfg, get):
    """(글 전체, 주소, 올린 시각) — 페이지 토큰으로. 페북 글을 못 읽으면 인스타 글로.
    모두 못 읽었는데 다시 해 볼 만한 실패(토큰·한도·일시 오류)가 있으면 None(내일 다시), 글이 없거나 못 읽는 글뿐이면 빈 값."""
    asks = [(post_id, 'message,permalink_url,created_time', 'message', 'permalink_url', 'created_time')] \
        if channel == Ad.FACEBOOK else []
    if media:
        asks.append((media, 'caption,permalink,timestamp', 'caption', 'permalink', 'timestamp'))
    retry = False
    for node, fields, text_key, url_key, time_key in asks:
        try:
            d = meta._call(get, node, {'fields': fields}, cfg)
        except meta.MetaError as e:
            log.warning('ads post info: %s', e)
            retry = retry or e.code not in NOT_OURS_CODES
            continue
        return ' '.join((d.get(text_key) or '').split()), d.get(url_key) or '', parse_time(d.get(time_key))
    return None if retry else ('', '', None)


def _new_ads(get, cfg, ids, report):
    """DB에 없는 광고 번호 가운데 한티재 광고만 저장한다. 나머지는 버린다."""
    ids = sorted(ids)
    for i in range(0, len(ids), IDS_PER_CALL):
        chunk = ids[i:i + IDS_PER_CALL]
        # ?ids= 묶음 읽기는 광고 토큰으로 HTTP 500(code 100)이 난다(사전 확인 10-03) → 광고 계정에서 번호로 거른다
        flt = json.dumps([{'field': 'id', 'operator': 'IN', 'value': chunk}])
        rows = meta.pages(get, f"{cfg['META_AD_ACCOUNT_ID']}/ads",
                          {'fields': 'id,' + CREATIVE, 'filtering': flt, 'limit': IDS_PER_CALL}, cfg,
                          token=cfg['META_ADS_TOKEN'])
        got = {str(r.get('id')): r for r in rows}
        for ad_id in chunk:
            row = got.get(ad_id)
            if row is None:   # 목록은 보관·삭제된 광고를 빼기도 한다 → 그 광고 하나만 따로 읽는다(글 번호 칸만)
                try:
                    row = _ads(get, ad_id, {'fields': CREATIVE}, cfg)
                except meta.MetaError as e:
                    if e.code in meta.TOKEN_CODES:   # 토큰 문제만 멈춘다 — 10·200은 이 광고 하나만의 문제
                        raise
                    report.unlisted += 1
                    log.warning('ads creative: %s', e)
                    continue
            which = _which(row.get('creative') or {}, cfg, get)
            if which == UNKNOWN:
                report.unknown += 1
                continue
            if which is None:
                continue
            channel, post_id, media = which
            info = _post_info(channel, post_id, media, cfg, get)
            if info is None:   # 글을 못 읽었다 — 저장하지 않고 내일 다시 본다(글·책을 영영 잃지 않게)
                report.unknown += 1
                continue
            text, url, at = info
            book, title = ad_books.match((post_id, media), text)   # 책 찾기는 자르기 전 원문으로
            Ad.objects.create(ad_id=ad_id, channel=channel, post_id=post_id, ig_media_id=media, post_url=url,
                              post_text=text[:200], posted_at=at, book=book, book_title=title)
            report.new += 1


def _date(value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _save_days(get, cfg, span, ours, report, full):
    """한티재 광고 번호로만 일별 값을 읽어 덮어쓴다. 전체 기간은 광고마다 그 광고 자체에서 읽는다
    (계정 쪽 filtering은 보관·삭제된 광고를 빼 버린다)."""
    for ad_id in sorted(ours) if full else [None]:
        if full:
            rows = meta.pages(get, f'{ad_id}/insights', {'time_increment': 1, 'date_preset': 'maximum',
                                                         'fields': DAY_FIELDS, 'limit': 500}, cfg,
                              token=cfg['META_ADS_TOKEN'])
        else:
            flt = json.dumps([{'field': 'ad.id', 'operator': 'IN', 'value': sorted(ours)}])
            rows = meta.pages(get, f"{cfg['META_AD_ACCOUNT_ID']}/insights",
                              {'level': 'ad', 'time_increment': 1, 'fields': DAY_FIELDS, 'filtering': flt,
                               'limit': 500, **span}, cfg, token=cfg['META_ADS_TOKEN'])
        for r in rows:
            ad, day = ours.get(str(r.get('ad_id'))), _date(r.get('date_start'))
            if ad is None or day is None:   # 걸러 달라고 한 번호 밖의 행은 버린다
                continue
            AdDay.objects.update_or_create(ad=ad, day=day, defaults=_metrics(r))
            report.days += 1


def _refresh(get, cfg, ad):
    """전체 기간 합계(도달 포함)와 처음·끝 지출일. 합계 읽기가 실패하면 전날 값을 둔다(권한 오류는 올린다)."""
    try:
        rows = _ads(get, f'{ad.ad_id}/insights', {'date_preset': 'maximum', 'fields': TOTAL_FIELDS}, cfg).get('data')
    except meta.MetaAuthError:
        raise
    except meta.MetaError as e:
        log.warning('ads totals: %s', e)
        rows = None
    if rows is not None:
        row = rows[0] if rows else {}
        for key, value in {**_metrics(row), 'reach': _int(row.get('reach'))}.items():
            setattr(ad, key, value)
        ad.totals_at = timezone.now()
    span = AdDay.objects.filter(ad=ad, spend__gt=0).aggregate(first=Min('day'), last=Max('day'))
    ad.first_day, ad.last_day = span['first'], span['last']
    # 몇 분 전에 읽은 행이라 card·book은 건드리지 않는다(그사이 보냄·책 수정이 되돌아가지 않게)
    fields = ['first_day', 'last_day', 'updated_at']
    if rows is not None:
        fields += [*_metrics({}), 'reach', 'totals_at']
    ad.save(update_fields=fields)


def collect(today, full=False, get=requests.get):
    """기간(최근 28일, full이면 전체)에 노출이 있었던 광고 가운데 한티재 광고의 일별·전체 값을 저장한다."""
    cfg, report = config(), Report()
    if not cfg:
        return report
    span = _span(today, full)
    rows = meta.pages(get, f"{cfg['META_AD_ACCOUNT_ID']}/insights",
                      {'level': 'ad', 'fields': 'ad_id', 'limit': 500, **span}, cfg, token=cfg['META_ADS_TOKEN'])
    ids = {str(r['ad_id']) for r in rows if r.get('ad_id')}
    report.found = len(ids)
    known = set(Ad.objects.filter(ad_id__in=ids).values_list('ad_id', flat=True))
    _new_ads(get, cfg, ids - known, report)
    ours = {a.ad_id: a for a in Ad.objects.filter(ad_id__in=ids)}
    report.ours = len(ours)
    if ours:
        _save_days(get, cfg, span, ours, report, full)
        for ad in ours.values():
            _refresh(get, cfg, ad)
    return report


REMIND_DAYS = (7, 1)   # 만료 며칠 전에 알리나
TOKEN_NOTE = "⚠️ 광고 성과 토큰이 끊겼어요. Claude에게 '광고 토큰 갱신해 줘'라고 말해 주세요"
ROLE_NOTE = ('⚠️ 광고 성과를 읽지 못했어요(권한 오류). 대표님 광고 계정에서 분석자 역할이 빠졌거나 권한이 바뀌었을 수 있어요. '
             '토큰을 새로 받아도 안 풀릴 수 있어요')


def remind_expiry(today, notify):
    """만료 7일 전과 전날에 한 번씩. 같은 날 둘 다 걸리면 한 번만 알린다. 만료일마다 기억하니 갱신하면 다시 켜진다."""
    expires = expires_on()
    if expires is None:
        return
    due = [d for d in REMIND_DAYS if today >= expires - timedelta(days=d)
           and WorkerState.get(f'ads_expiry_reminded_{d}') != expires.isoformat()]
    if not due:
        return
    for d in due:
        WorkerState.put(f'ads_expiry_reminded_{d}', expires.isoformat())
    notify(f"⏰ 광고 성과 토큰이 {expires.month}월 {expires.day}일에 끝나요. Claude에게 '광고 토큰 갱신해 줘'라고 말해 주세요")


def run(today, notify, get=requests.get, llm=None):
    """워커가 매일 06:50에 부른다. 권한 오류는 하루 한 번 원인별로 알리고 None. 끝까지 성공하면 ads_ok_on.
    광고가 없는 날이 대부분이라 상태 페이지는 새 행이 아니라 ads_ok_on으로 성공을 판정한다.
    수집 뒤 책이 빈 광고를 다시 맞춘다(ad_books.relink — llm이 있으면 글자로 못 찾은 글을 광고마다 한 번 묻는다)."""
    if not configured():
        return None
    remind_expiry(today, notify)
    try:
        report = collect(today, get=get)
    except meta.MetaAuthError as e:
        if WorkerState.get('ads_auth_alert_day') != today.isoformat():
            WorkerState.put('ads_auth_alert_day', today.isoformat())
            notify(TOKEN_NOTE if e.code in meta.TOKEN_CODES else ROLE_NOTE)
        return None
    WorkerState.put('ads_ok_on', today.isoformat())
    report.linked = ad_books.relink(llm).linked
    return report


CARD_MODES = ('off', 'admin_only', 'live')
ENDED_AFTER = 3       # 지출 없는 날이 이만큼이면 끝난 광고
CARD_WAIT_MAX = 10    # 끝난 날 + 이만큼까지 판매를 기다린다(전산망은 이틀 늦다)
CARD_STALE = 14       # 이보다 오래전에 끝난 광고는 카드 없이 넘긴다(켜자마자 몰려가지 않게)
CARD_RETRY_MINUTES = 30   # 보내기가 실패하면 이만큼 쉬었다가 다시(바퀴마다 Meta를 부르지 않게)
CARD_MAX = 3          # 한 메시지에 광고 몇 개까지
CARD_FROM, CARD_UNTIL = (9, 30), (21, 0)
BASELINE_MIN, BASELINE_SPEND = 3, 10000
ORGANIC_DAYS, ORGANIC_MIN = 60, 3
HEAD = 24
CHANNEL_LABEL = {Ad.FACEBOOK: '페이스북', Ad.INSTAGRAM: '인스타그램'}
CARD_NOTE = '판매는 광고 말고도 여러 까닭으로 움직여요. 전후를 나란히 놓은 거예요.'
CARD_SOURCE = ('출처: Meta 광고 계정(한티재 페이지·인스타 게시물 광고만, 숫자는 Meta 집계), '
               '출판유통통합전산망 판매통계(종이책, 약 2일 늦게 올라옴)')


def card_mode():
    return WorkerState.get('ads_card_mode', 'off')


def card_target(bot, marketing_mode):
    """받는 곳: live(마케팅도 live) → 검수 방, admin_only(또는 마케팅이 live 아님) → 관리자 1:1, off → 없음."""
    m = card_mode()
    if m == 'off':
        return None
    if m == 'live' and marketing_mode == 'live':
        return bot.review_chat_id()
    return bot._chat(TelegramChat.ADMIN)


def name(ad):
    """'『책』 글' 또는 '「글 앞부분」 글'(서식 없음). 사이트에 아직 없는 책(북펀드)은 그 제목으로."""
    if ad.book_id:
        return f'『{ad.book.title}』 글'
    if ad.book_title:
        return f'『{ad.book_title}』 글'
    text = ad.post_text or ''
    head = text if len(text) <= HEAD else text[:HEAD].rstrip() + '…'
    return f'「{head}」 글' if head else '광고한 글'


def period(first, last):
    if first == last:
        return f'{first.month}월 {first.day}일'
    if first.month == last.month:
        return f'{first.month}월 {first.day}일~{last.day}일'
    return f'{first.month}월 {first.day}일~{last.month}월 {last.day}일'


@dataclass(frozen=True)
class SalesCompare:
    days: int
    before: Optional[int]   # None이면 앞 기간이 전산망 기록 시작보다 이르다(비교하지 못함)
    during: Optional[int]


def sales_around(book, first, last):
    """광고 기간과 같은 길이의 바로 앞 기간 판매(전산망 종이책). 아직 다 안 들어왔거나 전산망이 꺼졌으면 None."""
    if book is None or bnk_sales.mode() != 'on':
        return None
    n = (last - first).days + 1
    start = first - timedelta(days=n)
    earliest = bnk_sales.first_day()
    if earliest is None:
        return None
    if start < earliest:
        return SalesCompare(n, None, None)
    if not bnk_sales.days_ready(start, last):
        return None
    return SalesCompare(n, bnk_sales.book_total(book, start, first - timedelta(days=1)),
                        bnk_sales.book_total(book, first, last))


def skip_stale(today):
    return Ad.objects.filter(card=Ad.PENDING, last_day__lt=today - timedelta(days=CARD_STALE)).update(card=Ad.SKIPPED)


def _ready(ad, today):
    if ad.book_id is None or bnk_sales.mode() != 'on' or today >= ad.last_day + timedelta(days=CARD_WAIT_MAX):
        return True
    return sales_around(ad.book, ad.first_day, ad.last_day) is not None


def due_cards(today):
    """보낼 결과 카드 광고(먼저 끝난 순, 최대 CARD_MAX)."""
    ended = (Ad.objects.filter(card=Ad.PENDING, last_day__lte=today - timedelta(days=ENDED_AFTER))
             .select_related('book').order_by('last_day', 'id'))
    out = []
    for ad in ended:
        if _ready(ad, today):
            out.append(ad)
            if len(out) == CARD_MAX:
                break
    return out


def _ad_block(ad):
    days = AdDay.objects.filter(ad=ad, spend__gt=0).count()
    lines = [f'<b>{h(name(ad))}</b> ({CHANNEL_LABEL[ad.channel]})',
             f'{period(ad.first_day, ad.last_day)} · {days}일 · {ad.spend:,}원']
    if ad.reach and ad.spend:
        lines.append(f'· {ad.reach:,}명에게 보였어요 (1,000원에 {round(ad.reach * 1000 / ad.spend):,}명)')
    lines.append(f'· 글을 누른 횟수 {ad.clicks:,}번, 그중 링크 {ad.link_clicks:,}번')
    lines.append(f'· 반응 {ad.reactions:,}')
    return '\n'.join(lines)


def _sales_lines(ads_):
    """책마다 한 번: 그 책 광고들의 처음~끝."""
    spans = {}
    for ad in ads_:
        if ad.book_id:
            book, first, last = spans.get(ad.book_id, (ad.book, ad.first_day, ad.last_day))
            spans[ad.book_id] = (book, min(first, ad.first_day), max(last, ad.last_day))
    out = []
    for book, first, last in spans.values():
        s = sales_around(book, first, last)
        if s is None:
            continue
        if s.during is None:
            out.append(f'· 『{h(book.title)}』 판매는 기록이 그보다 늦게 시작돼 비교하지 못했어요')
        else:
            out.append(f'· 전산망 판매 『{h(book.title)}』: 광고 전 {s.days}일 {s.before}권 → 광고 {s.days}일 {s.during}권')
    return out


def _organic_line(now, fetch):
    """공식 페북에서 광고하지 않은 최근 글의 반응 중앙값. 못 읽거나 글이 적으면 ''."""
    try:
        got = fetch(now - timedelta(days=ORGANIC_DAYS), now).get('facebook')
    except Exception as e:
        log.warning('ads organic posts: %s', type(e).__name__)
        return ''
    paid = post_ids()
    counts = [p.reactions for p in got or [] if p.id not in paid]
    if len(counts) < ORGANIC_MIN:
        return ''
    return f'· 광고 없는 평소 페북 글은 보통 반응 {round(median(counts)):,}'


def _baseline_line(ads_):
    shown = [a.pk for a in ads_]
    rates = [a.reach * 1000 / a.spend for a in
             Ad.objects.filter(spend__gte=BASELINE_SPEND, reach__gt=0).exclude(pk__in=shown)]
    if len(rates) < BASELINE_MIN:
        return ''
    return f'· 지난 한티재 광고 {len(rates)}개는 보통 1,000원에 {round(median(rates)):,}명에게 보였어요'


def card_text(ads_, now, fetch=meta.channel_posts):
    parts = ['<b>📣 광고 결과</b>'] + [_ad_block(a) for a in ads_]
    sales = _sales_lines(ads_)
    tail = [x for x in [_organic_line(now, fetch), *sales, _baseline_line(ads_)] if x]
    tail += [f'· {h(name(a))}: ' + ('아직 사이트 도서 목록에 없는 책이라 판매는 뺐어요' if a.book_title
                                    else '어느 책 광고인지 몰라 판매는 뺐어요') for a in ads_ if not a.book_id]
    if tail:
        parts.append('\n'.join(tail))
    if any('권 →' in x for x in sales):
        parts.append(CARD_NOTE)
    parts.append(f'<blockquote expandable>{h(CARD_SOURCE)}</blockquote>')
    return '\n\n'.join(parts)


def send_due_cards(bot, now, fetch=meta.channel_posts):
    """하루 한 메시지(광고 최대 CARD_MAX개), 09:30~21:00. 보낸 뒤에만 '보냄'으로 적는다(실패하면 다음 바퀴에 다시)."""
    if card_mode() == 'off':   # 꺼져 있으면 bot도 건드리지 않는다
        return 0
    local = kst_now(now)
    today = local.date()
    if not CARD_FROM <= (local.hour, local.minute) < CARD_UNTIL or WorkerState.get('ads_card_day') == today.isoformat():
        return 0
    if WorkerState.get('ads_ok_on') != today.isoformat():   # 오늘 수집이 안 됐으면 낡은 숫자 때문에 진행 중인 광고가 끝난 것처럼 보인다
        return 0
    chat = card_target(bot, bot.marketing.mode())
    if chat is None:
        return 0
    skip_stale(today)
    ads_ = due_cards(today)
    if not ads_:
        return 0
    try:
        last_try = datetime.fromisoformat(WorkerState.get('ads_card_last_try') or '')
    except ValueError:
        last_try = None
    if last_try and timedelta(0) <= now - last_try < timedelta(minutes=CARD_RETRY_MINUTES):
        return 0
    WorkerState.put('ads_card_last_try', now.isoformat())
    bot.tg.send_message(chat, card_text(ads_, now, fetch), html=True)
    Ad.objects.filter(pk__in=[a.pk for a in ads_]).update(card=Ad.SENT, card_sent_at=now)
    WorkerState.put('ads_card_day', today.isoformat())
    return 1


def post_ids():
    """광고한 글 번호(페북 글·인스타 글). 반응 비교에서 광고 글을 가릴 때 쓴다."""
    out = set()
    for post_id, media in Ad.objects.values_list('post_id', 'ig_media_id'):
        out.update(x for x in (post_id, media) if x)
    return out


def _spend_by_ad(start, end):
    """start~end 지출이 있었던 광고별 (Ad, 날 수, 금액), 금액 큰 순."""
    rows = list(AdDay.objects.filter(day__range=(start, end), spend__gt=0).values('ad')
                .annotate(total=Sum('spend'), days=Count('day')).order_by('-total', 'ad'))
    found = Ad.objects.select_related('book').in_bulk([r['ad'] for r in rows])
    return [(found[r['ad']], r['days'], r['total']) for r in rows]


def week_text(start, end):
    """브리핑 '지난주 공식 채널' 줄 끝 한 마디(서식 없음). 그 주 지출만 센다. 없으면 ''."""
    rows = _spend_by_ad(start, end)
    if not rows:
        return ''
    parts = [f'{name(ad)} {days}일 · {total:,}원' + (f' · 지금까지 {ad.reach:,}명에게 보였어요' if ad.reach else '')
             for ad, days, total in rows[:2]]
    more = len(rows) - 2
    return '지난주 광고: ' + ', '.join(parts) + (f' 외 {more}건' if more > 0 else '')


def measure_note(ids):
    """그 글을 광고했으면 '(광고 7일 · 35,000원 포함)'. 같은 글의 광고가 여럿이면 합치고 날은 겹치지 않게 센다."""
    ids = {i for i in ids if i}
    found = list(Ad.objects.filter(Q(post_id__in=ids) | Q(ig_media_id__in=ids), spend__gt=0)) if ids else []
    if not found:
        return ''
    days = AdDay.objects.filter(ad__in=found, spend__gt=0).values('day').distinct().count()
    return f'(광고 {days}일 · {sum(a.spend for a in found):,}원 포함)'


def month_lines(start, end):
    """월간 돌아보기 '💸 광고' 칸(서식 없는 줄). 그 달 지출만 센다. 금액 큰 순 3줄, 나머지는 '외 n건'. 없으면 []."""
    rows = _spend_by_ad(start, end)
    if not rows:
        return []
    lines = [f'광고 {len(rows)}건 · 광고비 {sum(t for _, _, t in rows):,}원']
    for ad, days, total in rows[:3]:
        line = f'{name(ad)}: {days}일 · {total:,}원'
        if ad.reach:
            line += f' · 지금까지 {ad.reach:,}명에게 보였어요'
        s = sales_around(ad.book, ad.first_day, ad.last_day) if ad.book_id and ad.first_day else None
        if s and s.during is not None:
            line += f' · 전산망 판매 광고 전 {s.days}일 {s.before}권 → 광고 {s.days}일 {s.during}권'
        lines.append(line)
    if len(rows) > 3:
        rest = rows[3:]
        lines.append(f'외 {len(rest)}건 {sum(t for _, _, t in rest):,}원')
    return lines


USAGE = '사용법: /ads · /ads now (지금 읽기) · /ads card off|admin_only|live (결과 카드 받는 곳)'


def report_text(report):
    line = f'기간에 돈 광고 {report.found}개 중 한티재 광고 {report.ours}개(새로 {report.new}개) · 일별 {report.days}줄'
    line += f' · 인스타 글 주인을 확인하지 못한 광고 {report.unknown}개(내일 다시)' if report.unknown else ''
    line += f' · 목록에 없어 따로 못 읽은 광고 {report.unlisted}개' if report.unlisted else ''
    return line + (f' · 책을 새로 정한 광고 {report.linked}개' if report.linked else '')


def saved_text():
    s = Ad.objects.aggregate(n=Count('id'), first=Min('first_day'), last=Max('last_day'), spend=Sum('spend'))
    return (f"저장된 한티재 광고 {s['n']}개 · {s['first'] or '—'}~{s['last'] or '—'} · "
            f"합계 {s['spend'] or 0:,}원")


def status_text(today):
    expires = expires_on()
    lines = [f"광고 토큰 만료 {expires.isoformat() if expires else '설정 없음'} · ads_card_mode={card_mode()} · "
             f"마지막 성공 {WorkerState.get('ads_ok_on') or '없음'}"]
    recent = (Ad.objects.filter(last_day__gte=today - timedelta(days=90)).select_related('book')
              .order_by('-last_day')[:10])
    lines += [f'· {name(a)} {period(a.first_day, a.last_day)} {a.spend:,}원 · {a.reach:,}명 · 카드 {a.get_card_display()}'
              for a in recent] or ['최근 90일 한티재 광고 없음']
    return '\n'.join(lines + [USAGE])
