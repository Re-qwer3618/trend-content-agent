"""분석 결과 + 기획서 → 마크다운 리포트 파일."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .analyzer import Analysis
from .config import KST
from .generator import Plan

SOURCE_LABEL = {
    "google_trends": "구글 트렌드(실시간)",
    "google_news": "구글 뉴스",
    "naver_news": "네이버 뉴스",
    "naver_blog": "네이버 블로그",
    "youtube": "유튜브",
    "instagram": "인스타그램",
}


def _slug(text: str) -> str:
    return re.sub(r"[^\w가-힣-]+", "_", text).strip("_")[:40] or "trend"


def _md_cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def build_markdown(analysis: Analysis, plans: list[Plan], now: datetime) -> str:
    a, ins = analysis, analysis.insight
    out = [
        f"# 트렌드 리서치 & 콘텐츠 기획 리포트: {a.keyword or '오늘의 트렌드'}",
        "",
        f"- 생성: {now:%Y-%m-%d %H:%M} (KST)",
        f"- 분석: {a.insight_by}",
        f"- 기획서: " + ", ".join(f"{p.title} ({p.generated_by})" for p in plans),
        "",
        "## 1. 요약",
        f"- **주제**: {ins.get('main_topic', '')}",
        f"- **왜 지금**: {ins.get('why_now', '')}",
        f"- **타깃**: {ins.get('target_audience', '')}",
    ]
    if a.seed_trend:
        g = a.seed_trend.get("growth")
        out.append(f"- **네이버 검색량** (최근 7일 vs 직전 7일): {f'{g:+.0f}%' if g is not None else '-'}")

    out += ["", "## 2. 수집 현황", "| 플랫폼 | 건수 | 상태 |", "|---|---|---|"]
    for r in a.collected:
        status = "✅" if r.items else ("⏭ " + r.skipped if r.skipped else ("⚠ " + r.error if r.error else "결과 없음"))
        out.append(f"| {SOURCE_LABEL.get(r.source, r.source)} | {len(r.items)} | {_md_cell(status)} |")
    if a.notes:
        out += [""] + [f"> {n}" for n in a.notes]

    out += ["", "## 3. 핵심 이슈", "| # | 이슈 | 점수 | 플랫폼 | 콘텐츠 적합도 | 관점 |", "|---|---|---|---|---|---|"]
    fit = {s["issue_index"]: s for s in ins.get("selected_issues", [])}
    for i, iss in enumerate(a.issues):
        sel = fit.get(i, {})
        out.append(
            f"| {i} | {_md_cell(iss.title[:60])} | {iss.score} | "
            f"{', '.join(SOURCE_LABEL.get(s, s) for s in iss.sources)} | {sel.get('content_fit', '-')} | "
            f"{_md_cell(sel.get('angle') or '-')} |"
        )
    if not a.issues:
        out.append("| - | 수집된 이슈 없음 | | | | |")

    out += ["", "## 4. 연관 키워드", "| 키워드 | 점수 | 언급 수 | 플랫폼 | 네이버 검색량 증감 |", "|---|---|---|---|---|"]
    for k in a.keywords[:15]:
        g = k.trend.get("growth") if k.trend else None
        out.append(f"| {k.word} | {k.score} | {k.count} | {', '.join(SOURCE_LABEL.get(s, s) for s in k.sources)} | "
                   f"{f'{g:+.0f}%' if g is not None else '-'} |")
    seo = ins.get("seo_keywords", {})
    out += [
        "",
        f"- **SEO 메인**: {seo.get('main', '')}",
        f"- **서브**: {', '.join(seo.get('sub', []))}",
        f"- **롱테일**: {', '.join(seo.get('long_tail', []))}",
        f"- **해시태그**: {' '.join(ins.get('hashtags', []))}",
    ]
    if ins.get("cautions"):
        out += ["", "**주의사항**"] + [f"- {c}" for c in ins["cautions"]]

    if a.keyword and a.trending_now:
        out += ["", "<details><summary>참고: 지금 구글 실시간 급상승 검색어</summary>", ""]
        out += [f"- {t.title} ({t.metric_label})" for t in a.trending_now[:15]]
        out += ["", "</details>"]

    for n, p in enumerate(plans, start=5):
        out += ["", "---", "", f"## {n}. {p.title}", f"*작성: {p.generated_by}*", "", p.body.strip()]

    out += ["", "---", "", "## 부록: 이슈별 원문 링크"]
    for i, iss in enumerate(a.issues):
        out.append(f"\n**[{i}] {iss.title}**")
        for it in iss.items[:5]:
            meta = f" · {it.metric_label}" if it.metric_label else ""
            out.append(f"- [{it.title}]({it.url}) — {SOURCE_LABEL.get(it.source, it.source)}{meta}")
    return "\n".join(out) + "\n"


def save_report(analysis: Analysis, plans: list[Plan], report_dir: Path) -> Path:
    now = datetime.now(KST)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{now:%Y%m%d_%H%M}_{_slug(analysis.keyword or 'today')}.md"
    path.write_text(build_markdown(analysis, plans, now), encoding="utf-8")
    return path


def save_raw(analysis: Analysis, data_dir: Path) -> Path:
    """수집 원본(JSON) 보관 — 분석 로직을 바꿔 재실행하거나 디버깅할 때 사용."""
    now = datetime.now(KST)
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{now:%Y%m%d_%H%M%S}_{_slug(analysis.keyword or 'today')}.json"
    payload = {
        "keyword": analysis.keyword,
        "collected_at": now.isoformat(),
        "results": [
            {"source": r.source, "skipped": r.skipped, "error": r.error,
             "items": [it.to_dict() for it in r.items]}
            for r in analysis.collected
        ],
        "insight": analysis.insight,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
