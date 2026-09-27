"""목록 카드용 축소 표지. 원본 PNG가 1MB를 넘는 경우가 많아 휴대폰 목록에선 이걸 쓴다."""
import io
import logging

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image

log = logging.getLogger(__name__)
THUMB_MAX_SIDE = 480      # 카드 표시 폭 240px의 2배 밀도
THUMB_QUALITY = 82


def make_thumbnail_bytes(fileobj) -> bytes:
    with Image.open(fileobj) as im:
        if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
            rgba = im.convert('RGBA')
            flat = Image.new('RGB', rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.split()[-1])
        else:
            flat = im.convert('RGB')
        flat.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE))
        buf = io.BytesIO()
        flat.save(buf, 'JPEG', quality=THUMB_QUALITY, optimize=True, progressive=True)
        return buf.getvalue()


def refresh_cover_thumbnail(book) -> bool:
    """평면 표지로 썸네일을 만들어 저장한다. 실패해도 예외를 올리지 않는다 — 썸네일 때문에 책 저장이 막히면 안 된다."""
    try:
        with book.cover_image.open('rb') as fh:
            data = make_thumbnail_bytes(fh)
        book.cover_thumbnail.save('thumb.jpg', ContentFile(data), save=False)
        # save()를 다시 부르면 표지 변경 감지가 또 돈다 → 필드만 직접 갱신(updated_at도 건드리지 않음)
        # DB 오류(예: 락, 커넥션 끊김)도 여기서 잡아야 한다 — Book.save()는 transaction.atomic() 안에서
        # 호출될 수 있어서, 여기서 예외가 새어 나가면 책 저장 자체가 롤백된다.
        # savepoint로 감싸는 이유: .update()가 실패했을 때 이 savepoint까지만 되돌리고, 바깥(호출한 쪽의)
        # 트랜잭션은 계속 쓸 수 있는 상태로 남겨 둔다 — savepoint 없이 예외만 잡으면 바깥 트랜잭션이
        # 깨진 상태로 남아 이어지는 조회가 실패할 수 있다.
        with transaction.atomic():
            type(book).objects.filter(pk=book.pk).update(cover_thumbnail=book.cover_thumbnail.name)
    except Exception:
        log.exception('cover thumbnail failed for book %s', book.pk)
        return False
    return True
