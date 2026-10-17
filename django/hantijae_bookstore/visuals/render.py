"""검증된 글은 글꼴로, 표지/목차는 원본으로 배치한다. 모델이 문구를 다시 그리지 않는다."""
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from visuals.svg import rasterize

WIDTH, HEIGHT = 1080, 1350
PAPER, INK, ACCENT = '#F5F1E7', '#243B34', '#86734D'
FONTS = Path(__file__).parent / 'assets' / 'fonts'


def font(size, serif=False):
    return ImageFont.truetype(str(FONTS / ('NanumMyeongjo-Regular.ttf' if serif else 'NanumGothic-Bold.ttf')), size)


def lines_for(text, face, width):
    lines = []
    for paragraph in text.split('\n'):
        current = ''
        for word in paragraph.split():
            candidate = current + ' ' + word if current else word
            if face.getlength(candidate) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = ''
                # 공백 없는 긴 낱말만 글자 단위로 나눈다. 일반 단어는 다음 줄에 온전히 놓는다.
                for char in word:
                    if current and face.getlength(current + char) > width:
                        lines.append(current)
                        current = ''
                    current += char
        lines.append(current)
    return lines


def text_block(draw, text, box, *, max_size=80, min_size=40, serif=True, color=INK):
    x, y, width, height = box
    for size in range(max_size, min_size - 1, -2):
        face = font(size, serif)
        lines = lines_for(text, face, width)
        step = round(size * 1.55)
        if len(lines) * step <= height:
            for i, line in enumerate(lines):
                draw.text((x, y + i * step), line, fill=color, font=face, anchor='lt')
            return
    raise ValueError('카드 글이 영역을 넘습니다. 원문을 자르지 않습니다.')


def render_packet(cards, assets, svg, output_dir, title='한티재의 책'):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not 1 <= len(cards) <= 4:
        raise ValueError('카드는 1~4장')
    paths = []
    for index, card in enumerate(cards, 1):
        kind, text = card['kind'], card['text']
        canvas = Image.new('RGB', (WIDTH, HEIGHT), PAPER)
        if kind == 'illustration':
            if not svg:
                raise ValueError('일러스트 없음')
            canvas = rasterize(svg)
            # 상단 문구는 충분한 단색 여백에 합성한다. 그림은 하단에 보존한다.
            ImageDraw.Draw(canvas).rectangle((0, 0, WIDTH, 470), fill=PAPER)
        draw = ImageDraw.Draw(canvas)
        draw.text((76, 66), '한티재의 책', font=font(27), fill=ACCENT)
        draw.line((76, 122, 1004, 122), fill='#D7CDBB', width=2)
        if kind in ('cover', 'toc', 'inside', 'photo'):
            original = assets.get(kind)
            if original is None:
                raise ValueError('원본 자료 없음: ' + kind)
            image = ImageOps.exif_transpose(original).convert('RGB')
            fitted = ImageOps.contain(image, (830, 855), Image.Resampling.LANCZOS)
            x, y = (WIDTH - fitted.width) // 2, 162 + (855 - fitted.height) // 2
            canvas.paste(fitted, (x, y))
            caption = re.sub(r'(』)\s+', r'\1\n', text, count=1) if kind == 'cover' else text
            text_block(draw, caption, (76, 1053, 928, 190), max_size=51, min_size=34)
        elif kind == 'illustration':
            text_block(draw, text, (76, 172, 928, 275), max_size=68, min_size=40)
        elif kind == 'text':
            text_block(draw, text, (76, 300, 928, 790), max_size=86, min_size=40)
        else:
            raise ValueError('알 수 없는 카드 유형')
        # 게시용 이미지에 내부 설명이나 파일명은 넣지 않는다.
        draw.rectangle((0, 1260, WIDTH, HEIGHT), fill=PAPER)
        draw.text((76, 1292), 'AI 도형 일러스트' if kind == 'illustration' else '도서출판 한티재',
                  font=font(23), fill=ACCENT)
        draw.text((1004, 1292), f'{index:02} / {len(cards):02}', font=font(23), fill=ACCENT, anchor='rt')
        path = output_dir / f'{index:02}.png'
        canvas.save(path, 'PNG')
        paths.append(path)
    return paths
