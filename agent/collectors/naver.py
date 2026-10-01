"""네이버 검색 API(뉴스·블로그)와 데이터랩 검색어 트렌드 API.

developers.naver.com 에서 애플리케이션 등록 → 사용 API에 '검색', '데이터랩(검색어트렌드)' 추가.
NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 하나로 둘 다 사용. (검색 25,000회/일, 데이터랩 1,000회/일)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ..config import KST
from .base import BaseCollector, TrendItem, clean_text, parse_rfc822

SEARCH_URL = "https://openapi.naver.com/v1/search/{kind}.json"
DATALAB_URL = "https://openapi.naver.com/v1/datalab/search"


class _NaverBase(BaseCollector):
    def available(self):
        s = self.settings
        if s.naver_client_id and s.naver_client_secret:
            return True, ""
        return False, "NAVER_CLIENT_ID/SECRET 없음"

    @property
    def auth_headers(self) -> dict:
        return {
            "X-Naver-Client-Id": self.settings.naver_client_id or "",
            "X-Naver-Client-Secret": self.settings.naver_client_secret or "",
        }


class NaverNewsCollector(_NaverBase):
    name = "naver_news"

    def collect(self, keyword, limit):
        if not keyword:  # 네이버는 '전체 인기 검색어' 공개 API가 없음
            return []
        r = self.get(
            SEARCH_URL.format(kind="news"),
            params={"query": keyword, "display": min(limit, 100), "sort": "date"},
            headers=self.auth_headers,
        )
        return [
            TrendItem(
                source=self.name,
                title=clean_text(it.get("title")),
                url=it.get("originallink") or it.get("link", ""),
                description=clean_text(it.get("description")),
                published_at=parse_rfc822(it.get("pubDate")),
            )
            for it in r.json().get("items", [])
        ]


class NaverBlogCollector(_NaverBase):
    """상위 노출 블로그 = 경쟁 콘텐츠. 제목 패턴이 SEO 기획의 참고 자료가 된다."""

    name = "naver_blog"

    def collect(self, keyword, limit):
        if not keyword:
            return []
        r = self.get(
            SEARCH_URL.format(kind="blog"),
            params={"query": keyword, "display": min(limit, 100), "sort": "sim"},
            headers=self.auth_headers,
        )
        items = []
        for rank, it in enumerate(r.json().get("items", []), start=1):
            postdate = it.get("postdate")
            published = None
            if postdate:
                try:
                    published = datetime.strptime(postdate, "%Y%m%d").replace(tzinfo=KST)
                except ValueError:
                    pass
            items.append(
                TrendItem(
                    source=self.name,
                    title=clean_text(it.get("title")),
                    url=it.get("link", ""),
                    description=clean_text(it.get("description")),
                    published_at=published,
                    metric=float(max(0, 101 - rank)),  # 검색 상위일수록 높게
                    metric_label=f"검색 {rank}위",
                    extra={"blogger": it.get("bloggername", "")},
                )
            )
        return items


class NaverDataLab(_NaverBase):
    """키워드별 최근 검색량 추이. 수집기가 아니라 분석 단계에서 연관 키워드를 평가할 때 쓴다."""

    name = "naver_datalab"

    def keyword_trends(self, keywords: list[str], days: int = 28) -> dict[str, dict]:
        """{키워드: {"recent": 최근 7일 평균, "previous": 직전 7일 평균, "growth": 증감률(%)}}

        ratio는 한 요청 안에서 가장 많이 검색된 지점이 100인 상대값이라, 같은 요청의 키워드끼리만 비교 가능.
        """
        ok, _ = self.available()
        keywords = [k for k in dict.fromkeys(keywords) if k][:5]  # API 제한: 한 번에 5개 그룹
        if not ok or not keywords:
            return {}
        end = date.today()
        body = {
            "startDate": (end - timedelta(days=days)).isoformat(),
            "endDate": end.isoformat(),
            "timeUnit": "date",
            "keywordGroups": [{"groupName": k, "keywords": [k]} for k in keywords],
        }
        r = self.session.post(
            DATALAB_URL, json=body, headers=self.auth_headers, timeout=self.settings.http_timeout
        )
        r.raise_for_status()
        out = {}
        for res in r.json().get("results", []):
            ratios = [d["ratio"] for d in res.get("data", [])]
            recent = sum(ratios[-7:]) / max(len(ratios[-7:]), 1)
            prev_slice = ratios[-14:-7]
            previous = sum(prev_slice) / max(len(prev_slice), 1)
            growth = ((recent - previous) / previous * 100) if previous else None
            out[res["title"]] = {"recent": round(recent, 1), "previous": round(previous, 1),
                                 "growth": round(growth, 1) if growth is not None else None}
        return out
