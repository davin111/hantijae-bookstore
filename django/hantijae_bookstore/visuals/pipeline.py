import hashlib
import json
import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from books.models import Book
from intake.llm import parse_json_object
from intake.models import TelegramChat, WorkerState
from marketing.models import BookProfile, Draft, Proposal, Signal
from marketing.timeutil import KST, in_quiet_hours, week_start
from visuals.assets import load_assets, root, source_versions, sources_current
from visuals.delivery import deliver
from visuals.models import CardJob
from visuals.policy import card_kind, illustration_decision
from visuals.prompts import ART, DECISION
from visuals.render import render_packet
from visuals.svg import validate_svg
from visuals.quality import assess, current_sources, files_approved, hold
from visuals.handoff import deliver_handoff

log = logging.getLogger('intake')


def fingerprint(draft):
    book = draft.proposal.book
    data = [draft.title, draft.body, draft.extra or {}, draft.proposal.book_id,
            [book.title, book.subtitle or '', book.cover_image.name or ''] if book else None,
            source_versions(book)]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _allowed(draft, chat_id, now):
    mode = WorkerState.get('visuals_mode', 'off')
    marketing = WorkerState.get('marketing_mode', 'off')
    if mode not in ('live', 'admin_only') or marketing not in ('live', 'admin_only'):
        return False
    chat = TelegramChat.objects.filter(chat_id=chat_id).first()
    if not chat or ((mode == 'admin_only' or marketing == 'admin_only') and chat.kind != TelegramChat.ADMIN):
        return False
    p = draft.proposal
    if draft.channel not in (Draft.INSTAGRAM, Draft.BLOG) or draft.status != Draft.DRAFT or draft.placements:
        return False
    if p.status in (Proposal.SKIPPED, Proposal.ACTED) or p.extra.get('memorial'):
        return False
    if Draft.objects.filter(proposal=p, channel=draft.channel).filter(
            Q(version__gt=draft.version) | Q(version=draft.version, pk__gt=draft.pk)).exists():
        return False
    ids = ([p.signal_id] if p.signal_id else []) + p.extra.get('signals', []) + p.extra.get('more_signal_ids', [])
    signals = list(Signal.objects.filter(pk__in=ids))
    if len(signals) != len(set(ids)):
        return False
    for signal in signals:
        d = signal.detail or {}
        event = d.get('event') if isinstance(d.get('event'), dict) else {}
        if (signal.sensitive or not signal.relevant or d.get('status') == 'cancelled'
                or event.get('status') == 'cancelled' or d.get('promoted') or event.get('promoted')):
            return False
    today = now.astimezone(KST).date()
    book_ids = set(([p.book_id] if p.book_id else []) + p.extra.get('book_ids', []))
    quiet = set(BookProfile.objects.filter(quiet_until__gte=today).values_list('book_id', flat=True))
    if book_ids & quiet or Book.objects.filter(pk__in=book_ids, is_published=True, visible=True).count() != len(book_ids):
        return False
    if p.candidate_key.startswith(('onsite:', 'reprint:')):
        from marketing import dated
        if WorkerState.get('dated_mode') != 'live' or not p.signal_id:
            return False
        live = dated._items(today, now, reserved_ids=ids, check_sent=False)
        if not any(c.id == p.candidate_key for c in live):
            return False
    if p.candidate_key.startswith('peer:'):
        from marketing import peers
        if not peers.can_send(p, today, now):
            return False
    if p.candidate_key.startswith('series:'):
        from marketing import series
        if WorkerState.get('series_mode') != 'live' or today.weekday() != 4 or not p.candidate_key.endswith(week_start(today).isoformat()):
            return False
        live = {s.pk for group in series._groups(today, now, quiet) for s in group['signals']}
        if set(ids) - live:
            return False
    if p.candidate_key.startswith('moment:') and WorkerState.get('moment_mode') != 'live':
        return False
    return True


def eligible(job, now):
    draft = Draft.objects.select_related('proposal__book').get(pk=job.draft_id)
    return (_allowed(draft, job.chat_id, now) and fingerprint(draft) == job.fingerprint
            and sources_current(job.plan) and current_sources(job, draft))


