"""카드뉴스(인스타그램 피드 캐러셀) — 카드 문구(JSON) → cards.html → PNG.

카드 그리기는 cardnews-kit 스킬(cardnews-engine의 render.cjs: 로컬 Chrome으로 1080×1350 PNG, 넘침·작은 글자·어색한 줄바꿈 검사)에 맡긴다.
키트는 프로젝트 `.claude/skills/`에 두되 git에는 넣지 않는다(재배포 라이선스 없음, 공개 저장소) — PC마다 복사 후 `npm install`.

카드 문구 파일 (`reports/<리포트>_cards.json`) — 리포트를 만들 때 저장한다(API 모드는 LLM, 아니면 상위 이슈로 기본본).
Claude가 쓴 문구로 덮어쓰거나 웹 LLM 답변을 `--cards-file`로 넘겨 `run.bat --cards-from <리포트>`로 다시 굽는다.
작성 규칙은 prompts/cards.md (요청 프롬프트·API 모드·스킬 공통).

    {"style": "series", "channel": "starter", "topic": "가을 캠핑",
     "cards": [{"type": "cover" | "page" | "closing", "name": "영문-파일이름", "pill": "01 / 03",
                "title": "두 줄\\n*강조*", "desc": "설명 한 줄", "dots": ["점 목록"],
                "shot": {"label": "화면 이름", "dark": false,
                         "rows": [["이름", "값"]] | "list": [..] | "table": [["머리", "값"]] |
                         "checks": [..] | "text": "*칸* 강조 가능" | "image": "프로젝트 기준 경로"}}],
     "caption": "...", "hashtags": ["#..."]}

`title`·`text`의 `\\n`은 줄바꿈, `*…*`는 강조색(표지는 흰 띠). 문구에 없는 사실은 쓰지 않는다(지어내지 않기).
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import PROJECT_DIR
from .report import SOURCE_LABEL

STYLES = ("series",)  # 지금은 starter의 series 틀만 지원 (나머지 틀은 짜임이 달라 변환기를 따로 만든다)
SHOT_KINDS = ("rows", "list", "table", "checks", "text", "image")
CHECK_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.4" stroke-linecap="round" '
             'stroke-linejoin="round"><path d="M4 12.5l5 5L20 6.5"/></svg>')


class CardError(RuntimeError):
    pass


@dataclass
class CardResult:
    set_dir: Path
    pngs: list[Path]
    sheet: Path | None
    warnings: list[str] = field(default_factory=list)


def cards_json_path(report: Path) -> Path:
    return report.with_name(f"{report.stem}_cards.json")


# ---------------------------------------------------------------- 기본 문구 (LLM 없이, 수집 데이터 그대로)


def cards_from_analysis(analysis, max_issues: int = 4) -> dict:
    """상위 이슈로 표지 → 이슈 N장 → 확인할 것 → 마무리. 우리 데이터는 제목뿐이라 제목·출처·날짜만 싣는다."""
    from .shorts_maker import _clean_title, _short_caption

    main = analysis.insight.get("seo_keywords", {}).get("main") or analysis.keyword or "오늘의 트렌드"
    issues = analysis.issues[:max_issues]
    if not issues:
        raise CardError("카드로 만들 이슈가 없습니다")
    n = len(issues)
    shorts = []
    for iss in issues:
        head, body = _clean_title(iss.title)
        shorts.append((head, body, _headline(body, main) or _short_caption(body, 18)))

    cards = [{
        "type": "cover", "name": "cover",
        "title": f"{_wrap(main, 8)}\n*지금 뜨는 {n}가지*",
        "desc": "수집 시각 기준, 화제 순으로 모았어요.",
        "shot": {"label": "오늘 모은 소식", "dark": True,
                 "rows": [[f"{i + 1:02d}", s[2]] for i, s in enumerate(shorts[:3])]},
    }]
    for i, (iss, (head, body, short)) in enumerate(zip(issues, shorts)):
        item = iss.items[0] if iss.items else None
        where = SOURCE_LABEL.get(item.source, item.source) if item else ""
        extra = (item.extra or {}) if item else {}
        who = extra.get("press") or extra.get("channel") or extra.get("blogger") or ""
        when = item.published_at.strftime("%m.%d") if item and item.published_at else ""
        cards.append({
            "type": "page", "name": f"issue-{i + 1}", "pill": f"{i + 1:02d} / {n:02d}",
            "title": _emphasize_last(_wrap(short, 9)),
            "desc": " · ".join(x for x in (head, where, when) if x) or "수집한 원문 제목이에요.",
            "shot": {"label": "원문 제목 · 수집 데이터",
                     "table": [["제목", _wrap(body, 17)]] + ([["출처", who]] if who else [])},
        })
    cards.append({
        "type": "page", "name": "checklist", "pill": "저장용",
        "title": "보기 전에\n*세 가지* 확인",
        "desc": "기사 제목만으로는 알 수 없는 것들이에요.",
        "shot": {"checks": ["원문 날짜가 최근인지", "가격·일정은 공식 안내로", "광고·협찬 표기가 있는지"]},
    })
    cards.append({
        "type": "closing", "name": "closing", "pill": "가져가기",
        "title": "저장해 두고\n*원문으로* 확인하세요",
        "desc": f"{main}, 다음 소식도 모아 올게요.",
        "shot": {"label": "오늘의 출처", "dark": True,
                 "list": [s for _, _, s in shorts[:4]]},
    })
    return {"version": 1, "style": "series",
            "topic": main, "by": "템플릿 (수집 데이터의 제목만 사용)", "cards": cards}


# ---------------------------------------------------------------- LLM이 쓰는 문구 (API 모드 / 웹 LLM 답변)

# 구조화 출력용 평평한 스키마 — 화면 칸을 kind + items(key/value)로 받아 덱 형식으로 바꾼다
CARDS_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "cards": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["cover", "page", "closing"]},
                "name": {"type": "string", "description": "영문 소문자·숫자·하이픈"},
                "pill": {"type": "string"},
                "title": {"type": "string", "description": "\\n 줄바꿈, *강조*"},
                "desc": {"type": "string"},
                "say": {"type": "string", "description": "카드형 릴스 나레이션 한두 문장 (25자 안팎)"},
                "shot_kind": {"type": "string", "enum": ["rows", "list", "table", "checks", "text"]},
                "shot_label": {"type": "string", "description": "근거(예: 기사 제목 · 언론사 날짜). checks는 빈 문자열"},
                "shot_dark": {"type": "boolean"},
                "shot_items": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"key": {"type": "string", "description": "rows·table의 이름 칸, 나머지는 빈 문자열"},
                                   "value": {"type": "string"}},
                    "required": ["key", "value"], "additionalProperties": False}},
            },
            "required": ["type", "name", "pill", "title", "desc", "say", "shot_kind", "shot_label", "shot_dark", "shot_items"],
            "additionalProperties": False}},
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topic", "cards", "caption", "hashtags"],
    "additionalProperties": False,
}


def generate_cards(analysis, llm) -> dict:
    """API 모드: 카드뉴스 문구를 LLM으로 (규칙은 prompts/cards.md — 웹 LLM 요청 프롬프트·스킬과 같은 파일)."""
    from .analyzer import digest
    from .generator import _prompt

    main = analysis.insight.get("seo_keywords", {}).get("main") or analysis.keyword or ""
    system = _prompt("system") + "\n\n" + _prompt("cards")
    request = (f"아래 리서치로 인스타그램 피드 카드뉴스 문구를 만들어 줘. 메인 키워드: {main}\n"
               "화면 칸은 shot_kind + shot_items로 준다: rows·table은 key/value, list·checks는 value만, "
               "text는 shot_items 하나의 value에 문장.\n\n" + digest(analysis, with_urls=True))
    data = llm.json(system, request, CARDS_SCHEMA)
    cards = []
    for c in data.get("cards", []):
        items, kind = c.get("shot_items") or [], c.get("shot_kind")
        if kind in ("rows", "table"):
            value = [[i["key"], i["value"]] for i in items]
        elif kind == "text":
            value = items[0]["value"] if items else ""
        else:
            value = [i["value"] for i in items]
        shot = {kind: value} if value else {}
        if shot and c.get("shot_label"):
            shot["label"] = c["shot_label"]
        if shot and c.get("shot_dark"):
            shot["dark"] = True
        cards.append({k: v for k, v in {"type": c.get("type", "page"), "name": c.get("name"), "pill": c.get("pill"),
                                        "title": c.get("title", ""), "desc": c.get("desc"), "say": c.get("say"),
                                        "shot": shot}.items() if v})
    if not cards:
        raise CardError("LLM이 카드를 만들지 않았습니다")
    return {"version": 1, "style": "series",
            "topic": data.get("topic") or main, "by": llm.label, "cards": cards,
            "caption": data.get("caption", ""), "hashtags": data.get("hashtags", [])}


_FENCE_RE = re.compile(r"(?:```|~~~)[ \t]*(?:json)?[ \t]*\n(.*?)(?:```|~~~)", re.S)


def extract_deck(text: str) -> dict:
    """웹 LLM 답변(또는 JSON 파일)에서 카드뉴스 JSON을 꺼낸다 — 코드 블록 중 cards가 있는 것, 없으면 본문 전체."""
    candidates = _FENCE_RE.findall(text) + [text, text[text.find("{"):text.rfind("}") + 1]]
    for chunk in candidates:
        try:
            deck = json.loads(chunk)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(deck, dict) and isinstance(deck.get("cards"), list) and deck["cards"]:
            deck.setdefault("style", "series")
            deck.setdefault("by", "웹 LLM 답변")
            return deck
    raise CardError("카드뉴스 JSON(cards 배열이 든 코드 블록)을 찾지 못했습니다")


def _headline(body: str, keyword: str, lo: int = 8, hi: int = 20) -> str:
    """제목을 쉼표로 나눠 키워드 낱말이 가장 많이 든 조각(lo~hi자)을 고른다. 없으면 ''."""
    words = [w for w in keyword.split() if len(w) >= 2]
    best, hits = "", 0
    for seg in (x.strip() for x in re.split(r"[,，]", body)):
        n = sum(w in seg for w in words)
        if lo <= len(seg) <= hi and n > hits:
            best, hits = seg, n
    return best


def _wrap(text: str, width: int) -> str:
    """단어 경계에서 width자 이내로, 줄 길이를 고르게 나눈다 — 끝줄에 한두 단어만 떨어지지 않게.
    렌더러의 어색한 줄바꿈 검사는 손으로 끊은 줄(<br>)은 넘긴다."""
    n = len(_greedy(text, width))
    fits = [c for c in (_greedy(text, w) for w in range(max(1, -(-len(text) // n)), width + 1)) if len(c) <= n]
    return "\n".join(next((c for c in fits if len(c[-1]) > 3), fits[0] if fits else [text]))


def _greedy(text: str, width: int) -> list[str]:
    """단어 경계에서 width자 이내로 채운다 (한 단어가 width보다 길면 그대로)."""
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + [cur] if cur else lines


def _emphasize_last(text: str) -> str:
    lines = text.split("\n")
    lines[-1] = f"*{lines[-1]}*"
    return "\n".join(lines)


# ---------------------------------------------------------------- cards.html


def build_html(deck: dict, set_dir: Path) -> str:
    style = deck.get("style", "series")
    if style not in STYLES:
        raise CardError(f"지원하지 않는 스타일: {style} (지금은 {', '.join(STYLES)})")
    channel = deck.get("channel") or default_channel()
    if not re.fullmatch(r"[a-z0-9]+", channel):
        raise CardError(f"채널 이름은 영문 소문자·숫자만: {channel}")
    cards = deck.get("cards") or []
    if not cards:
        raise CardError("cards가 비어 있습니다")
    if len(cards) > 20:
        raise CardError(f"인스타그램 한도는 20장입니다 (지금 {len(cards)}장)")
    total = len(cards)
    body = "\n\n".join(_card(c, i, total, set_dir) for i, c in enumerate(cards))
    title = html.escape(deck.get("topic") or "카드뉴스")
    return f"""<!doctype html>
