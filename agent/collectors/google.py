"""Google 트렌드(실시간 인기 검색어 RSS)와 Google 뉴스 검색 RSS. 키 불필요."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

from .base import BaseCollector, TrendItem, clean_text, parse_rfc822

TRENDS_RSS = "https://trends.google.com/trending/rss?geo={geo}"
NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
HT = "{https://trends.google.com/trending/rss}"


def _traffic_to_number(text: str) -> float:
    # "2000+", "10만+", "1M+" 같은 표기를 대략적인 수로
    t = (text or "").replace(",", "").replace("+", "").strip()
    m = re.match(r"([\d.]+)\s*([KkMm만천]?)", t)
    if not m:
        return 0.0
    n = float(m.group(1))
    return n * {"K": 1e3, "k": 1e3, "M": 1e6, "m": 1e6, "만": 1e4, "천": 1e3}.get(m.group(2), 1)


class GoogleTrendsCollector(BaseCollector):
    """지금 한국에서 급상승 중인 검색어. 키워드 모드에서도 '전체 화제' 맥락으로 쓰인다."""

    name = "google_trends"

    def collect(self, keyword, limit):
        root = ET.fromstring(self.get(TRENDS_RSS.format(geo="KR")).content)
        items = []
        for it in root.iter("item"):
            news = [
                {
                    "title": clean_text(n.findtext(f"{HT}news_item_title")),
                    "url": n.findtext(f"{HT}news_item_url") or "",
                    "source": n.findtext(f"{HT}news_item_source") or "",
                }
                for n in it.findall(f"{HT}news_item")
            ]
            traffic = it.findtext(f"{HT}approx_traffic") or ""
            items.append(
                TrendItem(
                    source=self.name,
                    title=clean_text(it.findtext("title")),
                    url=news[0]["url"] if news else "",
                    description=" / ".join(n["title"] for n in news[:3]),
                    published_at=parse_rfc822(it.findtext("pubDate")),
                    metric=_traffic_to_number(traffic),
                    metric_label=f"검색량 {traffic}",
                    extra={"news": news},
                )
            )
        return items[:limit]


class GoogleNewsCollector(BaseCollector):
    """키워드 관련 최신 뉴스. 키워드가 없으면 건너뜀."""

    name = "google_news"

    def collect(self, keyword, limit):
        if not keyword:
            return []
        root = ET.fromstring(self.get(NEWS_RSS.format(q=quote(keyword))).content)
        items = []
        for it in root.iter("item"):
            title = clean_text(it.findtext("title"))
            press = it.findtext("source") or ""
            # 제목 끝의 " - 언론사" 제거
            if press and title.endswith(f" - {press}"):
                title = title[: -len(press) - 3]
            items.append(
                TrendItem(
                    source=self.name,
                    title=title,
                    url=it.findtext("link") or "",
                    published_at=parse_rfc822(it.findtext("pubDate")),
                    extra={"press": press},
                )
            )
        return items[:limit]
