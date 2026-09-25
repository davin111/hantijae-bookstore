import unicodedata

from django.test import SimpleTestCase

from intake.classify import FileEntry, classify


def entries(*paths):
    return [FileEntry(p) for p in paths]


RAINBOW = entries(
    '보도자료_무지개를변호하다.hwp', '무지개를변호하다_입체 그림자.jpeg', '박한희(출판용).jpg',
    '보도자료_무지개를변호하다.pdf', '무지개를변호하다_입체.jpeg',
    '무지개를변호하다_미리보기/무지개를변호하다_뒷날개.jpg', '무지개를변호하다_미리보기/무지개를변호하다_앞표지.jpg',
    '무지개를변호하다_미리보기/무지개를변호하다_본문-1.jpg', '무지개를변호하다_미리보기/무지개를변호하다_책등.jpg',
)


class ClassifyTest(SimpleTestCase):
    def test_2026_template_folder(self):
        c = classify(RAINBOW)
        self.assertEqual(c.press_release.path, '보도자료_무지개를변호하다.pdf')
        self.assertEqual([f.path for f in c.text_sources], ['보도자료_무지개를변호하다.hwp', '보도자료_무지개를변호하다.pdf'])
        self.assertEqual(c.front_cover.path, '무지개를변호하다_미리보기/무지개를변호하다_앞표지.jpg')
        self.assertEqual([f.path for f in c.cover_3d],
                         ['무지개를변호하다_입체.jpeg', '무지개를변호하다_입체 그림자.jpeg'])

    def test_drafts_and_old_versions_are_excluded(self):
        c = classify(entries('보도자료_무궁화호를위하여.pdf', '보도자료_초안_저자수정.hwpx', '보도자료_무궁화호를위하여.hwp',
                             '보도자료_초안.hwp', '무궁화호를위하여_입체.jpg'))
        self.assertEqual(c.press_release.path, '보도자료_무궁화호를위하여.pdf')
        c = classify(entries('보도자료_내란앞에서.pdf', '보도자료_목차 수정 전.hwp', '보도자료_내란앞에서.hwp'))
        self.assertEqual(c.press_release.path, '보도자료_내란앞에서.pdf')

    def test_prefixed_name_wins_over_other_orgs_version(self):
        c = classify(entries('10월문학회 보도자료_시월,곡비의노래.hwp', '보도자료_시월,곡비의노래.hwpx',
                             '보도자료_시월,곡비의노래.pdf', '시월,곡비의노래_입체북_정사각.jpg',
                             '시월,곡비의노래_입체북_그림자.jpg', '시월,곡비의노래_입체북.jpg'))
        self.assertEqual(c.press_release.path, '보도자료_시월,곡비의노래.pdf')
        self.assertEqual([f.path for f in c.text_sources], ['보도자료_시월,곡비의노래.hwpx', '보도자료_시월,곡비의노래.pdf'])
        self.assertEqual(c.cover_3d[0].path, '시월,곡비의노래_입체북.jpg')

    def test_base_stem_wins_over_variants(self):
        c = classify(entries('보도자료_헌법개정(프린트용).hwp', '보도자료_헌법개정.hwp', '헌법개정_입체표지.jpg'))
        self.assertEqual(c.press_release.path, '보도자료_헌법개정.hwp')

    def test_unrelated_stems_are_ambiguous(self):
        c = classify(entries('보도자료_가나다.pdf', '보도자료_라마바.pdf'))
        self.assertIsNone(c.press_release)
        self.assertEqual(len(c.ambiguous), 2)

    def test_front_cover_fallbacks(self):
        c = classify(entries('보도자료_지방자치새로고침.hwp', '지방자치_표1.jpg', '지방자치_입체표지.jpg',
                             '2017-9-5 보도자료 초안.hwp', '지방자치새로고침_미리보기.zip'))
        self.assertEqual(c.front_cover.path, '지방자치_표1.jpg')
        self.assertEqual(c.press_release.path, '보도자료_지방자치새로고침.hwp')
        self.assertEqual([z.path for z in c.zips], ['지방자치새로고침_미리보기.zip'])
        c = classify(entries('보도자료_x.pdf', '남북신통상_표지(띠지).jpg', '남북신통상_표지.jpg', '남북신통상_입체표지.jpg'))
        self.assertEqual(c.front_cover.path, '남북신통상_표지.jpg')

    def test_preview_front_cover_beats_top_level(self):
        c = classify(entries('보도자료_내란앞에서.pdf', '내란앞에서_앞표지.jpeg', '내란앞에서_미리보기/내란앞에서_앞표지.jpeg',
                             '내란앞에서_입체북_여백많게.png', '내란앞에서_입체.jpeg'))
        self.assertEqual(c.front_cover.path, '내란앞에서_미리보기/내란앞에서_앞표지.jpeg')
        self.assertEqual(c.cover_3d[0].path, '내란앞에서_입체.jpeg')

    def test_nfd_filenames_are_normalized(self):
        nfd = [FileEntry(unicodedata.normalize('NFD', f.path)) for f in RAINBOW]
        c = classify(nfd)
        self.assertEqual(c.press_release.path, '보도자료_무지개를변호하다.pdf')
        self.assertEqual(c.front_cover.path, '무지개를변호하다_미리보기/무지개를변호하다_앞표지.jpg')

    def test_half_title_page_is_not_a_cover(self):
        c = classify(entries('보도자료_x.pdf', '개방명부비례대표제_약표지.jpg'))
        self.assertIsNone(c.front_cover)   # 약표지(반표제지)는 표지가 아니다
        c = classify(entries('보도자료_x.pdf', 'x_약표지.jpg', 'x_표지.jpg'))
        self.assertEqual(c.front_cover.path, 'x_표지.jpg')
