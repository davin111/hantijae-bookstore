"""목록 카드용 축소 표지. 원본 PNG가 1MB를 넘는 경우가 많아 휴대폰 목록에선 이걸 쓴다."""
import io
import logging

from django.core.files.base import ContentFile
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
    except Exception:
        log.exception('cover thumbnail failed for book %s', book.pk)
        return False
    # save()를 다시 부르면 표지 변경 감지가 또 돈다 → 필드만 직접 갱신(updated_at도 건드리지 않음)
    type(book).objects.filter(pk=book.pk).update(cover_thumbnail=book.cover_thumbnail.name)
    return True
