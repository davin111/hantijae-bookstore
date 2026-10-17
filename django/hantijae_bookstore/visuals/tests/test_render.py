import tempfile
from pathlib import Path

from django.test import SimpleTestCase
from PIL import Image

from visuals.svg import validate_svg, rasterize
from visuals.render import render_packet
from visuals.policy import illustration_decision

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1350"><rect width="1080" height="1350" fill="#dde6df"/><path d="M0 1350 L540 600 L1080 1350Z" fill="#345648"/></svg>'


class SVGTest(SimpleTestCase):
    def test_valid_geometry_renders_exact_size(self):
        image = rasterize(validate_svg(SVG))
        self.assertEqual(image.size, (1080, 1350))
        self.assertEqual(image.getpixel((540, 1000))[:3], (52, 86, 72))

    def test_external_content_and_active_svg_are_rejected(self):
        for body in ('<script>alert(1)</script>', '<image href="https://example.com/a.png"/>',
                     '<use href="file:///etc/passwd"/>', '<foreignObject/>', '<text>가짜 인용</text>',
                     '<rect style="fill:url(https://example.com/a)"/>',
                     '<rect fill="url(https://example.com/a)"/>', '<animate/>', '<filter/>'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                validate_svg(SVG.replace('</svg>', body + '</svg>'))

    def test_resource_limits_and_entities_are_rejected(self):
        for svg in (SVG.replace('1080 1350', '99999999 99999999'),
                    SVG.replace('</svg>', '<rect/>' * 1501 + '</svg>'),
                    '<!DOCTYPE svg [<!ENTITY x "oops">]>' + SVG,
                    SVG.replace('M0 1350', 'M' + '1 1 ' * 30000),
                    SVG.replace('fill="#dde6df"', 'onload="alert(1)"')):
            with self.subTest(size=len(svg)), self.assertRaises(ValueError):
                validate_svg(svg)


class PolicyTest(SimpleTestCase):
    def test_decoration_and_missing_reason_do_not_generate(self):
        for value in ({}, {'needed': True, 'purpose': 'decoration', 'reason': '예뻐서', 'subject': '꽃'},
                      {'needed': True, 'purpose': 'theme', 'reason': '', 'subject': '산'}):
            self.assertIsNone(illustration_decision(value, sensitive=False, requested=['가을 산 풍경']))

    def test_real_documents_people_and_memorial_are_never_substituted(self):
        value = {'needed': True, 'purpose': 'theme', 'reason': '산과 계절이라는 글의 주제를 보여 준다', 'subject': '산'}
        for requested in (['책 표지 정면'], ['목차 면'], ['행사 현장 사진'], ['작가 얼굴 사진']):
            self.assertIsNone(illustration_decision(value, sensitive=False, requested=requested))
        self.assertIsNone(illustration_decision(value, sensitive=True, requested=['산 풍경']))
        self.assertIsNotNone(illustration_decision(value, sensitive=False, requested=['가을 산 풍경']))


class RenderTest(SimpleTestCase):
    def test_text_and_original_cover_make_publishable_pngs(self):
        with tempfile.TemporaryDirectory() as tmp:
            cover = Image.new('RGB', (600, 900), '#cc2233')
            cards = [{'kind': 'text', 'text': '나는 산속으로\n더 깊이 들어간다'},
                     {'kind': 'cover', 'text': '최정 시집'}]
            paths = render_packet(cards, {'cover': cover}, None, Path(tmp), title='한티재의 책')
            self.assertEqual(len(paths), 2)
            for path in paths:
                with Image.open(path) as image:
                    self.assertEqual((image.size, image.mode), ((1080, 1350), 'RGB'))
            with Image.open(paths[1]) as image:
                self.assertEqual(image.getpixel((540, 700)), (204, 34, 51))

    def test_text_overflow_fails_instead_of_silently_truncating(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            render_packet([{'kind': 'text', 'text': '아주 긴 한글 문장입니다. ' * 300}], {}, None, Path(tmp))

    def test_missing_original_is_not_replaced_with_generated_art(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            render_packet([{'kind': 'toc', 'text': '차례'}], {}, SVG.encode(), Path(tmp))

    def test_large_original_is_reduced_before_composition_without_changing_source(self):
        import io
        from visuals.assets import open_image
        data = io.BytesIO()
        with Image.new('RGB', (6000, 4000), '#334455') as image:
            image.save(data, 'PNG')
        result = open_image(data.getvalue())
        self.assertEqual(result.size, (1350, 900))
        self.assertEqual(result.getpixel((500, 500)), (51, 68, 85))
        with Image.open(io.BytesIO(data.getvalue())) as original:
            self.assertEqual(original.size, (6000, 4000))


class KindTest(SimpleTestCase):
    def test_title_text_card_with_screenshot_prohibition_is_still_text(self):
        from visuals.policy import card_kind
        self.assertEqual(card_kind('기사 제목을 글자로만 적은 카드(기사 화면 갈무리는 쓰지 않음)'), 'text')

    def test_korean_words_are_not_split_when_the_next_word_can_start_a_new_line(self):
        from visuals.render import lines_for, font
        text = '가을 문학 행사를 다룬 지역 기사에 이 시집이 나왔습니다'
        lines = lines_for(text, font(86, True), 928)
        self.assertEqual(' '.join(lines), text)
        self.assertTrue(any('지역' in line for line in lines))
        self.assertTrue(all(font(86, True).getlength(line) <= 928 for line in lines))
