"""오늘의 이슈 TOP N 목록 (--list) 과 그중 골라서 상세 작성 (--pick).

목록은 기획서 없이 순위·지표·대표 링크만 담는다. 사용자가 번호를 고르면 그 이슈의 검색어(query)로
키워드 모드를 다시 돌려 기사·영상을 더 모은 뒤 상세 리포트를 만든다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .analyzer import Analysis, Issue
from .config import KST
from .report import SOURCE_LABEL, _md_cell, _slug

_BRACKET_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】|#\S+")
_GENERIC_RE = re.compile(r"예고편|티저|트레일러|하이라이트|M/?V|OST|teaser|trailer", re.I)
_CUT_RE = re.compile(r"\s[|｜/]\s?|\s-\s")  # "제목 | 채널", "제목 - 부제" 에서 앞부분만


def issue_query(iss: Issue) -> str:
    """상세 작성 때 다시 검색할 키워드. 구글 급상승어는 검색어 자체, 그 외는 제목을 짧게 다듬는다."""
    for it in iss.items:
        if it.source == "google_trends":
            return it.title
    title = _CUT_RE.split(_BRACKET_RE.sub(" ", iss.title))[0]
    # "[드럼(통 속의 진실)] 메인 예고편" 처럼 괄호 밖이 '예고편' 같은 일반어뿐이면 괄호 안이 진짜 제목
    lead = re.match(r"\s*\[([^\]]+)\]", iss.title)
    generic = _GENERIC_RE.search(title)
    if lead and (not title.strip() or (generic and len(_GENERIC_RE.sub("", title).split()) <= 1)):
        title = re.sub(r"[()]", " ", lead.group(1)) + (f" {generic.group(0)}" if generic else "")
    title = re.sub(r"[^\w\s·.,'&-]", " ", title)  # 이모지·특수기호 제거
    words = title.split()
    query = ""
    for w in words:  # 30자 안에서 단어 단위로 자르기
        if len(query) + len(w) + 1 > 30:
            break
        query = f"{query} {w}".strip()
    return query or iss.title[:30]


def _entry(rank: int, iss: Issue) -> dict:
    lead = max(iss.items, key=lambda i: i.metric)
    headlines = []
    for it in iss.items:
        for n in it.extra.get("news", [])[:3]:  # 구글 급상승어에 딸린 관련 기사
            headlines.append({"title": n["title"], "url": n["url"], "source": n["source"]})
    for it in iss.items[1:4]:  # 같은 이슈로 묶인 다른 기사·영상
        headlines.append({"title": it.title, "url": it.url, "source": it.extra.get("press") or it.extra.get("channel") or it.source})
    return {
        "rank": rank,
        "title": iss.title,
        "query": issue_query(iss),
        "score": iss.score,
        "sources": iss.sources,
        "metric": lead.metric_label,
        "url": lead.url,
        "published_at": lead.published_at.isoformat() if lead.published_at else None,
        "headlines": headlines[:4],
    }


def save_issue_list(analysis: Analysis, report_dir: Path, top: int = 10) -> Path:
    """<시각>_<키워드>_issues.json 과 같은 이름의 .md 를 저장하고 .md 경로를 돌려준다."""
    now = datetime.now(KST)
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{now:%Y%m%d_%H%M}_{_slug(analysis.keyword or 'today')}_issues"
    entries = [_entry(i, iss) for i, iss in enumerate(analysis.issues[:top], start=1)]
    payload = {"keyword": analysis.keyword, "created_at": now.isoformat(), "issues": entries}
    (report_dir / f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# 이슈 TOP {len(entries)}: {analysis.keyword or '오늘의 트렌드'}", "",
             f"- 생성: {now:%Y-%m-%d %H:%M} (KST)", "- 상세 작성: `run.bat --pick 번호 [번호 ...]`", "",
             "| 순위 | 이슈 | 지표 | 플랫폼 | 검색어(--pick) |", "|---|---|---|---|---|"]
    for e in entries:
        srcs = ", ".join(SOURCE_LABEL.get(s, s) for s in e["sources"])
        title = f"[{_md_cell(e['title'])}]({e['url']})" if e["url"] else _md_cell(e["title"])
        lines.append(f"| {e['rank']} | {title} | {_md_cell(e['metric'])} | {srcs} | {_md_cell(e['query'])} |")
    lines.append("")
    for e in entries:
        if e["headlines"]:
            lines.append(f"**{e['rank']}. {e['title']}**")
            lines += [f"- [{h['title']}]({h['url']}) — {h['source']}" for h in e["headlines"]]
            lines.append("")
    md = report_dir / f"{stem}.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    return md


def load_issue_list(report_dir: Path, path: str | None = None) -> tuple[Path, list[dict]]:
    """지정한 목록(.json 또는 .md) 또는 가장 최근 *_issues.json."""
    if path:
        p = Path(path)
        p = p.with_suffix(".json") if p.suffix == ".md" else p
    else:
        found = sorted(report_dir.glob("*_issues.json"))
        if not found:
            raise FileNotFoundError("이슈 목록이 없습니다. 먼저 run.bat --today --list 를 실행하세요.")
        p = found[-1]
    return p, json.loads(p.read_text(encoding="utf-8"))["issues"]