def enqueue(draft, chat_id, reply_to):
    if not reply_to or not _allowed(draft, chat_id, timezone.now()):
        return None
    if not (draft.extra or {}).get('cards'):
        return None
    job, _ = CardJob.objects.get_or_create(draft=draft, chat_id=chat_id, fingerprint=fingerprint(draft),
                                          defaults={'reply_to': reply_to})
    # 과거 발송의 키는 유지하고 아직 보내지 않은 원문 변경만 재검토한다.
    if (job.state in ('cancelled', 'queued', 'ready', 'handoff') and not job.receipt
            and not current_sources(job, draft)):
        job.state, job.plan, job.files, job.attempts = 'queued', {}, [], 0
        job.save(update_fields=['state', 'plan', 'files', 'attempts', 'updated_at'])
    return job


def enqueue_proposal(proposal, chat_id, reply_to):
    # 같은 제안에 인스타/블로그가 함께 있어도 한 벌만. 글 보기를 누르면 동일 초안 작업이 재사용된다.
    for channel in (Draft.INSTAGRAM, Draft.BLOG):
        draft = proposal.drafts.filter(channel=channel, status=Draft.DRAFT).order_by('-version', '-id').first()
        if draft and (draft.extra or {}).get('cards'):
            return enqueue(draft, chat_id, reply_to)


def safe_enqueue(draft=None, proposal=None, chat_id=None, reply_to=None):
    try:
        return enqueue(draft, chat_id, reply_to) if draft is not None else enqueue_proposal(proposal, chat_id, reply_to)
    except Exception:
        log.exception('visuals enqueue failed')
        try:
            WorkerState.put('visuals_enqueue_error', timezone.now().isoformat())
        except Exception:
            log.exception('visuals enqueue error recording failed')


def reserve_illustration(job, now):
    day = now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    if CardJob.objects.filter(illustration_at__gte=day).count() >= 2:
        return False
    same_book = CardJob.objects.filter(draft__proposal__book_id=job.draft.proposal.book_id,
                                      illustration_at__gte=now - timedelta(days=30)).exclude(pk=job.pk)
    if job.draft.proposal.book_id and same_book.exists():
        return False
    if job.illustration_at:
        return False  # 중단된 유료가 아닌 호출도 반복 생성하지 않는다.
    job.illustration_at = now
    job.save(update_fields=['illustration_at', 'updated_at'])
    return True


def build(job, llm, now):
    draft, book = job.draft, job.draft.proposal.book
    folder = root() / str(job.pk)
    folder.mkdir(parents=True, exist_ok=True)
    assets, labels, sources = load_assets(book)
    raw = (draft.extra or {}).get('cards', [])[:6]
    candidates, missing, fallbacks = [], [], []
    for item in raw:
        if not isinstance(item, dict):
            continue
        show, text = item.get('show', ''), item.get('text', '')
        if not isinstance(show, str) or not isinstance(text, str) or len(text) > 300:
            continue
        kind = card_kind(show)
        if kind in ('cover', 'toc', 'inside', 'photo') and kind not in assets:
            label = {'toc': '목차', 'inside': '본문', 'photo': '사진', 'cover': '표지'}[kind]
            if kind in ('photo', 'cover') and text.strip() and '[' not in text and ']' not in text:
                fallbacks.append(label)
                kind = 'text'  # 확인된 문구만 유지한다. 없는 사진/목차를 만들어내지 않는다.
            else:
                missing.append(label)
                continue
        if kind in ('toc', 'inside'):
            text = labels[kind]
        if '[' in text or ']' in text or not text.strip():
            continue
        candidates.append({'kind': kind, 'text': text, 'show': show})
    candidates = candidates[:4]
    themes = [c for c in candidates if c['kind'] == 'theme']
    art, decision = None, None
    if themes and 'photo' not in assets:
        try:
            value = parse_json_object(llm.complete(DECISION, json.dumps({
                'title': draft.title, 'body': draft.body[:6000], 'cards': candidates,
                'available_originals': list(labels.values())}, ensure_ascii=False)))
            decision = illustration_decision(value, sensitive=False, requested=[c['show'] for c in themes])
            if decision and reserve_illustration(job, now):
                art = validate_svg(llm.complete(ART, json.dumps({
                    'book': book.title if book else '', 'theme': decision['subject'],
                    'purpose': decision['reason']}, ensure_ascii=False)))
                (folder / 'illustration.svg').write_bytes(art)
            else:
                decision = None
        except Exception as exc:
            # 원본/글 카드는 계속 만든다. 원고·모델 응답·비밀값은 오류에 기록하지 않는다.
            log.warning('visuals illustration failed job=%s type=%s', job.pk, type(exc).__name__)
            job.error = '일러스트 제외: ' + type(exc).__name__
            art, decision = None, None
    cards, used = [], False
    for card in candidates:
        if card['kind'] == 'theme':
            if art and not used:
                card, used = {**card, 'kind': 'illustration'}, True
            else:
                card = {**card, 'kind': 'text'}
        if card['kind'] in ('toc', 'inside'):
            card = {**card, 'text': labels.get(card['kind'], card['text'])}
        cards.append(card)
    cards = cards[:4]
    if not cards:
        raise ValueError('만들 수 있는 카드가 없습니다')
    paths = render_packet(cards, assets, art, folder, title=book.title if book else draft.title)
    job.plan = {'cards': cards, 'illustration': decision if used else None,
                'missing': list(dict.fromkeys(missing)), 'text_fallbacks': list(dict.fromkeys(fallbacks)),
                'originals': labels, 'sources': sources}
    job.files = [p.name for p in paths]
    job.state = 'ready'
    job.save(update_fields=['plan', 'files', 'state', 'error', 'updated_at'])
    (folder / 'manifest.json').write_text(json.dumps(job.plan, ensure_ascii=False, indent=2))


