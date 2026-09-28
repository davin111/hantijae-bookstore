"""새 책 홍보 묶음: 공개된 지 60일 안 된 책마다 초안 한 벌을 만든다(LLM 1회). 보내기는 bot.py가 한다."""
from datetime import timedelta

from django.conf import settings

from books.models import Book
from intake.llm import complete_json
from marketing.hooks import upcoming
from marketing.models import BookProfile, Draft, Proposal
from marketing.prompts import KIT_SYSTEM, build_kit_user
from marketing.text import fix_title_marks, foreign_numbers, title_key, unverified_quotes
from web.presenters import UNTRUSTED_SHORTLINK, authors_of, credit_line, store_links

NEW_BOOK_DAYS = 60
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


def build_kit(book, llm, posts, today):
    exists = blog_has(book, posts)
    hooks = [f'{on.month}월 {on.day}일 {h.name}' + (' (추모 성격)' if h.memorial else '')
             for h, on in upcoming(today, 45) if book in h.books.all()]
    out = complete_json(llm, KIT_SYSTEM, build_kit_user(book, credit_line(authors_of(book)), today, exists, hooks))
    p = Proposal.objects.create(kind=Proposal.KIT, book=book, headline=f'『{book.title}』 홍보 자료',
                                caution=_clean(out.get('caution')),
                                extra={'blog_exists': exists, 'missing_stores': missing_stores(book)})
    blog_body = _clean(out.get('blog_body'))
    if not exists and blog_body:
        Draft.objects.create(proposal=p, channel=Draft.BLOG, title=_clean(out.get('blog_title')), body=blog_body)
    insta = _clean(out.get('instagram'))
    if insta:
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body=insta)
    Draft.objects.create(proposal=p, channel=Draft.LINKS, body=links_text(book))
    liners = [x for x in (_clean(v) for v in (out.get('one_liners') or [])) if x and len(x) <= 20][:3]
    summary = _clean(out.get('summary_200'))
    if liners or summary:
        body = ['한 줄 소개', *[f'{i}. {x}' for i, x in enumerate(liners, 1)], '', '200자 소개', summary]
        Draft.objects.create(proposal=p, channel=Draft.SHORT, body='\n'.join(body).strip())
    outreach = [o for o in (out.get('outreach') or []) if isinstance(o, dict) and o.get('who')][:5]
    letter = out.get('letter') if isinstance(out.get('letter'), dict) else {}
    if outreach or letter.get('body'):
        lines = ['알리면 좋을 곳'] + [f'· {_clean(o["who"])} ― {_clean(o.get("why"))}' for o in outreach]
        if letter.get('body'):
            lines += ['', f'보낼 글 ({_clean(letter.get("to"))})', f'제목: {_clean(letter.get("title"))}', '',
                      _clean(letter['body'])]
        Draft.objects.create(proposal=p, channel=Draft.LETTER, body='\n'.join(lines))
    source = '\n'.join([book.description or '', book.short_description or ''])
    notes = []
    bad = [q for d in p.drafts.all() for q in unverified_quotes(d.body, source)]
    if bad:
        notes.append('원문과 다른 인용이 있어요. 책에서 확인해 주세요: ' + ' / '.join(f'"{q}"' for q in bad))
    allowed = [source, book.title, book.subtitle or '', str(book.page_count), str(book.full_price),
               book.published_date.isoformat(), '200자 소개']
    nums = foreign_numbers(' '.join(f'{d.title} {d.body}' for d in p.drafts.exclude(channel=Draft.LINKS)), allowed)
    if nums:
        notes.append('자료에 없는 숫자가 있어요. 확인해 주세요: ' + ', '.join(nums))
    if notes:
        p.caution = '\n'.join([p.caution, *notes]) if p.caution else '\n'.join(notes)
        p.save(update_fields=['caution'])
    return p


def build_pending(llm, today, posts, limit=1):
    """LLM 호출이 몇 분 걸리므로 한 번에 limit권만 만든다(그동안 워커가 텔레그램을 못 본다)."""
    return [build_kit(book, llm, posts, today) for book in pending_books(today)[:limit]]
