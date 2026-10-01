"""데이터 수집기. 플랫폼마다 하나씩, 결과는 공통 TrendItem 형식.

새 플랫폼 추가: BaseCollector를 상속해 collect()를 구현하고 COLLECTORS에 등록.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..config import Settings
from .base import BaseCollector, CollectResult, TrendItem
from .google import GoogleNewsCollector, GoogleTrendsCollector
from .instagram import InstagramCollector
from .naver import NaverBlogCollector, NaverDataLab, NaverNewsCollector
from .youtube import YouTubeCollector

COLLECTORS: dict[str, type[BaseCollector]] = {
    c.name: c
    for c in (
        GoogleTrendsCollector,
        GoogleNewsCollector,
        NaverNewsCollector,
        NaverBlogCollector,
        YouTubeCollector,
        InstagramCollector,
    )
}


def collect_all(
    settings: Settings, keyword: str | None, sources: list[str] | None = None, limit: int = 20
) -> list[CollectResult]:
    """선택한 플랫폼을 병렬로 수집. 실패·건너뜀도 결과에 남겨 리포트에 표시한다."""
    names = sources or list(COLLECTORS)
    unknown = [n for n in names if n not in COLLECTORS]
    if unknown:
        raise ValueError(f"알 수 없는 소스: {unknown} (가능: {list(COLLECTORS)})")
    collectors = [COLLECTORS[n](settings) for n in names]
    with ThreadPoolExecutor(max_workers=len(collectors)) as pool:
        return list(pool.map(lambda c: c.run(keyword, limit), collectors))


__all__ = ["COLLECTORS", "CollectResult", "NaverDataLab", "TrendItem", "collect_all"]
