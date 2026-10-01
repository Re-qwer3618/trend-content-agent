from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests

from ..config import Settings

_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(text: str | None) -> str:
    """HTML 태그·엔티티 제거 (네이버 API는 <b>키워드</b> 형태로 강조해서 돌려줌)."""
    if not text:
        return ""
    return html.unescape(_TAG_RE.sub("", text)).strip()


def parse_rfc822(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


@dataclass
class TrendItem:
    """모든 플랫폼의 수집 결과를 담는 공통 형식."""

    source: str                      # google_trends, google_news, naver_news, naver_blog, youtube, instagram
    title: str
    url: str = ""
    description: str = ""
    published_at: datetime | None = None
    metric: float = 0.0              # 플랫폼별 인기 지표(검색량, 조회수, 좋아요 등)
    metric_label: str = ""           # metric이 무엇인지 (예: "조회수")
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat() if self.published_at else None
        return d


@dataclass
class CollectResult:
    source: str
    items: list[TrendItem] = field(default_factory=list)
    skipped: str = ""                # 키 없음 등으로 건너뛴 이유
    error: str = ""


class BaseCollector:
    name = "base"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers["User-Agent"] = settings.user_agent

    def available(self) -> tuple[bool, str]:
        """(사용 가능 여부, 불가 사유)."""
        return True, ""

    def collect(self, keyword: str | None, limit: int) -> list[TrendItem]:
        raise NotImplementedError

    def run(self, keyword: str | None, limit: int) -> CollectResult:
        ok, reason = self.available()
        if not ok:
            return CollectResult(self.name, skipped=reason)
        try:
            return CollectResult(self.name, items=self.collect(keyword, limit))
        except requests.RequestException as e:
            return CollectResult(self.name, error=f"{type(e).__name__}: {_safe_error(e)}")
        except Exception as e:  # 한 플랫폼 실패가 전체 파이프라인을 멈추지 않도록
            return CollectResult(self.name, error=f"{type(e).__name__}: {e}")

    def get(self, url: str, **kwargs) -> requests.Response:
        r = self.session.get(url, timeout=self.settings.http_timeout, **kwargs)
        r.raise_for_status()
        return r


def _safe_error(e: requests.RequestException) -> str:
    # URL 쿼리에 API 키가 들어가는 플랫폼(YouTube 등)이 있어 URL은 빼고 상태만 남긴다
    resp = getattr(e, "response", None)
    if resp is not None:
        return f"HTTP {resp.status_code} {resp.reason}"
    return "request failed (네트워크/타임아웃)"
