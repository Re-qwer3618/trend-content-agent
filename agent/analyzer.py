"""분석·필터링: 수집 결과 → 핵심 이슈 선별 + 연관 키워드 추출 (+ 선택적으로 LLM 인사이트).

1) 규칙 기반 (LLM 없이도 동작)
   - 연관 키워드: 제목·설명·태그를 토큰화해 빈도 × 등장 플랫폼 수로 점수
   - 이슈: 제목이 비슷한 항목을 묶고, 관련도·최신성·인기도·플랫폼 다양성으로 점수
   - 네이버 데이터랩으로 상위 키워드의 최근 검색량 증감 확인 (키 있을 때)
2) LLM 인사이트 (있을 때): 콘텐츠화 관점에서 이슈를 고르고 각도·SEO 키워드·해시태그 제안
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .collectors import CollectResult, NaverDataLab, TrendItem
from .config import Settings
from .llm import LLM, LLMError

# ---------------------------------------------------------------- 토큰화 (형태소 분석기 없이 가볍게)

_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9+]{1,}|\d+[가-힣A-Za-z]+")
_JOSA = sorted(
    "은 는 이 가 을 를 의 에 에서 에게 으로 로 와 과 도 만 까지 부터 처럼 보다 한테 이나 나 라도 이란 란 "
    "이다 였다 했다 한다 하는 하고 하며 해서 하면 된다 되는 됐다 이라는 라는 이었다".split(),
    key=len, reverse=True,
)
STOPWORDS = set(
    "기자 뉴스 오늘 사진 관련 위해 대한 통해 있다 없다 그리고 지난 이번 최근 대표 공개 진행 영상 단독 속보 종합 "
    "가장 정말 진짜 우리 이런 그런 어떤 모든 하나 때문 이후 이전 경우 정도 사실 생각 내용 이상 이하 "
    "올해 내년 작년 오전 오후 기준 발표 예정 가능 확인 제공 맞아 맞이 추진 개최 포착 실시 운영 "
    "좋은 많은 다양한 함께 구독 좋아요 알림 채널 문의 instagram vlog 브이로그 즐기 "
    "the and for with you this that from to of on in at by is are be it as or vs ft feat "
    "shorts youtube video official live "
    # 유튜브 음원 자동 설명문 ("Provided to YouTube by … Released on … Composer/Lyricist")
    "provided released auto generated music composer lyricist producer artist arranger "
    "remastered records entertainment".split()
)
_DATE_TOKEN_RE = re.compile(r"^\d+(일|월|년|시|분|초)$")  # '2일' 같은 날짜 조각은 키워드가 아님


def _strip_josa(tok: str) -> str:
    if not ("가" <= tok[0] <= "힣"):
        return tok.lower()
    for j in _JOSA:
        if tok.endswith(j) and len(tok) - len(j) >= 2:
            return tok[: -len(j)]
    return tok


_URL_RE = re.compile(r"https?://\S+|www\.\S+")


def tokenize(text: str) -> list[str]:
    out = []
    for raw in _TOKEN_RE.findall(_URL_RE.sub(" ", text or "")):  # 유튜브 설명의 링크 제거
        tok = _strip_josa(raw)
        if len(tok) >= 2 and tok not in STOPWORDS and not _DATE_TOKEN_RE.match(tok):
            out.append(tok)
    return out


# ---------------------------------------------------------------- 결과 구조


@dataclass
class Keyword:
    word: str
    score: float
    sources: list[str]
    count: int
    trend: dict | None = None  # 네이버 데이터랩 {"recent", "previous", "growth"}


@dataclass
class Issue:
    title: str
    score: float
    sources: list[str]
    items: list[TrendItem]
    breakdown: dict[str, float]  # relevance / recency / popularity / diversity


@dataclass
class Analysis:
    keyword: str | None
    collected: list[CollectResult]
    issues: list[Issue]
    keywords: list[Keyword]
    trending_now: list[TrendItem]          # 구글 실시간 급상승 (전체 화제, 참고용)
    seed_trend: dict | None = None         # 입력 키워드의 네이버 검색량 추이
    insight: dict = field(default_factory=dict)
    insight_by: str = "규칙 기반"           # 또는 LLM 이름
    notes: list[str] = field(default_factory=list)

    @property
    def all_items(self) -> list[TrendItem]:
        return [it for r in self.collected for it in r.items]


# ---------------------------------------------------------------- 키워드


def _press_tokens(items: list[TrendItem]) -> set[str]:
    """언론사·채널 이름은 키워드가 아니므로 제외 대상으로 모은다."""
    names = []
    for it in items:
        names += [it.extra.get("press", ""), it.extra.get("channel", "")]
        names += [n.get("source", "") for n in it.extra.get("news", [])]
    return {t for n in names if n for t in tokenize(n)}


def extract_keywords(items: list[TrendItem], seed: str | None, top: int = 20) -> list[Keyword]:
    seed_tokens = set(tokenize(seed or ""))
    excluded = seed_tokens | _press_tokens(items)
    weight: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    sources: dict[str, set] = defaultdict(set)

    for it in items:
        if _off_topic_trend(it, seed_tokens):
            continue  # 키워드 모드에서 무관한 전체 급상승어는 연관 키워드 계산에서 제외
        per_item: dict[str, float] = {}
        for tok in tokenize(it.title):
            per_item[tok] = max(per_item.get(tok, 0), 2.0)
        for tag in it.tags:
            for tok in tokenize(tag):
                per_item[tok] = max(per_item.get(tok, 0), 1.5)
        for tok in tokenize(it.description):
            per_item[tok] = max(per_item.get(tok, 0), 1.0)
        for tok, w in per_item.items():  # 한 문서 안 반복은 한 번만 (문서 빈도)
            weight[tok] += w
            count[tok] += 1
            sources[tok].add(it.source)

    result = [
        Keyword(word=t, score=round(w * (1 + 0.5 * (len(sources[t]) - 1)), 2),
                sources=sorted(sources[t]), count=count[t])
        for t, w in weight.items()
        if t not in excluded and count[t] >= 2
    ]
    result.sort(key=lambda k: k.score, reverse=True)
    return result[:top]


# ---------------------------------------------------------------- 이슈


def _relevance(item: TrendItem, seed_tokens: set[str]) -> float:
    if not seed_tokens:
        return 1.0
    text_tokens = set(tokenize(f"{item.title} {item.description} {' '.join(item.tags)}"))
    return len(seed_tokens & text_tokens) / len(seed_tokens)


def _off_topic_trend(item: TrendItem, seed_tokens: set[str]) -> bool:
    """키워드 모드에서 구글 실시간 급상승어는 키워드로 검색한 결과가 아니라 '오늘 전체 목록'이라,
    '가을' 같은 흔한 토큰 하나만 겹쳐도 붙어 들어온다(예: '가을 캠핑'에 '보그'). 키워드 토큰이 전부 있어야 채택."""
    return bool(seed_tokens) and item.source == "google_trends" and _relevance(item, seed_tokens) < 1.0


def _recency(item: TrendItem, now: datetime) -> float:
    if not item.published_at:
        return 0.3
    ts = item.published_at if item.published_at.tzinfo else item.published_at.replace(tzinfo=timezone.utc)
    hours = max((now - ts).total_seconds() / 3600, 0)
    return 0.5 ** (hours / 72)  # 반감기 3일


def _popularity(items: list[TrendItem]) -> dict[int, float]:
    """플랫폼마다 지표 단위가 달라 소스 안에서 log 정규화 (0~1)."""
    by_source: dict[str, list[TrendItem]] = defaultdict(list)
    for it in items:
        by_source[it.source].append(it)
    out = {}
    for group in by_source.values():
        top = max((math.log1p(i.metric) for i in group), default=0)
        for i in group:
            # 지표가 없는 소스(뉴스 등)는 중간보다 약간 높은 값 — 0.3이면 조회수 있는 유튜브만 상위를 독차지했다
            out[id(i)] = (math.log1p(i.metric) / top) if top else 0.75
    return out


def _cluster(items: list[TrendItem], threshold: float = 0.3) -> list[list[TrendItem]]:
    """제목 토큰 자카드 유사도로 탐욕적 묶기. 같은 사건을 다룬 뉴스·영상이 한 이슈가 된다."""
    clusters: list[tuple[set[str], list[TrendItem]]] = []
    for it in items:
        toks = set(tokenize(it.title))
        if not toks:
            continue
        for ctoks, members in clusters:
            if len(toks & ctoks) / len(toks | ctoks) >= threshold:
                members.append(it)
                ctoks |= toks
                break
        else:
            clusters.append((toks, [it]))
    return [m for _, m in clusters]


def rank_issues(items: list[TrendItem], seed: str | None, top: int = 7) -> list[Issue]:
    seed_tokens = set(tokenize(seed or ""))
    now = datetime.now(timezone.utc)
    pop = _popularity(items)
    issues = []
    for members in _cluster(items):
        rel = max(_relevance(i, seed_tokens) for i in members)
        if seed_tokens and rel == 0:
            continue
        srcs = sorted({i.source for i in members})
        breakdown = {
            "relevance": rel,
            "recency": max(_recency(i, now) for i in members),
            "popularity": max(pop[id(i)] for i in members),
            "diversity": min(len(srcs) / 3, 1.0) * min(len(members) / 3, 1.0) ** 0.5,
        }
        score = (0.35 * breakdown["relevance"] + 0.25 * breakdown["recency"]
                 + 0.25 * breakdown["popularity"] + 0.15 * breakdown["diversity"])
        lead = max(members, key=lambda i: pop[id(i)])
        issues.append(Issue(
            title=lead.title, score=round(score * 100, 1), sources=srcs,
            items=sorted(members, key=lambda i: pop[id(i)], reverse=True),
            breakdown={k: round(v, 2) for k, v in breakdown.items()},
        ))
    issues.sort(key=lambda x: x.score, reverse=True)
    if not seed_tokens:  # 오늘의 트렌드 모드: 유튜브 인기 영상이 목록을 독차지하지 않게
        issues = _balance_today(issues, top)
    return issues[:top]


# 유튜브 카테고리 중 블로그·릴스 소재가 되기 어려운 것 (YouTube Data API videoCategories, KR)
_YT_SKIP_CATEGORIES = {"10": "음악", "20": "게임"}
YOUTUBE_SHARE = 0.3  # 오늘의 목록에서 유튜브 단독 이슈가 차지할 수 있는 최대 비율


def _balance_today(issues: list[Issue], top: int) -> list[Issue]:
    """키워드 없는 목록: 게임·음악 영상은 빼고, 유튜브만으로 된 이슈는 top의 30%(10개 중 3개)까지만.
    자리가 남으면(급상승어가 모자라면) 밀려난 유튜브 이슈로 다시 채운다."""
    def youtube_only(iss: Issue) -> bool:
        return iss.sources == ["youtube"]

    def skipped(iss: Issue) -> bool:
        return youtube_only(iss) and all(it.extra.get("category_id") in _YT_SKIP_CATEGORIES for it in iss.items)

    kept = [i for i in issues if not skipped(i)]
    cap = max(1, int(top * YOUTUBE_SHARE))
    picked, overflow, yt = [], [], 0
    for iss in kept:
        if youtube_only(iss):
            if yt >= cap:
                overflow.append(iss)
                continue
            yt += 1
        picked.append(iss)
    return picked + overflow


# ---------------------------------------------------------------- LLM 인사이트

INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "main_topic": {"type": "string", "description": "이번 콘텐츠의 한 줄 주제"},
        "why_now": {"type": "string", "description": "지금 다뤄야 하는 이유 (데이터 근거)"},
        "target_audience": {"type": "string"},
        "selected_issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_index": {"type": "integer", "description": "제공된 이슈 목록의 번호"},
                    "angle": {"type": "string", "description": "이 이슈를 콘텐츠로 풀 관점"},
                    "content_fit": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["issue_index", "angle", "content_fit"],
                "additionalProperties": False,
            },
        },
        "seo_keywords": {
            "type": "object",
            "properties": {
                "main": {"type": "string"},
                "sub": {"type": "array", "items": {"type": "string"}},
                "long_tail": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["main", "sub", "long_tail"],
            "additionalProperties": False,
        },
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "cautions": {"type": "array", "items": {"type": "string"},
                     "description": "사실 확인·저작권·광고 표기 등 주의점"},
    },
    "required": ["main_topic", "why_now", "target_audience", "selected_issues",
                 "seo_keywords", "hashtags", "cautions"],
    "additionalProperties": False,
}

INSIGHT_SYSTEM = (
    "너는 한국 시장의 콘텐츠 마케팅 리서처다. 수집된 트렌드 데이터만 근거로, 네이버 블로그와 인스타그램 릴스로 "
    "만들었을 때 검색 유입·저장·공유가 잘 될 이슈를 고른다. 정치·사건사고·혐오처럼 브랜드 리스크가 큰 이슈는 "
    "content_fit을 low로 두고 이유를 cautions에 적는다. 데이터에 없는 사실은 지어내지 않는다."
)


def digest(analysis: Analysis, max_issues: int = 7, with_urls: bool = False) -> str:
    """LLM에 넘길 분석 요약(프롬프트용 텍스트). with_urls: 본문에 출처 링크를 걸 때."""
    lines = [f"# 입력 키워드: {analysis.keyword or '(없음 - 오늘의 트렌드 모드)'}", "", "## 핵심 이슈 후보"]
    for n, iss in enumerate(analysis.issues[:max_issues]):
        lines.append(f"[{n}] {iss.title}  (점수 {iss.score}, 플랫폼 {', '.join(iss.sources)})")
        for it in iss.items[:4]:
            meta = f" | {it.metric_label}" if it.metric_label else ""
            date = f" | {it.published_at:%Y-%m-%d}" if it.published_at else ""
            press = f" | {it.extra['press']}" if it.extra.get("press") else ""
            lines.append(f"    - ({it.source}) {it.title}{meta}{date}{press}")
            if with_urls and it.url:
                lines.append(f"      URL: {it.url}")
            if it.description:
                lines.append(f"      {it.description[:160]}")
    lines += ["", "## 연관 키워드 (점수 / 등장 플랫폼 / 네이버 검색량 최근7일 증감)"]
    for k in analysis.keywords[:15]:
        trend = ""
        if k.trend and k.trend.get("growth") is not None:
            trend = f" / 검색량 {k.trend['growth']:+.0f}%"
        lines.append(f"- {k.word}: {k.score} / {', '.join(k.sources)}{trend}")
    if analysis.trending_now:
        lines += ["", "## 구글 실시간 급상승 검색어 (전체 화제, 참고)"]
        lines += [f"- {t.title} ({t.metric_label})" for t in analysis.trending_now[:10]]
    blog_titles = [it.title for it in analysis.all_items if it.source == "naver_blog"][:10]
    if blog_titles:
        lines += ["", "## 네이버 블로그 상위 노출 글 제목 (경쟁 콘텐츠)"] + [f"- {t}" for t in blog_titles]
    return "\n".join(lines)


def rule_based_insight(analysis: Analysis) -> dict:
    seed = analysis.keyword or (analysis.issues[0].title if analysis.issues else "오늘의 트렌드")
    subs = [k.word for k in analysis.keywords[:6]]
    return {
        "main_topic": seed,
        "why_now": "수집 데이터의 상위 이슈 기준 (LLM 미사용 — 규칙 기반 요약)",
        "target_audience": "(LLM 연결 시 자동 제안)",
        "selected_issues": [
            {"issue_index": i, "angle": "", "content_fit": "medium"}
            for i, iss in enumerate(analysis.issues[:3])
        ],
        "seo_keywords": {
            "main": seed,
            "sub": subs,
            "long_tail": [f"{seed} {s}" for s in ("추천", "방법", "후기", "비교", "정리")],
        },
        "hashtags": [f"#{w.replace(' ', '')}" for w in [seed, *subs]][:15],
        "cautions": ["수집된 뉴스·영상의 사실관계는 게시 전 원문에서 직접 확인"],
    }


# ---------------------------------------------------------------- 진입점


def analyze(results: list[CollectResult], keyword: str | None, settings: Settings,
            llm: LLM | None, top_issues: int = 7) -> Analysis:
    items = [it for r in results for it in r.items]
    trending = [it for it in items if it.source == "google_trends"]
    seed_tokens = set(tokenize(keyword or ""))
    # 키워드 모드: 키워드와 무관한 전체 급상승어는 이슈 후보에서 빼고 '참고'로만 둔다
    candidates = [it for it in items if not _off_topic_trend(it, seed_tokens)]

    analysis = Analysis(
        keyword=keyword,
        collected=results,
        issues=rank_issues(candidates, keyword, top=top_issues),
        keywords=extract_keywords(candidates, keyword),
        trending_now=trending,
    )

    # 네이버 데이터랩: 입력 키워드 + 상위 연관 키워드 4개의 검색량 추이
    probe = ([keyword] if keyword else []) + [k.word for k in analysis.keywords[:5]]
    try:
        trends = NaverDataLab(settings).keyword_trends(probe[:5])
    except Exception as e:
        trends = {}
        status = getattr(getattr(e, "response", None), "status_code", None)
        hint = " — NAVER_CLIENT_ID/SECRET 인증 실패" if status == 401 else ""
        analysis.notes.append(f"네이버 데이터랩 조회 실패: {type(e).__name__} {status or ''}{hint}")
    for k in analysis.keywords:
        k.trend = trends.get(k.word)
    analysis.seed_trend = trends.get(keyword) if keyword else None

    analysis.insight = rule_based_insight(analysis)
    if llm and analysis.issues:
        try:
            analysis.insight = llm.json(INSIGHT_SYSTEM, digest(analysis), INSIGHT_SCHEMA)
            analysis.insight_by = llm.label
        except (LLMError, ValueError) as e:
            analysis.notes.append(f"LLM 인사이트 실패 → 규칙 기반 사용: {e}")
    return analysis
