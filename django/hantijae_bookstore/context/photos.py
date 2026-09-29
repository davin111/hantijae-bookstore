"""방에 올린 사진의 글자를 LLM으로 옮겨 적어 기록(media_text)에 넣는다.

계기를 뽑는 호출과 따로 부르는 이유: 같은 호출이 사진을 보며 요약과 옮긴 글을 함께 쓰면, 잘못 읽은 숫자가 양쪽에
똑같이 들어가 숫자·날짜 검사가 무력해진다. 옮겨 적기만 하는 호출은 '날짜를 찾아야 한다'는 압박이 없다.
LLM 호출(ask)과 텔레그램 내려받기(download)는 부르는 쪽이 넘긴다 — context 는 intake·marketing 을 import 하지 않는다.
"""
import io
import os
import tempfile

from django.db.models import F
from PIL import Image, ImageOps

from context.models import ContextEntry
from context.redact import redact

BATCH, LIMIT, MAX_SIDE, KEEP, MAX_TRIES = 8, 24, 1600, 3000, 3
MAX_PIXELS = 40_000_000  # 이보다 큰 그림은 풀지 않는다(1GB 서버). JPEG은 draft 로 줄여 연다
UNREADABLE = '[읽지 못함]'
KINDS = ('주문 화면', '포스터', '책', '행사 사진', '문서', '기타')

PHOTO_SYSTEM = f"""당신은 사진 속 글자를 그대로 옮겨 적는 도우미입니다. 웹 검색·웹 페치 도구를 쓰지 말고 첨부한 사진만 보세요.
- 사진마다 보이는 글자를 줄바꿈까지 그대로 옮겨 적습니다. 요약하거나 고치지 않습니다.
- 숫자·날짜·시각·금액은 보이는 그대로 적고 절대 고치거나 추측하지 않습니다. 읽기 어려운 글자는 [?]로 둡니다.
- kind는 {', '.join(KINDS)} 가운데 하나입니다.
- 글자가 거의 없으면 text는 빈 문자열로 두고 desc에 무엇이 찍혔는지 한 줄로 씁니다(사람이 누구인지는 쓰지 않습니다).
JSON 객체 하나만 출력하세요:
{{"items": [{{"n": 1, "kind": "포스터", "text": "사진 속 글자 그대로", "desc": ""}}]}}"""


def pending(limit=LIMIT):
    """아직 읽지 않은 사진(사진 메시지, 또는 jpg·png·webp 파일). 오래된 것부터."""
    qs = (ContextEntry.objects.filter(forgotten=False, media_read_at__isnull=True, media__in=('photo', 'document'))
          .exclude(file_id='').order_by('at', 'id'))
    return [e for e in qs if e.is_image][:limit]


def shrink(data):
    """긴 변 1600px 이하 JPEG로. 휴대폰 사진의 회전 정보(EXIF)를 먼저 반영한다."""
    img = Image.open(io.BytesIO(data))
    img.draft('RGB', (MAX_SIDE, MAX_SIDE))  # JPEG은 디코딩 단계에서 줄여 메모리를 아낀다(다른 형식은 그대로)
    if img.width * img.height > MAX_PIXELS:
        raise ValueError(f'too large: {img.width}x{img.height}')
    img = ImageOps.exif_transpose(img).convert('RGB')
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=85)
    return out.getvalue()


def _user(n):
    return f'사진 {n}장이 첨부 순서대로 1번부터 {n}번입니다. 사진마다 글자를 옮겨 적어 주세요.'


def _text(item):
    kind = str(item.get('kind') or '기타').strip()[:10]
    body = str(item.get('text') or '').strip() or str(item.get('desc') or '').strip()
    return f'[{kind}] {body}'.strip()


def _numbered(out):
    """응답 항목을 번호(1부터)로. LLM이 0부터 매겼으면 한 칸 민다."""
    by_n = {}
    for item in (out or {}).get('items') or []:
        if isinstance(item, dict):
            try:
                by_n[int(item.get('n'))] = item
            except (TypeError, ValueError):
                continue
    if by_n and min(by_n) == 0:
        by_n = {n + 1: item for n, item in by_n.items()}
    return by_n


def _failed(entries, now):
    """읽기 실패를 센다. 3번째 실패면 '[읽지 못함]'으로 적어 더 시도하지 않는다(한 장이 매일 막지 않게)."""
    ContextEntry.objects.filter(pk__in=[e.pk for e in entries]).update(media_read_tries=F('media_read_tries') + 1)
    for e in ContextEntry.objects.filter(pk__in=[e.pk for e in entries], media_read_tries__gte=MAX_TRIES):
        _save(e, UNREADABLE, now)


def _save(entry, text, now):
    masked, _ = redact(text)
    ContextEntry.objects.filter(pk=entry.pk, forgotten=False).update(media_text=masked[:KEEP], media_read_at=now)


def _load(entry, download):
    with tempfile.TemporaryDirectory() as tmp:
        path = download(entry.file_id, os.path.join(tmp, 'photo'))
        with open(path, 'rb') as fh:
            return shrink(fh.read())


def read_pending(ask, download, now, limit=LIMIT):
    """ask(system, user, images: list[bytes]) -> dict, download(file_id, path) -> path. 읽은(또는 못 읽음으로 적은) 수.

    내려받기·그림 열기 실패는 '[읽지 못함]'으로 적고 끝낸다. 묶음 호출이 실패하면 한 장씩 다시 부르고, 그래도 실패한
    사진은 실패 횟수만 센다(3번이면 '[읽지 못함]'). 한 장도 못 읽으면 예외를 올린다(다음 날 다시).
    """
    done = 0
    todo = pending(limit)
    for start in range(0, len(todo), BATCH):
        batch, images = [], []
        for e in todo[start:start + BATCH]:
            try:
                images.append(_load(e, download))
                batch.append(e)
            except Exception:
                _save(e, UNREADABLE, now)
                done += 1
        if not batch:
            continue
        try:
            by_n = _numbered(ask(PHOTO_SYSTEM, _user(len(batch)), images))
        except Exception:
            done += _one_by_one(ask, batch, images, now)  # 한 장 때문에 묶음 전체가 막히지 않게 한 장씩 다시
            continue
        for n, e in enumerate(batch, 1):
            _save(e, _text(by_n[n]) if n in by_n else UNREADABLE, now)
            done += 1
    return done


def _one_by_one(ask, batch, images, now):
    """묶음이 실패했을 때 한 장씩. 모두 실패하면(사이드카가 안 되는 날) 실패만 세고 예외를 올린다."""
    done, failed, last = 0, [], None
    for e, image in zip(batch, images):
        try:
            by_n = _numbered(ask(PHOTO_SYSTEM, _user(1), [image]))
        except Exception as err:
            failed.append(e)
            last = err
            continue
        _save(e, _text(by_n[1]) if 1 in by_n else UNREADABLE, now)
        done += 1
    if failed:
        _failed(failed, now)
    if done == 0 and last is not None:
        raise last
    return done
