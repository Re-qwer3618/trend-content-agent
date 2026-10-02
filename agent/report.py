"""분석 결과 + 기획서 → 마크다운 리포트 파일."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .analyzer import Analysis
from .config import KST
from .generator import STAGE_NAMES, Plan
from .images import USAGES, ImagePrompt
from .prompt_pack import RequestPrompt

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


def build_markdown(analysis: Analysis, plans: list[Plan], now: datetime,
                   images: list[ImagePrompt] | None = None, images_by: str = "",
                   requests: list[RequestPrompt] | None = None) -> str:
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

    n = 5
    for p in plans:
        plan_name, draft_name = STAGE_NAMES[p.format]
        out += ["", "---", "", f"## {n}. {p.title} {plan_name}", f"*작성: {p.generated_by}*", "", p.body.strip()]
        n += 1
        if p.draft:
            out += ["", "---", "", f"## {n}. {p.title} {draft_name}", f"*작성: {p.draft_by}*", "",
                    _demote_headings(p.draft.strip())]
            n += 1

    if requests:
        out += ["", "---", "", f"## {n}. LLM 제작 요청 프롬프트",
                "> API를 쓰지 않고 웹 LLM(ChatGPT·Claude.ai·Gemini)에 붙여 넣어 완성본을 만드는 프롬프트입니다. "
                "같은 내용이 `*_요청_*.txt` 파일로도 저장돼 있어 통째로 복사하기 편합니다.", ""]
        for r in requests:
            out += [f"### {r.title}", f"*사용법: {r.tip}*", "", "````text", r.text, "````", ""]

    out += ["", "---", "", "## 부록: 이슈별 원문 링크"]
    for i, iss in enumerate(a.issues):
        out.append(f"\n**[{i}] {iss.title}**")
        for it in iss.items[:5]:
            meta = f" · {it.metric_label}" if it.metric_label else ""
            out.append(f"- [{it.title}]({it.url}) — {SOURCE_LABEL.get(it.source, it.source)}{meta}")

    if images:
        out += ["", "---", "", "## 이미지 생성 프롬프트", f"*작성: {images_by}*", "",
                "> 이미지 안에는 글자를 넣지 않도록 만들었습니다. `얹을 문구`는 편집 툴에서 따로 올리세요.", ""]
        for img in images:
            label = USAGES[img.usage][0]
            out += [
                f"### [{img.issue_index}] {img.issue_title[:50]} — {label} ({img.aspect_ratio})",
                f"- 스타일: {img.style}",
                f"- 얹을 문구: **{img.overlay_text_ko}**",
                f"- 대체텍스트(alt): {img.alt_text_ko}",
                "",
                "```text",
                img.prompt_en,
                "```",
                f"Negative: `{img.negative_prompt}`",
                "",
            ]
    return "\n".join(out) + "\n"


def _demote_headings(md: str) -> str:
    """원고의 `#`/`##` 제목을 리포트 안 하위 제목(###~)으로 내린다. 코드 블록 안은 건드리지 않음."""
    lines, in_code = [], False
    for line in md.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and (m := re.match(r"^(#{1,4}) ", line)):
            line = "#" * min(len(m.group(1)) + 2, 6) + line[len(m.group(1)):]
        lines.append(line)
    return "\n".join(lines)


def save_report(analysis: Analysis, plans: list[Plan], report_dir: Path,
                images: list[ImagePrompt] | None = None, images_by: str = "",
                requests: list[RequestPrompt] | None = None) -> Path:
    now = datetime.now(KST)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{now:%Y%m%d_%H%M}_{_slug(analysis.keyword or 'today')}.md"
    path.write_text(build_markdown(analysis, plans, now, images, images_by, requests), encoding="utf-8")
    for r in requests or []:  # 웹 LLM에 통째로 붙여 넣기 좋게 따로 저장
        path.with_name(f"{path.stem}_요청_{r.key}.txt").write_text(r.text + "\n", encoding="utf-8")
    for p in plans:  # 완성 원고는 복사해 쓰기 쉽게 따로도 저장
        if p.draft:
            path.with_name(f"{path.stem}_{p.format}_{STAGE_NAMES[p.format][1].split()[-1]}.md").write_text(
                p.draft.strip() + "\n", encoding="utf-8")
    if images:  # image_maker가 다시 읽어 실제 이미지를 만든다
        images_json_path(path).write_text(
            json.dumps({"by": images_by, "prompts": [asdict(i) for i in images]}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return path


def images_json_path(report: Path) -> Path:
    return report.with_name(f"{report.stem}_images.json")


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
