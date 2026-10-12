"""카테고리별 제작 기본값 — prompts/categories.json (진행·리액션 캐릭터, 형식, 릴스 길이, 나레이션 톤).

노션 콘텐츠 예시 DB의 '카테고리'와 이름(name)이 같아 그 카테고리의 패턴(외부 사례)·본보기 세트를 골라 쓴다.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CAT_FILE = Path(__file__).parent / "prompts" / "categories.json"


@lru_cache(maxsize=1)
def all_categories() -> dict:
    data = json.loads(CAT_FILE.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def get(cid: str | None) -> dict | None:
    return all_categories().get(cid) if cid else None


def detect(text: str | None) -> str | None:
    """키워드·주제 글에서 카테고리 추정 — keywords가 가장 많이 걸리는 것(없으면 None)."""
    low = (text or "").lower()
    scores = {cid: sum(k.lower() in low for k in c["keywords"]) for cid, c in all_categories().items()}
    best = max(scores, key=scores.get, default=None)
    return best if best and scores[best] else None


def voice_offset(cid: str | None) -> tuple[int, int]:
    c = get(cid) or {}
    return c.get("rate", 0), c.get("pitch", 0)