def recover(now):
    stale = CardJob.objects.filter(started_at__lt=now - timedelta(minutes=15))
    stale.filter(state='sending').update(state='uncertain', error='전송 중 중단됨. 중복 방지를 위해 자동 재전송하지 않음')
    stale.filter(state='handoff_sending').update(state='handoff_uncertain', error='개인 제작 요청 전송 중 중단됨. 자동 재전송하지 않음')
    stale.filter(state='building').update(state='handoff', error='카드 제작·검토가 중단되어 사람의 확인이 필요합니다')


def run_once(llm, tg, now=None):
    now = now or timezone.now()
    WorkerState.put('visuals_heartbeat', now.isoformat())
    recover(now)
    if WorkerState.get('visuals_mode', 'off') == 'off' or in_quiet_hours(now):
        return None
    if TelegramChat.objects.filter(kind=TelegramChat.ADMIN, chat_id__gt=0).count() == 1:
        CardJob.objects.filter(state='handoff_waiting').update(state='handoff')
    job = CardJob.objects.filter(state__in=('queued', 'ready', 'handoff')).select_related('draft__proposal__book').first()
    if not job:
        return None
    if not eligible(job, now):
        if (not job.receipt and not current_sources(job) and _allowed(job.draft, job.chat_id, now)
                and fingerprint(job.draft) == job.fingerprint):
            CardJob.objects.filter(pk=job.pk).update(state='queued', plan={}, files=[])
            return job
        CardJob.objects.filter(pk=job.pk).update(state='cancelled')
        return job
    if job.state == 'ready' and not files_approved(job):
        if job.receipt.get('images'):
            CardJob.objects.filter(pk=job.pk).update(state='uncertain', error='이미 일부 전송된 시안의 검토 기록 확인 필요')
            return job
        job.state = 'queued'
        job.save(update_fields=['state', 'updated_at'])
    if job.state == 'queued':
        claimed = CardJob.objects.filter(pk=job.pk, state='queued').update(state='building', started_at=now,
                                                                         attempts=job.attempts + 1)
        if not claimed:
            return None
        job.state, job.attempts = 'building', job.attempts + 1
        try:
            assess(job, llm)
        except Exception as exc:
            log.warning('visuals quality needs help job=%s type=%s', job.pk, type(exc).__name__)
            job.plan.setdefault('quality', {}).setdefault('attempts', []).append({
                'stage': 'automation', 'failure_type': type(exc).__name__})
            hold(job, '자동 제작·이미지 검토를 완료하지 못했습니다. 원문과 시안을 보고 마무리가 필요합니다.')
    if job.state == 'handoff':
        deliver_handoff(job, tg, lambda: eligible(job, timezone.now()))
        return job
    try:
        deliver(job, tg, lambda: eligible(job, timezone.now()))
    except Exception as exc:
        job.refresh_from_db()
        job.state = 'uncertain' if job.state == 'sending' else 'failed'
        job.error = '이미지 전달 확인 필요: ' + type(exc).__name__
        job.save(update_fields=['state', 'error', 'updated_at'])
    return job
