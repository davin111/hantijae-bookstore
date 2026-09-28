"""텔레그램 사람 → 역할. 나중에 LLM에는 이름 대신 역할만 보낸다."""
from django.db.models import Q

from context.models import DEFAULT_ROLE, ContextEntry, Participant


def role_resolver():
    """참여자 표를 한 번 읽어 (사용자 번호, 이름) → 역할 함수를 만든다. 번호가 이름보다 우선."""
    by_id, by_name = {}, {}
    for p in Participant.objects.all():
        if p.telegram_user_id:
            by_id[p.telegram_user_id] = p.role
        for name in p.names():
            by_name.setdefault(name, p.role)
    return lambda author_id, name: by_id.get(author_id) or by_name.get((name or '').strip()) or DEFAULT_ROLE


def resolve_role(author_id, name):
    return role_resolver()(author_id, name)


def refresh_roles(participant):
    """이 참여자와 맞는 기존 기록의 역할을 다시 계산한다. 참여자를 저장·삭제한 뒤 부른다."""
    match = Q(pk__in=[])
    if participant.telegram_user_id:
        match |= Q(author_id=participant.telegram_user_id)
    if participant.names():
        match |= Q(author_name__in=participant.names())
    role_of = role_resolver()
    for author_id, name in set(ContextEntry.objects.filter(match).values_list('author_id', 'author_name')):
        ContextEntry.objects.filter(author_id=author_id, author_name=name).update(role=role_of(author_id, name))
