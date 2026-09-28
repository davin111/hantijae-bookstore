"""기념일 달력. 초기 목록은 2026-09-28 사이트 도서 목록에 맞춘 것이고, 이후는 관리자가 /hook 으로 더한다."""
from books.models import Book
from marketing.models import HookDate
from marketing.text import title_key

# (월, 일, 이름, 추모 성격, 책 제목들, 메모)
SEED = [
    (3, 8, '세계 여성의 날', False, ['우리 힘세고 사나운 용기', '전환의 시대, 지역과 여성에서 길을 찾다'], ''),
    (3, 11, '후쿠시마 원전 사고', True, ['한국탈핵', '탈핵 탈송전탑 원정대', '기후위기와 탈핵'], ''),
    (4, 16, '세월호 참사', True, ['잊지 않고 있어요, 그날의 약속'], ''),
    (4, 22, '지구의 날', False, ['기후위기 과학특강 : “도와줘요, 기후 박사!”', '기후정의', '1.5 : 그레타 툰베리와 함께'], ''),
    (5, 1, '노동절', False, ['태일과 함께 그늘을 걷다', '밥은 먹고 다니냐는 말'], ''),
    (5, 17, '국제 성소수자 혐오 반대의 날', False, ['웰컴 투 레인보우', '커밍아웃 스토리', '퀴어 디플로머시'], ''),
    (6, 1, '프라이드 먼스 시작', False, ['퀴어문화축제 방해 잔혹사', '성서, 퀴어를 옹호하다', '무지개를 변호하다'], ''),
    (6, 5, '세계 환경의 날', False, ['우리 힘세고 사나운 용기', '기후정의의 말들', '생태민주주의'], ''),
    (7, 17, '제헌절', False, ['내란 앞에서', '인권이란 무엇인가', '헌법개정'], '『내란 앞에서』 출간일'),
    (10, 1, '대구 10월항쟁', True, ['시월, 곡비의 노래'], '1946년'),
    (10, 9, '한글날', False, ['글쓰기의 태도', '하루 30분 글쓰기 훈련법'], ''),
    (10, 11, '커밍아웃의 날', False, ['커밍아웃 스토리', '웰컴 투 레인보우', '무지개를 변호하다'], ''),
    (10, 16, '세계 식량의 날', False, ['밥은 먹고 다니냐는 말', '소농, 문명의 뿌리', '밥상의 전환', '비아캄페시나'], ''),
    (11, 1, '가을철 산불조심기간 시작', False, ['나는 산속으로 더 깊이 들어간다'], '산림청이 해마다 앞당길 수 있음(2025년은 10/20)'),
    (11, 13, '전태일 기일', True, ['태일과 함께 그늘을 걷다'], '1970년'),
    (11, 20, '트랜스젠더 추모의 날', True, ['무지개를 변호하다'], ''),
    (12, 3, '12·3 비상계엄', False, ['내란 앞에서'], '분노보다 성찰의 결로'),
    (12, 10, '세계 인권의 날', False, ['인권이란 무엇인가', '인권 세미나', '퀴어 디플로머시'], ''),
]


def _books_by_key():
    return {title_key(b.title): b for b in Book.objects.all()}


def _link(hook, titles, books):
    missing = []
    for t in titles:
        b = books.get(title_key(t))
        if b:
            hook.books.add(b)
        else:
            missing.append(t)
    return missing


def seed():
    books, created, missing = _books_by_key(), 0, []
    for month, day, name, memorial, titles, note in SEED:
        hook, made = HookDate.objects.get_or_create(name=name, month=month, day=day,
                                                    defaults={'memorial': memorial, 'note': note})
        created += made
        missing += _link(hook, titles, books)
    return created, missing


def add_hook(month, day, name, titles):
    hook, _ = HookDate.objects.get_or_create(name=name, month=month, day=day)
    return hook, _link(hook, titles, _books_by_key())


def upcoming(today, days):
    out = []
    for hook in HookDate.objects.prefetch_related('books'):
        on = hook.next_on(today)
        if on and (on - today).days <= days:
            out.append((hook, on))
    return sorted(out, key=lambda x: (x[1], x[0].id))
