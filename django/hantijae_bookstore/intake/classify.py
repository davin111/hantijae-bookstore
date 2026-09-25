"""보도자료 폴더의 파일 목록에서 최종 보도자료·앞표지·입체 표지 후보를 고른다 (I/O 없음)."""
import os
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

DOC_RANK = {'.pdf': 0, '.hwpx': 1, '.hwp': 2, '.docx': 3}      # 사이드카 전송 우선순위
TEXT_RANK = {'.hwpx': 0, '.hwp': 1, '.docx': 2, '.pdf': 3}     # 로컬 원문 추출 우선순위 (문단 보존 순)
IMAGE_EXTS = {'.jpg', '.jpeg', '.png'}
EXCLUDE_WORDS = ('초안', '수정 전', '수정전', '요약')
PENALTY_3D = ('띠지', '그림자', '배경', '정사각', '여백', '투명', '블로그', '웹용', '세종')


def nfc(s: str) -> str:
    return unicodedata.normalize('NFC', s)


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int = 0

    @property
    def name(self) -> str:
        return nfc(os.path.basename(self.path))

    @property
    def stem(self) -> str:
        return os.path.splitext(self.name)[0]

    @property
    def ext(self) -> str:
        return os.path.splitext(self.name)[1].lower()

    @property
    def in_preview(self) -> bool:
        return '미리보기' in nfc(os.path.dirname(self.path))


@dataclass
class Classification:
    press_release: Optional[FileEntry]
    text_sources: List[FileEntry] = field(default_factory=list)
    ambiguous: List[FileEntry] = field(default_factory=list)
    front_cover: Optional[FileEntry] = None
    cover_3d: List[FileEntry] = field(default_factory=list)
    zips: List[FileEntry] = field(default_factory=list)


def _normalized(files: Sequence[FileEntry]) -> List[FileEntry]:
    return [FileEntry(nfc(f.path), f.size) for f in files]


def _pick_press_release(files: List[FileEntry]):
    docs = [f for f in files if f.ext in DOC_RANK and '보도자료' in f.name and not f.in_preview
            and not any(w in f.name for w in EXCLUDE_WORDS)]
    prefixed = [f for f in docs if f.name.startswith('보도자료_')]
    pool = prefixed or docs
    if not pool:
        return None, [], []
    stems = sorted({f.stem for f in pool}, key=len)
    base = stems[0]
    if len(stems) > 1 and not all(s.startswith(base) for s in stems):
        return None, [], pool
    same = [f for f in pool if f.stem == base]
    press = min(same, key=lambda f: DOC_RANK[f.ext])
    text_sources = sorted(same, key=lambda f: TEXT_RANK[f.ext])
    return press, text_sources, []


def _pick_front_cover(files: List[FileEntry]) -> Optional[FileEntry]:
    images = [f for f in files if f.ext in IMAGE_EXTS and '입체' not in f.name]
    no_band = lambda f: '띠지' not in f.name  # noqa: E731
    tiers = [
        lambda f: f.in_preview and '앞표지' in f.name,
        lambda f: '앞표지' in f.name,
        lambda f: '표1' in f.name and no_band(f),
        lambda f: '표1' in f.name,
        lambda f: '표지' in f.name and no_band(f) and not any(w in f.name for w in ('뒤표지', '약표지', '책등', '날개')),
    ]
    for tier in tiers:
        matched = [f for f in images if tier(f)]
        if matched:
            return sorted(matched, key=lambda f: (not no_band(f), len(f.name)))[0]
    return None


def _rank_3d(files: List[FileEntry]) -> List[FileEntry]:
    cands = [f for f in files if f.ext in IMAGE_EXTS and '입체' in f.name]
    return sorted(cands, key=lambda f: (sum(w in f.name for w in PENALTY_3D), len(f.name), f.path))


def classify(files: Sequence[FileEntry]) -> Classification:
    files = _normalized(files)
    press, text_sources, ambiguous = _pick_press_release(files)
    return Classification(
        press_release=press,
        text_sources=text_sources,
        ambiguous=ambiguous,
        front_cover=_pick_front_cover(files),
        cover_3d=_rank_3d(files),
        zips=[f for f in files if f.ext == '.zip'],
    )
