"""외부 페이지 읽기. 실패는 예외로 올리고, 부르는 쪽에서 건너뛴다."""
import requests

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'


def http_get(url, timeout=20):
    res = requests.get(url, timeout=timeout, headers={'User-Agent': UA})
    res.raise_for_status()
    return res.content.decode('utf-8', 'replace')


def http_get_bytes(url, timeout=30):
    """첨부 파일(PDF·엑셀)을 바이트 그대로 받는다."""
    res = requests.get(url, timeout=timeout, headers={'User-Agent': UA})
    res.raise_for_status()
    return res.content
