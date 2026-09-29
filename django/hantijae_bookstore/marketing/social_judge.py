"""운영진 개인 SNS 글 해석: 묶기 → LLM 판정 → 책·날짜 확인 → Signal(kind=social).
LLM이 말한 책 제목·행사 날짜는 글에 실제로 있는지 코드로 다시 확인한다(지어낸 것 거르기)."""
import re
from datetime import timedelta

from marketing.models import SocialPost
from marketing.social_parse import share_key
from marketing.text import similarity

SAME_POST_RATIO, SAME_POST_WINDOW, MIN_TEXT = 0.85, timedelta(days=3), 20


def _long_enough(text):
    return len(re.sub(r'\s+', '', text or '')) >= MIN_TEXT


def assign_group(post):
    """새 글의 묶음 열쇠. 같은 원문 공유 → ±3일 안의 거의 같은 글(페북·인스타 복사) → 자기 자신."""
    if post.shared.get('url'):
        return 'share:' + share_key(post.shared['url'])
    if _long_enough(post.text):
        near = (SocialPost.objects.filter(posted_at__gte=post.posted_at - SAME_POST_WINDOW,
                                          posted_at__lte=post.posted_at + SAME_POST_WINDOW)
                .exclude(pk=post.pk).exclude(group_key='').order_by('first_seen', 'id'))
        for other in near:
            if _long_enough(other.text) and similarity(post.text, other.text) >= SAME_POST_RATIO:
                return other.group_key
    return f'post:{post.platform}:{post.post_id}'
