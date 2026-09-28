"""텔레그램 내보내기(HTML)에서 최근 기간 메시지를 가린 채 맥락 기록에 넣는다.

개발자 컴퓨터에서 SSH 터널로 운영 DB에 넣는다(MODE=dev). 가리지 않은 원문 파일을 서버에 올리지 않기 위해서다.
실시간 기록과 번호 공간이 달라(일반 그룹) 그 방의 첫 실시간 기록보다 이른 메시지만 넣는다.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from context.models import ContextEntry
from context.redact import LABELS, redact
from context.roles import role_resolver
from context.telegram_export import parse_export


def _around(text, token, width=30):
    i = text.find(token)
    return text[max(0, i - width):i + len(token) + width].replace('\n', ' ') if i >= 0 else ''


class Command(BaseCommand):
    help = '텔레그램 내보내기(HTML) 가운데 최근 기간을 가린 채 맥락 기록에 넣는다'

    def add_arguments(self, parser):
        parser.add_argument('folder')
        parser.add_argument('--chat-id', type=int, required=True)
        parser.add_argument('--days', type=int)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--samples', type=int, default=3)

    def handle(self, *args, folder, chat_id, days=None, dry_run=False, samples=3, **options):
        days = days or settings.CONTEXT['RETENTION_DAYS']
        since = timezone.now() - timedelta(days=days)
        until = (ContextEntry.objects.filter(chat_id=chat_id, origin=ContextEntry.LIVE)
                 .order_by('at').values_list('at', flat=True).first())
        try:
            messages, errors = parse_export(folder)
        except FileNotFoundError as e:
            raise CommandError(str(e)) from None
        role_of = role_resolver()
        role_by_id = {m.id: role_of(None, m.author) for m in messages}
        skipped, counts, people, examples, entries = Counter(), Counter(), Counter(), defaultdict(list), []
        for m in messages:
            role = role_by_id[m.id]
            if m.at < since:
                skipped['기간 밖'] += 1
                continue
            if until and m.at >= until:
                skipped['실시간 기록 이후'] += 1
                continue
            if role == '봇':
                skipped['봇 메시지'] += 1
                continue
            text, c_text = redact(m.text)
            media_name, c_name = redact(m.media_name)
            c = Counter(c_text) + Counter(c_name)
            counts.update(c)
            people[(m.author, role)] += 1
            for rule in c:
                if len(examples[rule]) < samples:
                    examples[rule].append(_around(text or media_name, f'[{LABELS[rule]}]'))
            entries.append(ContextEntry(
                source=ContextEntry.TELEGRAM, origin=ContextEntry.EXPORT, key=f'tgx:{chat_id}:{m.id}',
                chat_id=chat_id, message_id=m.id, reply_to_id=m.reply_to,
                reply_to_bot=role_by_id.get(m.reply_to) == '봇', at=m.at, author_name=m.author[:100], role=role,
                text=text, redactions=dict(c), media=m.media, media_name=media_name[:200], forwarded=m.forwarded))
        self._report(len(messages), errors, len(entries), skipped, counts, examples, people)
        if dry_run:
            self.stdout.write('dry-run: 아무것도 넣지 않았어요')
            return
        exported = ContextEntry.objects.filter(chat_id=chat_id, origin=ContextEntry.EXPORT)
        before = exported.count()
        ContextEntry.objects.bulk_create(entries, batch_size=500, ignore_conflicts=True)
        added = exported.count() - before
        self.stdout.write(f'넣음 {added}건 (이미 있던 {len(entries) - added}건은 건너뜀)')

    def _report(self, read, errors, target, skipped, counts, examples, people):
        w = self.stdout.write
        w(f'읽음 {read}건 · 읽지 못함 {errors}건')
        w(f'넣을 대상 {target}건 · 건너뜀: ' + (', '.join(f'{k} {n}' for k, n in skipped.items()) or '없음'))
        w('가림: ' + (' · '.join(f'{LABELS[k]} {n}' for k, n in counts.most_common()) or '없음'))
        for rule, lines in examples.items():
            for line in lines:
                w(f'  [{LABELS[rule]}] …{line}…')
        w('이름별: ' + ', '.join(f'{name}({role}) {n}건' for (name, role), n in people.most_common()))
        if any(role == '참여자' for _, role in people):
            w('역할 없는 이름은 관리자 화면 "대화 참여자 역할"에서 별칭으로 연결한 뒤 다시 돌리세요')
