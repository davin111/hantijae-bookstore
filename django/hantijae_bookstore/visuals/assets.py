import hashlib
import io
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps

from visuals.models import ApprovedImage

MAX_BYTES, MAX_PIXELS = 20_000_000, 24_000_000


def root():
    return Path(getattr(settings, 'VISUALS_ROOT', Path(settings.INTAKE['WORK_DIR']) / 'visuals'))


def open_image(data):
    if len(data) > MAX_BYTES:
        raise ValueError('원본 이미지 파일이 너무 큽니다')
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > MAX_PIXELS:
            raise ValueError('원본 이미지 해상도가 너무 큽니다')
        # 큰 원본의 전체 크기 RGB/EXIF 복사본을 만들기 전에 작업용 크기로 줄인다.
        # JPEG는 디코더 자체도 축소한다. 보관한 원본 파일은 수정하지 않는다.
        image.draft('RGB', (1080, 1350))
        image.thumbnail((1350, 1350), Image.Resampling.LANCZOS)
        return ImageOps.exif_transpose(image).convert('RGB')


def source_path(asset):
    path = (root() / asset.path).resolve()
    if not path.is_relative_to((root() / 'sources').resolve()):
        raise ValueError('승인 자료 경로 오류')
    return path


def source_versions(book):
    if not book:
        return []
    return list(ApprovedImage.objects.filter(book=book, active=True).order_by('id').values(
        'id', 'kind', 'path', 'label', 'source', 'updated_at'))


def sources_current(plan):
    for saved in plan.get('sources', []):
        asset = ApprovedImage.objects.filter(pk=saved['id'], active=True).first()
        if not asset:
            return False
        try:
            with source_path(asset).open('rb') as fh:
                if hashlib.sha256(fh.read(MAX_BYTES + 1)).hexdigest() != saved['sha256']:
                    return False
        except (OSError, ValueError):
            return False
    return True


def load_assets(book):
    result, labels, sources = {}, {}, []
    if book and book.cover_image:
        with book.cover_image.open('rb') as fh:
            result['cover'] = open_image(fh.read(MAX_BYTES + 1))
        labels['cover'] = '한티재 원본 표지'
    if book:
        for asset in ApprovedImage.objects.filter(book=book, active=True).order_by('-id'):
            if asset.kind in result:
                continue
            with source_path(asset).open('rb') as fh:
                data = fh.read(MAX_BYTES + 1)
            result[asset.kind] = open_image(data)
            sources.append({'id': asset.pk, 'sha256': hashlib.sha256(data).hexdigest()})
            labels[asset.kind] = asset.label
    return result, labels, sources