<html lang="ko" data-channel="{channel}">
<head>
<meta charset="utf-8">
<title>{title}</title>
<link rel="stylesheet" href="/__engine/fonts.css">
<link rel="stylesheet" href="/__engine/base.css">
<link rel="stylesheet" href="/__kit/{channel}/{channel}.css">
<!-- trend-content-agent가 {html.escape(deck.get('by') or '카드 문구 JSON')}로 만든 파일. 고칠 땐 _cards.json을 고치고 다시 굽는다 -->
</head>
<body>

{body}

</body>
</html>
"""


def _card(c: dict, i: int, total: int, set_dir: Path) -> str:
    kind = c.get("type", "page")
    name = re.sub(r"[^a-z0-9-]", "", (c.get("name") or f"card-{i + 1}").lower()) or f"card-{i + 1}"
    cls = "card cover" if kind == "cover" else "card"
    parts = ['  <div class="bar" data-motion="none"><span data-token="name"></span><span data-page></span></div>']
    if kind != "cover" and c.get("pill"):
        parts.append(f'  <span class="pill">{_esc(c["pill"])}</span>')
    tag = "h1" if kind == "cover" else "h2"
    parts.append(f"  <{tag}>{_inline(c.get('title', ''), 'mark' if kind == 'cover' else 'em')}</{tag}>")
    if c.get("desc"):
        parts.append(f'  <p class="desc">{_inline(c["desc"], "b")}</p>')
    if c.get("shot"):
        parts.append(_shot(c["shot"], set_dir))
    if c.get("dots"):
        parts.append('  <ul class="dots">' + "".join(f"<li>{_esc(d)}</li>" for d in c["dots"][:3]) + "</ul>")
    prog = "".join('<i class="on"></i>' if k <= i else "<i></i>" for k in range(total))
    tail = ('<span class="handle" data-token="handle"></span>' if kind == "closing"
            else '<span class="swipe">밀어서 보기 →</span>')
    parts.append(f'  <div class="end" data-motion="none"><div class="prog">{prog}</div>{tail}</div>')
    return f'<section class="{cls}" data-name="{name}">\n' + "\n".join(parts) + "\n</section>"


def _shot(shot: dict, set_dir: Path) -> str:
    kinds = [k for k in SHOT_KINDS if shot.get(k)]
    if len(kinds) != 1:
        raise CardError(f"shot에는 {'/'.join(SHOT_KINDS)} 중 하나만: {list(shot)}")
    kind = kinds[0]
    dark = " dark" if shot.get("dark") else ""
    chrome = (f'<div class="chrome"><b></b><b></b><b></b><span>{_esc(shot["label"])}</span></div>'
              if shot.get("label") else "")
    v = shot[kind]
    if kind == "rows":
        inner = '<div class="body"><div class="rows">' + "".join(
            f"<div><b>{_esc(a)}</b><span>{_inline(b, 'b')}</span></div>" for a, b in v) + "</div></div>"
    elif kind == "list":
        inner = '<div class="body"><ul class="raw">' + "".join(f"<li>{_inline(x, 'b')}</li>" for x in v) + "</ul></div>"
    elif kind == "table":
        inner = '<div class="body"><table class="out">' + "".join(
            f"<tr><th>{_esc(a)}</th><td>{_inline(b, 'b')}</td></tr>" for a, b in v) + "</table></div>"
    elif kind == "checks":
        inner = '<div class="body fill"><ul class="checks">' + "".join(
            f"<li><i>{CHECK_SVG}</i>{_esc(x)}</li>" for x in v) + "</ul></div>"
    elif kind == "text":
        inner = f'<div class="body"><div class="ask">{_inline(v, "span class=slot")}</div></div>'
    else:  # image: 세트 폴더 images/로 복사해 화면을 꽉 채운다
        src = Path(v) if Path(v).is_absolute() else PROJECT_DIR / v
        if not src.is_file():
            raise CardError(f"그림 파일이 없습니다: {v}")
        (set_dir / "images").mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, set_dir / "images" / src.name)
        inner = (f'<div class="body fill" style="padding:0"><img src="images/{html.escape(src.name)}" alt="" '
                 f'style="width:100%;height:100%;object-fit:cover;display:block"></div>')
    return f'  <div class="shot{dark}">{chrome}{inner}</div>'


def _esc(text) -> str:
    return html.escape(str(text))


def _inline(text, tag: str) -> str:
    """이스케이프 후 `*강조*` → <tag>, `\\n` → <br>."""
    open_tag, close = f"<{tag}>", f"</{tag.split()[0]}>"
    if tag == "span class=slot":
        open_tag = '<span class="slot">'
    out = re.sub(r"\*([^*\n]+)\*", lambda m: f"{open_tag}{m.group(1)}{close}", _esc(text))
    return out.replace("\n", "<br>")


# ---------------------------------------------------------------- 굽기


def engine_dir() -> Path:
    custom = os.getenv("CARDNEWS_ENGINE")
    if custom:
        p = Path(custom)
        return p if p.is_absolute() else (PROJECT_DIR / p).resolve()
    local = PROJECT_DIR / ".claude" / "skills" / "cardnews-engine" / "scripts"  # 프로젝트 스킬 (기본)
    glob_ = Path.home() / ".claude" / "skills" / "cardnews-engine" / "scripts"
    return local if local.is_dir() or not glob_.is_dir() else glob_


def default_channel() -> str:
    """카드 머리글·색을 정하는 채널 키트: .env의 CARDNEWS_CHANNEL > 무모한도전 키트(cardnews-mumohan, 이 저장소) > starter."""
    if os.getenv("CARDNEWS_CHANNEL"):
        return os.environ["CARDNEWS_CHANNEL"]
    skills = engine_dir().parent.parent
    return "mumohan" if (skills / "cardnews-mumohan" / "kit" / "kit.json").is_file() else "starter"


def check_engine() -> tuple[bool, str]:
    eng = engine_dir()
    if not shutil.which("node"):
        return False, "Node.js가 없습니다 (node 18 이상)"
    if not (eng / "render.cjs").is_file():
        return False, f"cardnews-engine 스킬이 없습니다: {eng} (README '카드뉴스' 설치 참고)"
    if not (eng / "node_modules" / "playwright-core").is_dir():
        return False, f"playwright-core가 없습니다 — {eng} 에서 npm install 을 한 번 실행하세요"
    return True, str(eng)


def render_deck(deck: dict, set_dir: Path, timeout: int = 300) -> CardResult:
    ok, why = check_engine()
    if not ok:
        raise CardError(why)
    set_dir.mkdir(parents=True, exist_ok=True)
    (set_dir / "cards.html").write_text(build_html(deck, set_dir), encoding="utf-8")
    (set_dir / "cards.json").write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows에서 세트 폴더 경로에 한글이 있으면 렌더러(node)가 메시지 없이 죽는다(0xC0000409)
    # → 영문 임시 폴더에서 굽고 결과(out/, preview/)만 옮긴다
    with tempfile.TemporaryDirectory(prefix="cardnews-") as tmp:
        work = Path(tmp) / "set"
        shutil.copytree(set_dir, work, ignore=shutil.ignore_patterns("out", "preview"))
        proc = subprocess.run(["node", str(engine_dir() / "render.cjs"), str(work)], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout).strip().splitlines()
            raise CardError("렌더 실패: " + (msg[-1] if msg else f"종료 코드 {proc.returncode}"))
        for sub in ("out", "preview"):
            shutil.rmtree(set_dir / sub, ignore_errors=True)
            if (work / sub).is_dir():
                shutil.copytree(work / sub, set_dir / sub)
    warnings = [ln.strip()[2:] for ln in proc.stdout.splitlines() if ln.strip().startswith("! ")]
    pngs = sorted((set_dir / "out").glob("*.png"))
    sheet = set_dir / "preview" / "sheet.png"
    return CardResult(set_dir, pngs, sheet if sheet.exists() else None, warnings)


def load_deck(path: Path) -> dict:
    try:
        deck = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise CardError(f"카드 문구 파일을 읽지 못함 ({path.name}): {e}") from e
    if not isinstance(deck, dict) or not isinstance(deck.get("cards"), list):
        raise CardError(f"{path.name}: 최상위에 cards 배열이 있어야 합니다")
    return deck
