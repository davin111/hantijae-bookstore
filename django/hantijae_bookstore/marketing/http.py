"""외부 페이지 읽기. 실패는 예외로 올리고, 부르는 쪽에서 건너뛴다."""
import requests

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'


def http_get(url, timeout=20):
    res = requests.get(url, timeout=timeout, headers={'User-Agent': UA})
    res.raise_for_status()
    return res.content.decode('utf-8', 'replace')
