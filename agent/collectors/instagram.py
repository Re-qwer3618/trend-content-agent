"""Instagram Graph API 해시태그 검색 (선택).

인스타그램은 공개 트렌드 API가 없다. 공식 경로는 '비즈니스/크리에이터 계정 + Meta 앱(instagram_basic,
Instagram Public Content Access)'으로 해시태그 상위 게시물을 조회하는 것뿐이며, 해시태그 검색은 7일간 30개로 제한된다.
토큰이 없으면 건너뛴다. (로그인 스크레이핑은 약관 위반·계정 정지 위험이 있어 구현하지 않음)
"""
from __future__ import annotations

from datetime import datetime

from .base import BaseCollector, TrendItem


class InstagramCollector(BaseCollector):
    name = "instagram"

    def available(self):
        s = self.settings
        if s.instagram_access_token and s.instagram_user_id:
            return True, ""
        return False, "INSTAGRAM_ACCESS_TOKEN/USER_ID 없음 (Graph API 비즈니스 계정 필요)"

    def collect(self, keyword, limit):
        if not keyword:
            return []
        s = self.settings
        base = f"https://graph.facebook.com/{s.instagram_graph_version}"
        auth = {"user_id": s.instagram_user_id, "access_token": s.instagram_access_token}
        hashtag = keyword.replace(" ", "").lstrip("#")

        found = self.get(f"{base}/ig_hashtag_search", params={"q": hashtag, **auth}).json()
        if not found.get("data"):
            return []
        tag_id = found["data"][0]["id"]

        media = self.get(f"{base}/{tag_id}/top_media", params={
            "fields": "caption,media_type,like_count,comments_count,permalink,timestamp",
            "limit": min(limit, 50), **auth,
        }).json()

        items = []
        for m in media.get("data", []):
            caption = m.get("caption") or ""
            likes = int(m.get("like_count", 0) or 0)
            ts = m.get("timestamp")
            items.append(
                TrendItem(
                    source=self.name,
                    title=caption.split("\n")[0][:80] or f"#{hashtag} 게시물",
                    url=m.get("permalink", ""),
                    description=caption[:300],
                    published_at=datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z") if ts else None,
                    metric=float(likes + 3 * int(m.get("comments_count", 0) or 0)),
                    metric_label=f"좋아요 {likes:,}",
                    tags=[w.lstrip("#") for w in caption.split() if w.startswith("#")][:20],
                    extra={"media_type": m.get("media_type", "")},
                )
            )
        return items
