"""광고 결과 카드의 발송 위치와 보고 범위. 기존 WorkerState를 써서 스키마 변경 없이 추적한다.

번호가 없는 과거 카드는 추측해 다시 보내지 않는다. 실제 메시지를 확인한 뒤 remember로 등록한다.
수동 보충 설명은 notes에도 남겨야 다음 갱신 때 보존된다(Telegram Bot API는 과거 본문 조회가 없다).
"""
from datetime import date, datetime, timedelta

from intake.models import WorkerState
from intake.telegram_api import TEXT_LIMIT
from marketing.messages import h
from marketing.models import Ad
from marketing.timeutil import kst_now

PREFIX = 'ads_card_message_'
EXTENSION_NOTE = '연장 집행을 포함한 누적 결과예요. 중간에 광고하지 않은 날은 집행 일수에서 뺐어요.'


def checked_text(text):
    # TelegramAPI의 긴 글 일반 텍스트 잘라 보내기를 피한다. 설명이나 묶음 광고가 조용히 사라지면 안 된다.
    if len(text) > TEXT_LIMIT:
        raise ValueError('광고 결과 카드가 너무 길어요. 설명을 줄인 뒤 다시 갱신해 주세요.')
    return text


def _ranges(ads_):
    return [{'id': a.pk, 'last_day': a.last_day.isoformat(), 'spend': a.spend} for a in ads_]


def remember(chat, message_id, ads_, text, now, notes=''):
    """성공한 전송/확인한 기존 메시지만 등록. 같은 메시지 재등록 시 별도 카드로 늘어나지 않는다."""
    if not isinstance(message_id, int) or message_id <= 0 or not ads_:
        raise ValueError('확인된 메시지 번호와 광고 목록이 필요합니다.')
    key = f'{PREFIX}{chat}_{message_id}'
    WorkerState.put(key, {'chat_id': chat, 'message_id': message_id, 'ads': _ranges(ads_),
                          'text': checked_text(text), 'notes': notes, 'updated_at': now.isoformat()})
    return key


def refresh_due(bot, chat, now, fetch):
    """현재 수신 방의 등록된 카드 하나를 갱신. 신규 카드의 하루 한 번 제한과는 독립이다.

    연장된 모든 광고가 종료되고 개별 전체 합계도 오늘 읽혔을 때만 묶음 전체를 다시 만든다.
    Telegram 실패 시 보고 범위를 유지하며 같은 메시지만 재시도한다.
    """
    from marketing import ads

    today = kst_now(now).date()
    records = WorkerState.objects.filter(key__startswith=PREFIX).order_by('key')
    for row in records:
        record = row.value
        if record['chat_id'] != chat:
            continue
        snapshots = record['ads']
        found = Ad.objects.select_related('book').in_bulk([s['id'] for s in snapshots])
        if len(found) != len(snapshots):
            continue  # 묶음 중 하나라도 없어졌으면 나머지만으로 원문을 덮어쓰지 않는다
        members = [found[s['id']] for s in snapshots]
        if any(a.card != Ad.SENT or a.last_day is None for a in members):
            continue
        extended = [found[s['id']] for s in snapshots
                    if found[s['id']].last_day > date.fromisoformat(s['last_day'])]
        if not extended or any(a.last_day > today - timedelta(days=ads.ENDED_AFTER)
                               or not a.totals_at or kst_now(a.totals_at).date() != today
                               for a in extended) or not ads.card_sales_ready(members, today):
            continue
        last_try = datetime.fromisoformat(record['last_try']) if record.get('last_try') else None
        if last_try and timedelta(0) <= now - last_try < timedelta(minutes=ads.CARD_RETRY_MINUTES):
            continue
        record['last_try'] = now.isoformat()
        WorkerState.put(row.key, record)
        body = ads.card_text(members, now, fetch)
        body += '\n\n' + EXTENSION_NOTE
        if record.get('notes'):
            body += '\n\n' + h(record['notes'])
        checked_text(body)
        # edit_text는 'message is not modified'도 성공으로 처리하므로 응답 후 DB 저장 재시도가 안전하다.
        bot.tg.edit_text(chat, record['message_id'], body, html=True)
        record.update(ads=_ranges(members), text=body, updated_at=now.isoformat())
        WorkerState.put(row.key, record)
        return 1
    return 0
