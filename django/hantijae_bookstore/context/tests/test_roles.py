from datetime import datetime, timezone

from django.test import TestCase

from context.models import ContextEntry, Participant
from context.roles import resolve_role

AT = datetime(2026, 9, 29, 1, 0, tzinfo=timezone.utc)


def entry(key, author_id=None, name=''):
    return ContextEntry.objects.create(key=key, at=AT, author_id=author_id, author_name=name)


class RoleTest(TestCase):
    def test_user_id_wins_over_alias_and_unknown_is_participant(self):
        Participant.objects.create(role='운영진A', telegram_user_id=11)
        Participant.objects.create(role='운영진C', aliases='편집장님, 표시이름B')
        self.assertEqual(resolve_role(11, '표시이름B'), '운영진A')
        self.assertEqual(resolve_role(None, ' 표시이름B '), '운영진C')
        self.assertEqual(resolve_role(99, '모르는 사람'), '참여자')

    def test_saving_participant_updates_existing_entries(self):
        live = entry('tg:1:1', author_id=11, name='검수자A')
        exported = entry('tgx:1:5', name='대표님')
        Participant.objects.create(role='운영진A', telegram_user_id=11, aliases='대표님')
        self.assertEqual(ContextEntry.objects.get(pk=live.pk).role, '운영진A')
        self.assertEqual(ContextEntry.objects.get(pk=exported.pk).role, '운영진A')

    def test_changing_alias_or_deleting_participant_resets_roles(self):
        e = entry('tgx:1:5', name='대표님')
        p = Participant.objects.create(role='운영진A', aliases='대표님')
        p.aliases = '다른 이름'
        p.save()
        self.assertEqual(ContextEntry.objects.get(pk=e.pk).role, '참여자')
        p.aliases = '대표님'
        p.save()
        self.assertEqual(ContextEntry.objects.get(pk=e.pk).role, '운영진A')
        p.delete()
        self.assertEqual(ContextEntry.objects.get(pk=e.pk).role, '참여자')
