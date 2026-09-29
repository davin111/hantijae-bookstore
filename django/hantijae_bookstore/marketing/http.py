"""외부 페이지 읽기. 실패는 예외로 올리고, 부르는 쪽에서 건너뛴다."""
import requests

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'
MAX_BYTES = 20 * 1024 * 1024


def http_get(url, timeout=20):
    res = requests.get(url, timeout=timeout, headers={'User-Agent': UA})
    res.raise_for_status()
    return res.content.decode('utf-8', 'replace')


def http_get_bytes(url, timeout=30, max_bytes=MAX_BYTES):
    """첨부 파일(PDF·엑셀)을 바이트 그대로 받는다. max_bytes를 넘으면 내려받다 말고 예외를 올린다."""
    with requests.get(url, timeout=timeout, headers={'User-Agent': UA}, stream=True) as res:
        res.raise_for_status()
        chunks, size = [], 0
        for chunk in res.iter_content(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError(f'첨부 파일이 너무 커요({max_bytes // (1024 * 1024)}MB 초과): {url}')
            chunks.append(chunk)
        return b''.join(chunks)
