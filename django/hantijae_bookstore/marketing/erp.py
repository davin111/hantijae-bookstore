"""검수방 ERP 첨부 → 검산 → 월별 한 메시지. 워커만 실행하며 원본은 메모리에서 읽고 버린다."""
import calendar
import hashlib
import json
import re
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils.dateparse import parse_datetime

from context.models import ContextEntry
from intake.models import TelegramChat, WorkerState
from marketing.erp_parser import MAX_BYTES, InvalidERP, norm, parse_export, validate_pair
from marketing.models import BnkSale, ERPImport, ERPMonthlyReport
from marketing.timeutil import in_quiet_hours, kst_today

BATCH = 8
RETRY = timedelta(minutes=10)


def _hash(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def _kind(name):
    name = norm(name).replace(' ', '')
    if not name.lower().endswith(('.xlsx', '.xls')) or '집계' not in name:
        return ''
    return 'customer' if '거래처' in name else 'product' if '제품' in name else ''


def _signature(entry):
    return _hash(f'{entry.key}:{entry.file_id}:{norm(entry.media_name)}')


def _order(item):
    return item.received_at, item.pk


def _fresh(item, report):
    return bool(item and (report.accepted_at is None or _order(item) > (report.accepted_at, report.accepted_after)))


def _semantic(payload):
    # XLSX ZIP timestamps/author metadata are not a change in the ERP figures.
    content = dict(payload, rows=sorted(payload['rows'], key=lambda r: r['code']))
    return _hash(json.dumps(content, ensure_ascii=False, sort_keys=True))


def download(tg, file_id):
    info = tg.call('getFile', file_id=file_id)
    path = info.get('file_path', '')
    if info.get('file_size', 0) > MAX_BYTES:
        raise InvalidERP('파일이 너무 커요. 월별 XLSX 파일(5MB 이하)로 보내 주세요.')
    if not re.fullmatch(r'[a-zA-Z0-9_./-]+', path) or '..' in path or path.startswith('/'):
        raise RuntimeError('첨부 다운로드 경로를 확인하지 못했어요.')
    try:
        with tg.session.get(f'{tg.base}/file/bot{tg.token}/{path}', stream=True, timeout=(10, 40),
                            allow_redirects=False) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise RuntimeError()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise InvalidERP('파일이 너무 커요. 월별 XLSX 파일(5MB 이하)로 보내 주세요.')
                chunks.append(chunk)
            return b''.join(chunks)
    except InvalidERP:
        raise
    except Exception:
        # requests exception strings can contain the bot token.
        raise RuntimeError('첨부 다운로드를 마치지 못했어요.') from None


def erase_unavailable():
    """잊기·90일 정리 후 숫자를 다른 테이블에 남기지 않는다. 발송 식별자는 중복 방지용으로 유지."""
    ERPImport.objects.filter(entry__forgotten=True).exclude(status='forgotten').update(
        payload={}, text='', error='', status='forgotten', delivered_hash='')
    for report in ERPMonthlyReport.objects.exclude(pair_hash='').select_related('customer', 'product'):
        if not report.customer or not report.product or not report.customer.payload or not report.product.payload:
            report.result = {}
            report.state = 'withdrawn'
            report.text = f'📁 {report.month} ERP 보고\n원본 기록이 지워져 이 보고의 분석 내용도 지웠어요. 다시 분석하려면 두 파일을 함께 보내 주세요.'
            report.save(update_fields=['result', 'state', 'text', 'updated_at'])


def _discover(chats, start, now):
    entries = (ContextEntry.objects.filter(source=ContextEntry.TELEGRAM, origin=ContextEntry.LIVE,
               chat_id__in=chats, forgotten=False, media='document', at__gte=start, at__lte=now)
               .exclude(file_id='').order_by(Coalesce('edited_at', 'at'), 'pk'))
    # Bounded by the context retention period; persist receipts before attempting any downloads.
    for entry in entries.iterator():
        kind = _kind(entry.media_name)
        received_at = max(t for t in (entry.at, entry.edited_at) if t)
        if kind and received_at <= now:
            ERPImport.objects.filter(entry=entry).exclude(signature=_signature(entry)).exclude(status='superseded').update(
                status='superseded', text='', error='')
            ERPImport.objects.get_or_create(signature=_signature(entry), defaults={
                'entry': entry, 'chat_id': entry.chat_id, 'kind': kind, 'received_at': received_at})


def _read(item, tg, now):
    if item.signature != _signature(item.entry):
        item.status, item.payload = 'superseded', {}
        item.save(update_fields=['status', 'payload', 'updated_at'])
        return
    item.attempts += 1
    item.tried_at, item.status = now, 'retry'
    item.save(update_fields=['attempts', 'tried_at', 'status', 'updated_at'])
    try:
        if not norm(item.entry.media_name).lower().endswith('.xlsx'):
            raise InvalidERP('XLSX 형식으로 내보낸 파일이 필요해요.')
        data = download(tg, item.entry.file_id)
        item.digest = _hash(data)
        payload = parse_export(data, today=kst_today(now))
        if payload['kind'] != item.kind:
            raise InvalidERP('파일명과 표의 종류가 달라요. 원래 파일명으로 보내 주세요.')
        item.payload, item.month, item.status = payload, payload['month'], 'valid'
        item.error, item.text = '', ''
    except InvalidERP as e:
        item.status, item.error = 'invalid', str(e)
    except Exception:
        item.status = 'failed' if item.attempts >= 3 else 'retry'
        item.error = '첨부 파일을 내려받지 못했어요. 같은 파일을 다시 보내 주세요.'
    if item.status in ('invalid', 'failed'):
        item.text = f'📁 ERP 파일 확인\n{norm(item.entry.media_name)[:100]}\n{item.error}\n검산이 끝나기 전에는 보고 수치를 바꾸지 않아요.'
    # Recheck under the same row lock used by a concurrent forget/delete/update.
    # Network parsing intentionally happens outside the transaction.
    with transaction.atomic():
        current = ContextEntry.objects.select_for_update().filter(pk=item.entry_id).first()
        if current is None:
            return
        if current.forgotten or _signature(current) != item.signature:
            item.status = 'forgotten' if current.forgotten else 'superseded'
            item.payload, item.text, item.error = {}, '', ''
        item.save()


def _result(customer, product):
    c, p = customer.payload, product.payload
    start = date.fromisoformat(c['month'] + '-01')
    end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    from marketing.bnk_sales import month_ready
    bnk = None
    if month_ready(start):
        bnk = BnkSale.objects.filter(day__range=(start, end)).aggregate(n=Sum('total'))['n'] or 0
    return dict(totals=c['totals'], customer_count=c['count'], product_count=p['count'], bnk=bnk,
                top=sorted(p['rows'], key=lambda r: (-r['net_qty'], r['code']))[:5])


def _report_text(report):
    r, t = report.result, report.result['totals']
    lines = [f'📚 {report.month} ERP 출고 보고' + (' (수정)' if report.revision > 1 else ''), '',
             f'출고 {t["out_qty"]:,}권 · {t["out_amount"]:,}원',
             f'반품 {t["return_qty"]:,}권 · {t["return_amount"]:,}원',
             f'순출고 {t["net_qty"]:,}권 · {t["net_amount"]:,}원',
             f'기증 {t["gift_qty"]:,}권은 별도예요.', '',
             f'거래처 {r["customer_count"]:,}곳·제품 {r["product_count"]:,}개 행의 계산과 두 파일의 합계를 확인했어요.',
             '제공된 조회 범위의 출판사 출고액(부가세 별도)이며, 입금액·이익은 아니에요.',
             '조회 조건: 제품성격·제품상태 필터는 엑셀에 없어 확인하지 못했어요. 같은 조건으로 내보내 주세요.']
    if r['top']:
        lines += ['', '순출고 수량이 많은 책']
        lines += [f'· {row["label"][:70]}: {row["net_qty"]:,}권' for row in r['top']]
    if r['bnk'] is not None:
        lines += ['', f'같은 달 전산망 순판매 {r["bnk"]:,}권은 서점에서 독자에게 판매된 별도 지표예요. 두 수치를 더하거나 차이를 재고로 계산하지 않아요.']
    else:
        lines += ['', '같은 달 전산망은 수집 완료를 확인한 뒤 별도로 비교할 수 있어요.']
    lines += ['', '매월 마감 뒤 같은 기간·조건의 거래처별·제품별 XLSX 두 파일을 이 방에 보내 주세요. 수정할 때도 두 파일을 함께 보내면 이 보고를 갱신해요.']
    return '\n'.join(lines)


@transaction.atomic
def _prepare(chat, month):
    # Keep derived data consistent with /잊어 and edits while calculating (no network here).
    entry_ids = ERPImport.objects.filter(chat_id=chat, month=month).values_list('entry_id', flat=True)
    list(ContextEntry.objects.select_for_update().filter(pk__in=entry_ids).order_by('pk').values_list('pk', flat=True))
    report, _ = ERPMonthlyReport.objects.get_or_create(chat_id=chat, month=month)
    candidates = list(ERPImport.objects.filter(chat_id=chat, month=month, status='valid',
                      entry__forgotten=False).select_related('entry').order_by('-received_at', '-pk'))
    # Ignore old versions of an edited message, including when the replacement failed validation.
    latest = {}
    for item in candidates:
        if item.kind not in latest and item.signature == _signature(item.entry):
            latest[item.kind] = item
    c, p = latest.get('customer'), latest.get('product')
    # A newer unread/invalid export must never silently fall back to an older valid file.
    # Its month may be unreadable, so hold this chat's reports until that kind is supplied again.
    blockers = []
    for kind, candidate in (('customer', c), ('product', p)):
        bad = any(_fresh(i, report) and (not candidate or _order(i) > _order(candidate))
                  for i in ERPImport.objects.filter(chat_id=chat, kind=kind, month__in=('', month),
                       status__in=('pending', 'retry', 'invalid', 'failed'), entry__forgotten=False))
        if bad:
            blockers.append('거래처별' if kind == 'customer' else '제품별')
    if blockers:
        report.state = 'blocked'
        report.text = (f'📁 {month} ERP 보고 보류\n새로 받은 {"·".join(blockers)} 파일의 검산이 아직 끝나지 않았어요. '
                       '앞서 받은 파일로 대신 계산하지 않고 기다릴게요.')
        report.save()
        return report
    changed = [i for i in (c, p) if _fresh(i, report)]
    if report.pair_hash and not changed:
        if any(i and i.status == 'superseded' for i in (report.customer, report.product)):
            report.state, report.result = 'blocked', {}
            report.text = (f'📁 {month} ERP 보고 보류\n원본 첨부의 기간·내용이 바뀌었어요. '
                           f'{month} 거래처별·제품별 파일을 다시 함께 보내 주세요.')
            report.save()
        return report
    # One identical re-upload is just a receipt, not an incomplete correction.
    if report.pair_hash and len(changed) == 1 and report.state == 'ready':
        old = report.customer if changed[0].kind == 'customer' else report.product
        if old and old.payload and _semantic(old.payload) == _semantic(changed[0].payload):
            return report
    fresh_pair = c and p and (not report.pair_hash or (_fresh(c, report) and _fresh(p, report)))
    if not fresh_pair:
        missing = '거래처별·제품별' if not c and not p else '제품별' if c and not _fresh(p, report) else '거래처별'
        report.state = 'waiting'
        report.text = (f'📁 {month} ERP 파일을 받았어요.\n' + ('수정본은 두 파일이 모두 필요해요. ' if report.pair_hash else '')
                       + f'같은 기간·조회 조건의 {missing} XLSX 파일도 보내 주세요.\n두 파일의 검산이 끝나면 이 메시지를 보고로 바꿀게요.')
    else:
        try:
            validate_pair(c.payload, p.payload)
        except InvalidERP as e:
            report.state = 'blocked'
            report.text = f'📁 {month} ERP 보고 보류\n{e}\n기존에 검산한 수치에도 더하지 않았어요.'
        else:
            pair_hash = _hash(_semantic(c.payload) + ':' + _semantic(p.payload))
            if report.pair_hash != pair_hash or not report.result:
                report.result = _result(c, p)
                report.revision += 1
            report.customer, report.product = c, p
            report.accepted_at, report.accepted_after = max(_order(c), _order(p))
            report.pair_hash = pair_hash
            report.state = 'ready'
            report.text = _report_text(report)
    report.save()
    return report


def _deliver(item, tg, now, reply_to=None):
    cls = type(item)
    with transaction.atomic():
        current = cls.objects.select_for_update().get(pk=item.pk)
        if not current.text:
            return
        digest = _hash(current.text)
        if current.delivered_hash == digest:
            return
        if current.delivery_state in ('uncertain', 'sending') and not current.message_id:
            if current.delivery_state == 'sending' and current.delivery_try_at and now - current.delivery_try_at >= RETRY:
                current.delivery_state = 'uncertain'
                current.delivery_error = '첫 발송 결과 확인이 필요해요. 자동 재발송은 멈췄어요.'
                current.save(update_fields=['delivery_state', 'delivery_error', 'updated_at'])
            return
        if current.delivery_try_at and current.delivery_state != 'sent' and now - current.delivery_try_at < RETRY:
            return
        current.delivery_state, current.delivery_try_at = 'sending', now
        current.save(update_fields=['delivery_state', 'delivery_try_at', 'updated_at'])
    try:
        if current.message_id:
            tg.edit_text(current.chat_id, current.message_id, current.text)
        else:
            sent = tg.send_message(current.chat_id, current.text, reply_to=reply_to)
            current.message_id = sent['message_id']
        current.delivery_state, current.delivered_hash, current.delivery_error = 'sent', digest, ''
    except Exception:
        current.delivery_state = 'retry' if current.message_id else 'uncertain'
        current.delivery_error = ('기존 보고 수정 재시도 대기' if current.message_id else
                                  '첫 발송 결과 확인이 필요해요. 자동 재발송은 멈췄어요.')
    current.save(update_fields=['message_id', 'delivery_state', 'delivered_hash', 'delivery_error', 'updated_at'])


def run(bot, now):
    if (WorkerState.get('erp_mode', 'off') != 'live' or WorkerState.get('mode') != 'live'
            or WorkerState.get('marketing_mode', 'off') != 'live' or not WorkerState.get('context_record', False)):
        return
    start = parse_datetime(WorkerState.get('erp_start_at', '') or '')
    if not start or start.tzinfo is None:
        raise ValueError('ERP 수신 시작 시각(시간대 포함)을 먼저 설정해 주세요.')
    chats = list(TelegramChat.objects.filter(kind=TelegramChat.REVIEWERS).values_list('chat_id', flat=True))
    erase_unavailable()
    _discover(chats, start, now)
    pending = ERPImport.objects.filter(status__in=('pending', 'retry'), chat_id__in=chats,
                                       entry__forgotten=False).select_related('entry').order_by('pk')
    read = 0
    for item in pending:
        if item.tried_at and now - item.tried_at < RETRY:
            continue
        _read(item, bot.tg, now)
        read += 1
        if read >= BATCH:
            break
    months = list(ERPImport.objects.filter(status='valid', chat_id__in=chats).exclude(month='')
                  .values_list('chat_id', 'month').distinct())
    for chat, month in months:
        _prepare(chat, month)
    if not in_quiet_hours(now):
        for report in ERPMonthlyReport.objects.filter(chat_id__in=chats):
            first = ERPImport.objects.filter(chat_id=report.chat_id, month=report.month).select_related('entry').first()
            _deliver(report, bot.tg, now, first.entry.message_id if first else None)
        for item in ERPImport.objects.filter(status__in=('invalid', 'failed'), chat_id__in=chats).select_related('entry'):
            if item.signature == _signature(item.entry) and not item.entry.forgotten:
                _deliver(item, bot.tg, now, item.entry.message_id)
    WorkerState.put('erp_last_scan', now.isoformat())
