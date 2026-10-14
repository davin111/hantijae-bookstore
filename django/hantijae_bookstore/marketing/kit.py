"""새 책 홍보 묶음: 공개된 지 60일 안 된 책마다 초안 한 벌을 만든다(LLM 1회). 보내기는 bot.py가 한다."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction

from books.models import Book
from intake.llm import complete_json
from intake.models import WorkerState
from marketing.hooks import upcoming
from marketing.models import BookProfile, Draft, Proposal
from marketing.prompts import KIT_SYSTEM, build_kit_user
from marketing.supplements import clean, factual, normalize_extra, normalize_hashtags, recruit_cards
from marketing.text import fix_title_marks, foreign_numbers, title_key, unverified_quotes
from web.presenters import UNTRUSTED_SHORTLINK, authors_of, credit_line, store_links

NEW_BOOK_DAYS = 60
FAILURES_KEY, MAX_FAILURES = 'marketing_kit_failures', 3  # {"<책 번호>": {"day": KST 날짜, "count": 실패 횟수}}
LINK_ORDER = (('kyobo', '교보문고'), ('aladin', '알라딘'), ('yes24', '예스24'))


def blog_has(book, posts):
    key = title_key(book.title)
    return bool(key) and any(key in title_key(p.title) for p in (posts or []))


def links_text(book):
    urls = {link.store: link.url for link in store_links(book)}
    lines = [f'『{book.title}』']
    if book.subtitle:
        lines.append(f'― {book.subtitle}')
    credit = credit_line(authors_of(book))
    if credit:
        lines.append(credit)
    lines.append('')
    lines += [f'{label} {urls[s]}' for s, label in LINK_ORDER if s in urls]
    lines.append(f'한티재 책창고 {settings.SITE_URL}/book={book.id}')
    return '\n'.join(lines)


def missing_stores(book):
    out = []
    for s, label in LINK_ORDER:
        url = (getattr(book, f'{s}_url', '') or '').strip()
        if not url or UNTRUSTED_SHORTLINK.match(url):
            out.append(label)
    return out


def quiet_until(book, today):
    """/quiet 로 홍보를 쉬는 중이면 그 마지막 날, 아니면 None."""
    return BookProfile.objects.filter(book=book, quiet_until__gte=today).values_list('quiet_until', flat=True).first()


def pending_books(today):
    done = Proposal.objects.filter(kind=Proposal.KIT).values_list('book_id', flat=True)
    return (Book.objects.filter(is_published=True, published_date__gte=today - timedelta(days=NEW_BOOK_DAYS),
                                published_date__lte=today)
            .exclude(id__in=done).exclude(marketing__quiet_until__gte=today).order_by('published_date', 'id'))


def _clean(value):
    return fix_title_marks(str(value or '').strip())


RECRUIT_FIELDS = ('[모집 인원]', '[신청 마감]', '[발표]', '[서평 올릴 곳]', '[서평 기간]')


def _recruit_body(raw, book, allowed):
    """운영진이 아직 결정하지 않은 모집 조건은 반드시 빈칸으로 둔다."""
    import re
    body = clean(raw)
    if not body:
        return ''
    if not all(field in body for field in RECRUIT_FIELDS) or not factual(body, allowed):
        return '\n'.join([f'『{book.title}』 서평단을 모십니다.', '',
                          '이 글에 댓글로 읽고 싶은 이유를 한 줄 남겨 주세요.', '',
                          *RECRUIT_FIELDS, '', '#한티재의책'])
    # 같은 숫자가 책 쪽수에 있더라도 모집 인원으로 승인된 것은 아니다.
    # 모집 조건·혜택은 모델 문장을 쓰지 않고 정해진 빈칸으로만 안내한다.
    conditions = re.compile(r'모집|신청|마감|발표|서평|기간|인원|선착순|증정|추첨|당첨|제공|선물|선정')
    lines = [line for line in body.splitlines()
             if not conditions.search(line) and book.title not in line]
    body = '\n'.join(lines).strip()
    tags = normalize_hashtags(re.findall(r'#[\w가-힣]+', body), allowed)
    body = re.sub(r'#[\w가-힣]+', '', body).strip()
    return '\n\n'.join(p for p in [f'『{book.title}』 서평단을 모십니다.', body,
                                    '이 글에 댓글로 읽고 싶은 이유를 한 줄 남겨 주세요.',
                                    '\n'.join(RECRUIT_FIELDS), ' '.join(tags)] if p)


def _editor_questions(raw, allowed):
    if not isinstance(raw, list):
        return ''
    questions = []
    for value in raw:
        text = clean(value)
        if (text and len(text) <= 200 and text not in questions and factual(text, allowed)
                and (text.endswith(('?', '？', '은', '는')))):
            questions.append(text)
    if len(questions) < 2:
        return ''
    return '\n'.join(['편집 후기 질문', *[f'{i}. {q}' for i, q in enumerate(questions[:3], 1)], '',
                      '이 메시지에 답장으로 생각나는 대로 짧게 적어 주시면, 네이버 블로그 「편집 일기」 글로 다듬어 드릴게요.',
                      '여러 번 나눠 답장하셔도 돼요.'])


def build_kit(book, llm, posts, today):
    exists = blog_has(book, posts)
    hooks = [f'{on.month}월 {on.day}일 {h.name}' + (' (추모 성격)' if h.memorial else '')
             for h, on in upcoming(today, 45) if book in h.books.all()]
    out = complete_json(llm, KIT_SYSTEM, build_kit_user(book, credit_line(authors_of(book)), today, exists, hooks))
    source = '\n'.join([book.description or '', book.short_description or ''])
    allowed = [source, book.title, book.subtitle or '', str(book.page_count), str(book.full_price),
               book.published_date.isoformat(), credit_line(authors_of(book)), '200자 소개']
    with transaction.atomic():  # 도중에 실패하면 반쯤 저장된 묶음이 나가지 않게 통째로 되돌린다
        p = Proposal.objects.create(kind=Proposal.KIT, book=book, headline=f'『{book.title}』 홍보 자료'[:300],
                                    caution=_clean(out.get('caution')),
                                    extra={'blog_exists': exists, 'missing_stores': missing_stores(book)})
        blog_body = _clean(out.get('blog_body'))
        if not exists and blog_body:
            Draft.objects.create(proposal=p, channel=Draft.BLOG, title=_clean(out.get('blog_title'))[:300],
                                 body=blog_body, extra=normalize_extra({'cards': out.get('blog_cards'),
                                                                       'cross': out.get('blog_cross')}, allowed))
        insta = _clean(out.get('instagram'))
        if insta:
            Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body=insta,
                                 extra=normalize_extra({'cards': out.get('instagram_cards')}, allowed))
        Draft.objects.create(proposal=p, channel=Draft.LINKS, body=links_text(book))
        liners = [x for x in (_clean(v) for v in (out.get('one_liners') or [])) if x and len(x) <= 20][:3]
        summary = _clean(out.get('summary_200'))
        if liners or summary:
            body = ['한 줄 소개', *[f'{i}. {x}' for i, x in enumerate(liners, 1)], '', '200자 소개', summary]
            Draft.objects.create(proposal=p, channel=Draft.SHORT, body='\n'.join(body).strip())
        outreach = [o for o in (out.get('outreach') or []) if isinstance(o, dict) and o.get('who')][:5]
        letter = out.get('letter') if isinstance(out.get('letter'), dict) else {}
        places = [f'{_clean(o["who"])} ― {_clean(o.get("why"))}' for o in outreach]
        if letter.get('body'):  # 보낼 곳·받는 곳은 올릴 글이 아니라 extra로(텔레그램에서는 편지 앞에 짧게 따로 보낸다)
            Draft.objects.create(proposal=p, channel=Draft.LETTER, title=_clean(letter.get('title'))[:300],
                                 body=_clean(letter['body']), extra={'places': places, 'to': _clean(letter.get('to'))})
        elif places:  # 보낼 글 없이 알릴 곳만 있으면 목록을 글로 둔다
            Draft.objects.create(proposal=p, channel=Draft.LETTER,
                                 body='\n'.join(['알리면 좋을 곳', *[f'· {x}' for x in places]]))
        recruit = out.get('recruit') if isinstance(out.get('recruit'), dict) else {}
        recruit_body = _recruit_body(recruit.get('body'), book, allowed)
        if recruit_body:
            Draft.objects.create(proposal=p, channel=Draft.RECRUIT, body=recruit_body,
                                 extra={'cards': recruit_cards(recruit.get('cards'), allowed)})
        questions = _editor_questions(out.get('editor_questions'), allowed)
        if questions:
            Draft.objects.create(proposal=p, channel=Draft.EDITOR, body=questions, extra={'form': 'questions'})
        notes = []
        bad = [q for d in p.drafts.all() for q in unverified_quotes(d.body, source)]
        if bad:
            notes.append('원문과 다른 인용이 있어요. 책에서 확인해 주세요: ' + ' / '.join(f'"{q}"' for q in bad))
        nums = foreign_numbers(' '.join(f'{d.title} {d.body} {" ".join(d.places)}'
                                        for d in p.drafts.exclude(channel=Draft.LINKS)), allowed)
        if nums:
            notes.append('자료에 없는 숫자가 있어요. 확인해 주세요: ' + ', '.join(nums))
        if notes:
            p.caution = '\n'.join([p.caution, *notes]) if p.caution else '\n'.join(notes)
            p.save(update_fields=['caution'])
    _clear_failure(book)  # 자동이든 /kit 으로 직접 만들었든, 성공하면 자동 만들기 실패 기록을 지운다
    return p


def buildable_books(today):
    """만들 차례인 책. 오늘 이미 실패했거나 3번 실패한 책은 빼서, 사이드카가 죽어도 10분마다 몇 분씩 묶이지 않게 한다."""
    failures = WorkerState.get(FAILURES_KEY) or {}
    out = []
    for book in pending_books(today):
        f = failures.get(str(book.id))
        if f and (f['day'] == today.isoformat() or f['count'] >= MAX_FAILURES):
            continue
        out.append(book)
    return out


def _record_failure(book, today, notify):
    failures = WorkerState.get(FAILURES_KEY) or {}
    count = failures.get(str(book.id), {}).get('count', 0) + 1
    failures[str(book.id)] = {'day': today.isoformat(), 'count': count}
    WorkerState.put(FAILURES_KEY, failures)
    if count == MAX_FAILURES:
        notify(f'⚠️ 『{book.title}』 홍보 묶음을 3번 만들지 못했어요. 필요하면 /kit {book.title[:12]} 로 직접 만들어 주세요')


def _clear_failure(book):
    failures = WorkerState.get(FAILURES_KEY) or {}
    if failures.pop(str(book.id), None) is not None:
        WorkerState.put(FAILURES_KEY, failures)


def build_pending(llm, today, posts, limit=1, notify=lambda text: None):
    """LLM 호출이 몇 분 걸리므로 한 번에 limit권만 만든다(그동안 워커가 텔레그램을 못 본다).
    실패는 책마다 적어 두고 다시 올린다(_guard가 하루 한 번 알린다)."""
    made = []
    for book in buildable_books(today)[:limit]:
        try:
            made.append(build_kit(book, llm, posts, today))
        except Exception:
            _record_failure(book, today, notify)
            raise
    return made
