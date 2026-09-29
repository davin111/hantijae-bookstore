"""운영진 개인 SNS 수집 점검(관리자용).

  --status                                  상태와 최근 실행 5개
  --run facebook|instagram [--limit N]      일정과 상관없이 한 번 실행(상한·월 예산 그대로). 끝날 때까지 기다린다
  --from-file PATH --platform P [--dry-run] 내려받은 Apify 데이터셋을 Apify 없이 같은 경로(저장→판정→후보)로.
                                            --dry-run은 끝에 모두 되돌려 운영 DB에 아무것도 남기지 않는다
"""
import json
import time
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from intake.deps import build_deps
from marketing import candidates, social, social_judge
from marketing.apify import Apify
from marketing.models import SocialRun
from marketing.social_parse import FACEBOOK, INSTAGRAM
from marketing.timeutil import kst_today


class Rollback(Exception):
    pass


class Command(BaseCommand):
    help = '운영진 개인 SNS 수집 점검'

    def add_arguments(self, parser):
        parser.add_argument('--status', action='store_true')
        parser.add_argument('--run', choices=(FACEBOOK, INSTAGRAM))
        parser.add_argument('--limit', type=int, default=social.NORMAL_LIMIT)
        parser.add_argument('--from-file')
        parser.add_argument('--platform', choices=(FACEBOOK, INSTAGRAM))
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **o):
        now = timezone.now()
        if o['status']:
            for line in social.status_lines(now):
                self.stdout.write(line)
            for r in SocialRun.objects.order_by('-started_at', '-id')[:5]:
                self.stdout.write(f'{r.started_at:%m-%d %H:%M} {r.platform} {r.purpose} {r.state} '
                                  f'${r.cost_usd} {json.dumps(r.stats, ensure_ascii=False)} {r.error}')
            return
        token, accounts = social.config()
        if not accounts:
            raise CommandError('SOCIAL_ACCOUNTS가 없어요')
        if o['run']:
            self._run(o['run'], o['limit'], token, accounts, now)
        elif o['from_file']:
            if not o['platform']:
                raise CommandError('--platform 이 필요해요')
            self._from_file(o['from_file'], o['platform'], o['dry_run'], accounts, now)
        else:
            raise CommandError('--status, --run, --from-file 가운데 하나를 주세요')

    def _run(self, platform, limit, token, accounts, now):
        if not token:
            raise CommandError('APIFY_TOKEN이 없어요')
        deps, client = build_deps(), Apify(token)
        roles = [a['role'] for a in accounts if a.get(platform)]
        run = social.start(deps, client, platform, SocialRun.MANUAL, roles, limit, accounts, now)
        while run.state in (SocialRun.STARTING, SocialRun.RUNNING):
            time.sleep(10)
            social.poll(deps, client, platform, accounts, timezone.now())
            run.refresh_from_db()
        self.stdout.write(f'{run.state} 상한 ${run.cap_usd} 청구 ${run.cost_usd} '
                          f'{json.dumps(run.stats, ensure_ascii=False)} {run.error}')

    def _from_file(self, path, platform, dry_run, accounts, now):
        with open(path, encoding='utf-8') as f:
            items = json.load(f)
        deps = build_deps()
        try:
            with transaction.atomic():
                run = SocialRun.objects.create(platform=platform, purpose=SocialRun.MANUAL, apify_run_id='file',
                                               accounts=[a['role'] for a in accounts if a.get(platform)],
                                               limit=max(len(items), 1), cap_usd=Decimal('0'), cost_usd=Decimal('0'),
                                               started_at=now)
                new = social.store(run, items, accounts, now)
                signals = social_judge.judge_pending(deps.llm, now, social.labels(accounts))
                run.refresh_from_db()
                self.stdout.write(f'계정별: {json.dumps(run.stats, ensure_ascii=False)}')
                self.stdout.write(f'새 글 {len(new)}건, 관련 신호 {len({s.id for s in signals})}개')
                for p in new:
                    p.refresh_from_db()
                    v = p.verdict
                    self.stdout.write(f'- {p.account} {p.posted_at:%m-%d} '
                                      + (f'따름 #{v["follows"]}' if 'follows' in v else
                                         '기준선' if v.get('baseline') else
                                         f'관련={v.get("relevant")} 사생활={v.get("private")} {v.get("category")} '
                                         f'책={v.get("books")} 미등록={v.get("titles")} 행사={v.get("event")}'))
                kinds = [c.kind for c in candidates.social_candidates(kst_today(now), now, None)]
                self.stdout.write(f'sns 후보 종류: {kinds}')
                if dry_run:
                    raise Rollback()
        except Rollback:
            self.stdout.write('dry-run: 저장하지 않았어요')
