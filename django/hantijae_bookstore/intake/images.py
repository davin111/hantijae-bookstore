from io import BytesIO

from PIL import Image


def to_jpeg(path: str, max_side: int, quality: int = 88) -> bytes:
    with Image.open(path) as im:
        if im.format == 'JPEG':
            im.draft('RGB', (max_side, max_side))   # 디코드 단계에서 1/2·1/4·1/8로 줄여 메모리를 아낀다
        if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
            im = im.convert('RGBA')                  # 투명 영역을 그냥 RGB로 바꾸면 검은색이 된다 → 흰 배경에 합성
            im = Image.alpha_composite(Image.new('RGBA', im.size, (255, 255, 255, 255)), im)
        im = im.convert('RGB')                       # CMYK 등 정리
        im.thumbnail((max_side, max_side))
        buf = BytesIO()
        im.save(buf, 'JPEG', quality=quality, optimize=True)
        return buf.getvalue()
