"""첨부 문서(PDF·엑셀)에서 글자만 뽑는다. 표 구조는 보지 않는다 — 대조는 ISBN·제목이 '들어 있는지'만 본다."""
import io
import zipfile
from xml.etree import ElementTree

from pypdf import PdfReader


def pdf_text(data):
    reader = PdfReader(io.BytesIO(data))
    return '\n'.join((page.extract_text() or '') for page in reader.pages)


def xlsx_text(data):
    """공유 문자열(<t>)과 시트 셀 값(<v>)을 모두 모은다. ISBN은 숫자 셀(<v>)에 들어 있는 경우가 많다."""
    parts = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name == 'xl/sharedStrings.xml' or (name.startswith('xl/worksheets/') and name.endswith('.xml')):
                root = ElementTree.fromstring(z.read(name))
                parts += [el.text for el in root.iter() if el.tag.rsplit('}', 1)[-1] in ('t', 'v') and el.text]
    return '\n'.join(parts)


def document_text(name, data):
    lower = (name or '').lower()
    if lower.endswith('.pdf'):
        return pdf_text(data)
    if lower.endswith('.xlsx'):
        return xlsx_text(data)
    return ''
