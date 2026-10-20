"""기능이 다른 카드에 서로 다른 위계를 준다. 글·표지 원본은 자르지 않는다."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from visuals.render import text_block, WIDTH, HEIGHT

PAPER, INK, BLUE = '#F5F1E7', '#233C48', '#486C83'


def render_editorial(cards, assets, output, title):
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, card in enumerate(cards, 1):
        layout = card['layout']
        dark = layout == 'quote'
        canvas = Image.new('RGB', (WIDTH, HEIGHT), BLUE if dark else PAPER)
        draw = ImageDraw.Draw(canvas)
        ink = '#FFFFFF' if dark else INK
        text_block(draw, title, (76, 54, 928, 65), max_size=28, min_size=20, serif=False, color=ink)
        if layout == 'opening':
            text_block(draw, card['heading'], (76, 220, 928, 420), max_size=92, min_size=64, serif=False, color=INK)
            draw.rectangle((0, 730, WIDTH, 1250), fill=BLUE)
            text_block(draw, card['body'], (76, 790, 928, 370), max_size=52, min_size=44, serif=False, color='#FFFFFF')
        elif layout == 'detail':
            text_block(draw, card['heading'], (76, 190, 928, 290), max_size=72, min_size=52, serif=False, color=INK)
            draw.line((76, 540, 1004, 540), fill=BLUE, width=6)
            text_block(draw, card['body'], (76, 620, 928, 565), max_size=56, min_size=44, serif=False, color=INK)
        elif layout == 'quote':
            text_block(draw, card['heading'], (76, 185, 928, 195), max_size=44, min_size=36, serif=False, color=ink)
            text_block(draw, card['body'], (76, 445, 928, 610), max_size=68, min_size=46, serif=True, color=ink)
            text_block(draw, card['credit'], (76, 1120, 928, 105), max_size=32, min_size=28, serif=False, color=ink)
        elif layout == 'cover':
            if 'cover' not in assets:
                raise ValueError('표지 원본 없음')
            im = ImageOps.contain(assets['cover'], (680, 710), Image.Resampling.LANCZOS)
            canvas.paste(im, ((WIDTH-im.width)//2, 160+(710-im.height)//2))
            text_block(draw, card['heading'], (76, 900, 928, 155), max_size=54, min_size=42, serif=False, color=INK)
            text_block(draw, card['body'], (76, 1090, 928, 160), max_size=40, min_size=34, serif=False, color=INK)
        else:
            raise ValueError('지원하지 않는 편집 구성')
        text_block(draw, '도서출판 한티재', (76, 1280, 928, 48), max_size=24, min_size=24, serif=False, color=ink)
        path = folder / f'{i:02}.png'
        canvas.save(path, 'PNG')
        paths.append(path)
    return paths
