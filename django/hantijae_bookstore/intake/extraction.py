import os
import shutil
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional

from intake.classify import FileEntry, classify, nfc
from intake.extract import best_local_text
from intake.images import to_jpeg
from intake.llm import Attachment, complete_json
from intake.prompts import EXTRACT_SYSTEM, build_extract_user

MAX_PDF_BYTES = 10 * 1024 * 1024  # 사이드카 첨부 한도(base64 14,000,000자 ≈ 원본 10.5MB)
MAX_3D_CANDIDATES = 4


class NoPressRelease(Exception):
    pass


class AmbiguousPressRelease(Exception):
    def __init__(self, candidates):
        super().__init__('최종 보도자료 후보가 여러 개입니다')
        self.candidates = candidates


@dataclass
class ExtractionResult:
    data: dict
    root: str
    press_release: str
    text_sources: List[str] = field(default_factory=list)
    front_cover: Optional[str] = None
    cover_3d: Optional[str] = None
    cover_3d_alternatives: List[str] = field(default_factory=list)
    source_text: str = ''
    source_quality: float = 0.0


def list_files(root):
    out = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.startswith('.'):
                continue
            full = os.path.join(dirpath, n)
            out.append(FileEntry(nfc(os.path.relpath(full, root)).replace(os.sep, '/'), os.path.getsize(full)))
    return sorted(out, key=lambda f: f.path)


def zip_member_name(info) -> Optional[str]:
    """zip 항목 이름을 복원한다. UTF-8 플래그(0x800) 없는 이름은 zipfile이 cp437로 읽어 깨지므로
    원래 바이트로 되돌려 UTF-8(macOS) → CP949(한국어 윈도우) 순으로 다시 해석한다.
    __MACOSX·AppleDouble(._*)·디렉터리·경로 탈출 항목은 None."""
    name = info.filename
    if not info.flag_bits & 0x800:
        raw = name.encode('cp437')
        for enc in ('utf-8', 'cp949'):
            try:
                name = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    name = nfc(name).replace('\\', '/')
    parts = [p for p in name.split('/') if p]
    if (name.endswith('/') or not parts or parts[0] == '__MACOSX' or parts[-1].startswith('._')
            or any(p in ('.', '..') for p in parts) or name.startswith('/')):
        return None
    return '/'.join(parts)


def _expand_zips(root, zips):
    for z in zips:
        target = os.path.join(root, os.path.splitext(z.path)[0])
        if os.path.isdir(target):
            continue
        with zipfile.ZipFile(os.path.join(root, z.path)) as zf:
            for info in zf.infolist():
                name = zip_member_name(info)
                if not name:
                    continue
                dest = os.path.join(target, *name.split('/'))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(info) as src, open(dest, 'wb') as out:
                    shutil.copyfileobj(src, out)


def run_extraction(root, client, categories, series):
    files = list_files(root)
    c = classify(files)
    if c.zips:
        _expand_zips(root, c.zips)
        c = classify(list_files(root))
    if c.ambiguous:
        raise AmbiguousPressRelease([f.path for f in c.ambiguous])
    if not c.press_release:
        raise NoPressRelease('보도자료 문서를 찾지 못했습니다')

    path = lambda f: os.path.join(root, f.path)  # noqa: E731
    text_sources = [path(f) for f in c.text_sources]
    source_text, quality, _ = best_local_text(text_sources)

    attachments, local_text = [], ''
    press_path = path(c.press_release)
    if c.press_release.ext == '.pdf' and os.path.getsize(press_path) <= MAX_PDF_BYTES:
        with open(press_path, 'rb') as f:
            attachments.append(Attachment('pdf', 'application/pdf', f.read(), c.press_release.name))
    else:
        local_text = source_text
    images = ([c.front_cover] if c.front_cover else []) + c.cover_3d[:MAX_3D_CANDIDATES]
    for img in images:
        side = 1200 if img is c.front_cover else 800
        attachments.append(Attachment('image', 'image/jpeg', to_jpeg(path(img), side), img.name))

    data = complete_json(client, EXTRACT_SYSTEM,
                         build_extract_user(categories, series, [i.name for i in images], local_text),
                         attachments)

    candidates = c.cover_3d[:MAX_3D_CANDIDATES]
    chosen = next((f for f in candidates if f.name == nfc(data.get('best_3d') or '')), None) or \
        (candidates[0] if candidates else None)
    return ExtractionResult(
        data=data, root=root, press_release=press_path, text_sources=text_sources,
        front_cover=path(c.front_cover) if c.front_cover else None,
        cover_3d=path(chosen) if chosen else None,
        cover_3d_alternatives=[path(f) for f in candidates],
        source_text=source_text, source_quality=quality,
    )
