# 옛 편지 나누기(데이터만). 칸은 0012에서 — MySQL은 DDL을 트랜잭션으로 묶지 못하니 칸 바꾸기와 데이터 바꾸기를 나눈다.

import re

from django.db import migrations

# 예전 편지는 '알리면 좋을 곳' 목록이 본문 머리에 붙어 있었다. 목록을 extra로 떼어 내 본문이 곧 보낼 글이 되게 한다.
HEAD = '알리면 좋을 곳\n'
_SEP = re.compile(r'\n\n보낼 글(?: \((?P<to>[^\n]*)\))?\n(?:제목: (?P<title>[^\n]*)\n\n)?')


def split_letter(title, body):
    """예전 편지 본문(보낼 곳 목록이 본문 머리에 있던 모양) → (제목, 본문, extra). 모양이 다르면 None."""
    if not body.startswith(HEAD):
        return None
    m = _SEP.search(body)
    if not m:
        return None
    lines = body[:m.start()].split('\n')[1:]
    if not all(line.startswith('· ') for line in lines):
        return None  # 머리에 목록 말고 다른 문단이 있으면 잃지 않도록 건드리지 않는다
    places = [line[2:].strip() for line in lines]
    inner = (m.group('title') or '').strip()
    if title and inner:
        return None  # 제목이 이미 있는데 본문에도 '제목:' 줄이 있으면 나누며 그 줄을 잃으니 그대로 둔다
    moved = bool(inner)
    extra = {'places': places, 'to': (m.group('to') or '').strip(),
             'legacy': 'brief' if m.group(0) == '\n\n보낼 글\n' else 'kit', 'title_moved': moved}
    return (inner[:300] if moved else title), body[m.end():], extra  # Draft.title은 300자


def join_letter(title, body, extra):
    """split_letter의 반대. 새 코드가 만든 편지(legacy 없음)는 받는 곳이 있으면 신간 모양으로 붙인다."""
    legacy = extra.get('legacy') or ('kit' if extra.get('to') else 'brief')
    moved = extra.get('title_moved', legacy == 'kit' and 'legacy' not in extra)
    places = '\n'.join(f'· {p}' for p in extra.get('places', []))
    if legacy == 'kit':
        inner = title if moved else ''
        return ('' if moved else title), f'{HEAD}{places}\n\n보낼 글 ({extra.get("to", "")})\n제목: {inner}\n\n{body}'
    return title, f'{HEAD}{places}\n\n보낼 글\n{body}'


def forward(apps, schema_editor):
    Draft = apps.get_model('marketing', 'Draft')
    for d in Draft.objects.filter(channel='letter', body__startswith=HEAD):
        out = split_letter(d.title, d.body)
        if out:
            d.title, d.body, d.extra = out[0], out[1], {**(d.extra or {}), **out[2]}
            d.save(update_fields=['title', 'body', 'extra'])


def backward(apps, schema_editor):
    Draft = apps.get_model('marketing', 'Draft')
    for d in Draft.objects.filter(channel='letter'):
        extra = d.extra or {}
        if extra.get('places') or extra.get('to'):
            d.title, d.body = join_letter(d.title, d.body, extra)
            d.save(update_fields=['title', 'body'])


class Migration(migrations.Migration):

    dependencies = [
        ('marketing', '0012_notion_copy'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
