from io import BytesIO

from PIL import Image


def to_jpeg(path: str, max_side: int, quality: int = 88) -> bytes:
    with Image.open(path) as im:
        im = im.convert('RGB')          # PNG 투명도·CMYK 제거
        im.thumbnail((max_side, max_side))
        buf = BytesIO()
        im.save(buf, 'JPEG', quality=quality, optimize=True)
        return buf.getvalue()
