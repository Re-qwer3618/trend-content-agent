"""YouTube Data API v3. 키워드가 있으면 최근 7일 검색 상위, 없으면 한국 인기 급상승 동영상.

쿼터: search.list 100유닛, videos.list 1유닛 (기본 10,000유닛/일).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import BaseCollector, TrendItem

API = "https://www.googleapis.com/youtube/v3"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class YouTubeCollector(BaseCollector):
    name = "youtube"

    def available(self):
        return (True, "") if self.settings.youtube_api_key else (False, "YOUTUBE_API_KEY 없음")

    def collect(self, keyword, limit):
        key = self.settings.youtube_api_key
        limit = min(limit, 50)
        if keyword:
            after = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
            search = self.get(f"{API}/search", params={
                "key": key, "part": "id", "q": keyword, "type": "video", "order": "viewCount",
                "regionCode": "KR", "relevanceLanguage": "ko", "publishedAfter": after,
                "maxResults": limit,
            }).json()
            ids = [it["id"]["videoId"] for it in search.get("items", []) if it.get("id", {}).get("videoId")]
            if not ids:
                return []
            params = {"id": ",".join(ids)}
        else:
            params = {"chart": "mostPopular", "regionCode": "KR", "maxResults": limit}

        videos = self.get(f"{API}/videos", params={
            "key": key, "part": "snippet,statistics,contentDetails", **params,
        }).json()

        items = []
        for v in videos.get("items", []):
            sn, st = v.get("snippet", {}), v.get("statistics", {})
            views = int(st.get("viewCount", 0) or 0)
            items.append(
                TrendItem(
                    source=self.name,
                    title=sn.get("title", ""),
                    url=f"https://www.youtube.com/watch?v={v['id']}",
                    description=(sn.get("description") or "")[:300],
                    published_at=_parse_iso(sn.get("publishedAt")),
                    metric=float(views),
                    metric_label=f"조회수 {views:,}",
                    tags=sn.get("tags", [])[:15],
                    extra={
                        "channel": sn.get("channelTitle", ""),
                        "likes": int(st.get("likeCount", 0) or 0),
                        "comments": int(st.get("commentCount", 0) or 0),
                        "duration": v.get("contentDetails", {}).get("duration", ""),  # PT45S → 쇼츠 판별용
                        "category_id": sn.get("categoryId", ""),  # 10 음악, 20 게임 … (오늘의 목록 필터용)
                    },
                )
            )
        return items
