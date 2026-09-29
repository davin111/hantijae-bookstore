"""운영진 개인 SNS 수집(Apify): 일정·실행 상태·저장·틈·건강 검사·보관. 글 해석은 social_judge가 한다.
설계(로컬 문서): .claude/docs/specs/2026-09-30-personal-social-collector-design.md

빈 결과를 '새 글 없음'으로 오인하지 않으려고 매번 최근 몇 건을 일부러 겹치게 받는다:
- 0건·오류만·필수 필드 빠짐 → 그 계정은 실패
- 받은 글이 모두 처음 보는 글이고 한도만큼 찼다 → 틈(사이에 놓친 글이 있을 수 있음) → 20건으로 한 번 더"""
import json
from datetime import timedelta

from django.conf import settings
from django.db.models import Max

from intake.models import WorkerState
from marketing import social_judge
from marketing.models import SocialPost, SocialRun
from marketing.social_parse import FACEBOOK, parse_facebook, parse_instagram

OK_KEY = 'marketing_social_ok'   # {"facebook:editor": ISO 시각} — 정상으로 받은 계정만 갱신한다
BASELINE_DAYS = 30               # 이보다 오래된 글은 '본 글'로만 두고 판정하지 않는다


def config():
    """(Apify 토큰, 계정 목록). 계정 JSON이 깨졌으면 빈 목록."""
    cfg = getattr(settings, 'MARKETING', {})
    try:
        accounts = json.loads(cfg.get('SOCIAL_ACCOUNTS') or '[]')
    except ValueError:
        accounts = []
    return cfg.get('APIFY_TOKEN', ''), [a for a in accounts if isinstance(a, dict) and a.get('role')]


def labels(accounts):
    return {a['role']: a.get('label') or a['role'] for a in accounts}


def account_status(c):
    if c['items'] == 0:
        return 'empty'
    if c['valid'] == 0 and c['errors']:
        return 'error'
    if c['valid'] * 2 < c['items']:
        return 'malformed'
    return 'ok'


def mark_ok(platform, role, now):
    ok = dict(WorkerState.get(OK_KEY) or {})
    ok[f'{platform}:{role}'] = now.isoformat()
    WorkerState.put(OK_KEY, ok)


def _save(p, run, now):
    post = SocialPost.objects.create(platform=p.platform, account=p.account, post_id=p.post_id, url=p.url[:1000],
                                     posted_at=p.posted_at, text=p.text, shared=p.shared, link=p.link,
                                     first_run=run, first_seen=now, last_seen=now)
    post.group_key = social_judge.assign_group(post)[:300]
    fields = ['group_key']
    if p.posted_at < now - timedelta(days=BASELINE_DAYS):
        post.judged_at, post.verdict = now, {'baseline': True}
        fields += ['judged_at', 'verdict']
    post.save(update_fields=fields)
    return post


def store(run, items, accounts, now):
    """결과를 글로 저장하고 계정별 통계·틈을 적는다. 새로 본 글 목록을 돌려준다."""
    parse = parse_facebook if run.platform == FACEBOOK else parse_instagram
    parsed = parse(items, accounts)
    stats, new = {}, []
    for role in run.accounts:
        c = parsed.counts.get(role) or {'items': 0, 'valid': 0, 'errors': 0}
        mine = [p for p in parsed.posts if p.account == role]
        seen = SocialPost.objects.filter(platform=run.platform, account=role)
        newest = seen.aggregate(m=Max('posted_at'))['m']
        known = set(seen.filter(post_id__in=[p.post_id for p in mine]).values_list('post_id', flat=True))
        status = account_status(c)
        reached = (newest is None or bool(known) or len(mine) < run.limit
                   or (bool(mine) and min(p.posted_at for p in mine) <= newest))
        made = [_save(p, run, now) for p in mine if p.post_id not in known]
        SocialPost.objects.filter(platform=run.platform, post_id__in=known).update(last_seen=now)
        new += made
        stats[role] = {**c, 'new': len(made), 'known': len(known), 'reached': reached,
                       'gap': status == 'ok' and not reached, 'status': status}
        if status == 'ok':
            mark_ok(run.platform, role, now)
    run.stats, run.state, run.finished_at = stats, SocialRun.SUCCEEDED, now
    run.save(update_fields=['stats', 'state', 'finished_at'])
    return new
