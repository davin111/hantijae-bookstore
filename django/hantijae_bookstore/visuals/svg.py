"""Claude의 그림 코드를 외부 접근 없는 제한된 SVG로 검사한다. 한글은 여기서 그리지 않는다."""
import io
import math
import re

from defusedxml import ElementTree as ET
from PIL import Image

TAGS = {'svg', 'g', 'defs', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon',
        'linearGradient', 'radialGradient', 'stop'}
ATTRS = {'viewBox', 'width', 'height', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry',
         'd', 'points', 'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin',
         'opacity', 'fill-opacity', 'stroke-opacity', 'fill-rule', 'transform', 'id', 'offset',
         'stop-color', 'stop-opacity', 'gradientUnits', 'gradientTransform', 'fx', 'fy'}
NUMERIC = ATTRS - {'id', 'fill', 'stroke', 'stop-color', 'stroke-linecap', 'stroke-linejoin',
                   'fill-rule', 'gradientUnits'}
NUMBER = re.compile(r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?')


def validate_svg(text):
    text = text.strip()
    if text.startswith('```'):
        text = '\n'.join(text.splitlines()[1:-1]).strip()
    if len(text.encode()) > 100_000 or '<!' in text or '<?' in text:
        raise ValueError('SVG 크기 또는 선언 제한')
    try:
        root = ET.fromstring(text)
    except Exception as exc:
        raise ValueError('SVG 문법 오류') from exc
    ns = '{http://www.w3.org/2000/svg}'
    if root.tag not in ('svg', ns + 'svg') or root.get('viewBox') != '0 0 1080 1350':
        raise ValueError('SVG는 1080×1350 좌표만 허용')
    nodes = list(root.iter())
    if len(nodes) > 1200:
        raise ValueError('SVG 도형 수 초과')
    ids = {node.get('id') for node in nodes if node.get('id')}
    for node in nodes:
        tag = node.tag.removeprefix(ns)
        if tag not in TAGS or (node is not root and tag == 'svg') or (node.text or '').strip():
            raise ValueError('허용하지 않는 SVG 요소')
        for attr, value in node.attrib.items():
            if attr not in ATTRS or len(value) > 12_000:
                raise ValueError('허용하지 않는 SVG 속성')
            if attr == 'id' and not re.fullmatch(r'[a-zA-Z][\w-]{0,50}', value):
                raise ValueError('잘못된 SVG 식별자')
            if any(x in value.lower() for x in ('url(', 'href', '://', 'data:', 'file:')):
                m = re.fullmatch(r'url\(#([a-zA-Z][\w-]{0,50})\)', value)
                if attr not in ('fill', 'stroke') or not m or m[1] not in ids:
                    raise ValueError('SVG 외부 참조 금지')
            if attr in NUMERIC:
                numbers = NUMBER.findall(value)
                if len(numbers) > 3000 or any(not math.isfinite(float(n)) or abs(float(n)) > 20_000 for n in numbers):
                    raise ValueError('SVG 좌표/복잡도 제한')
    def depth(node, level=0):
        if level > 12:
            raise ValueError('SVG 중첩 제한')
        for child in node:
            depth(child, level + 1)
    depth(root)
    root.set('width', '1080')
    root.set('height', '1350')
    return ET.tostring(root, encoding='utf-8')


def rasterize(svg):
    import cairosvg
    # 검증을 거치지 않은 호출도 안전하게 처리한다. use/image/CSS/외부 URL은 전부 금지.
    clean = validate_svg(svg.decode() if isinstance(svg, bytes) else svg)
    data = cairosvg.svg2png(bytestring=clean, output_width=1080, output_height=1350, unsafe=False)
    return Image.open(io.BytesIO(data)).convert('RGB')
