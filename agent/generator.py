"""콘텐츠 생성: 네이버 블로그 / 인스타그램 릴스.

2단계로 만든다.
  1) 기획서 (prompts/blog.md, reels.md)        — 키워드 배치, 구성안, 스토리보드
  2) 완성본 (prompts/blog_draft.md, reels_script.md) — 기획서를 받아 발행용 본문 원고 / 컷별 촬영 대본
     수집 데이터가 헤드라인 위주라, 이 단계는 웹 검색으로 원문을 확인하며 쓴다 (--no-web 으로 끔).
LLM이 없거나 실패하면 1단계는 데이터로 채운 골격(템플릿), 2단계는 생략한다.
프롬프트 수정은 agent/prompts/ 의 마크다운 파일만 고치면 된다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .analyzer import Analysis, digest
from .llm import LLM, LLMError

PROMPT_DIR = Path(__file__).parent / "prompts"
FORMATS = {"blog": "네이버 블로그 포스팅", "reels": "인스타그램 릴스"}
STAGE_NAMES = {"blog": ("기획서", "발행용 본문 원고"), "reels": ("기획서", "촬영·편집 대본")}
DRAFT_PROMPT = {"blog": "blog_draft", "reels": "reels_script"}


@dataclass
class Plan:
    format: str
    title: str
    body: str                       # 1단계 기획서
    generated_by: str
    draft: str = ""                 # 2단계 완성본 (LLM 있을 때만)
    draft_by: str = ""


_INCLUDE_RE = re.compile(r"\{\{include:(\w+)\}\}")


def _prompt(name: str) -> str:
    """prompts/<name>.md. 본문의 {{include:파일}} 은 prompts/파일.md 내용으로 바꾼다(공통 규칙을 한 곳에서 관리)."""
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    text = _INCLUDE_RE.sub(lambda m: (PROMPT_DIR / f"{m.group(1)}.md").read_text(encoding="utf-8").strip(), text)
    if "{{cast}}" in text:
        text = text.replace("{{cast}}", _cast())
    if "{{examples}}" in text:
        text = text.replace("{{examples}}", _examples())
    return text.replace("{{refs}}", _refs()) if "{{refs}}" in text else text


def _cast() -> str:
    """출연 캐릭터 명단 (prompts/characters.json) — 카드 규칙·요청 프롬프트에 끼워 넣는다."""
    from .characters import all_characters

    rows = [f"  - `{k}` {v['name']}{' (이미지 있음)' if v.get('images') else ''}: {v['persona']}"
            for k, v in all_characters().items()]
    return "  출연 캐릭터:\n" + "\n".join(rows)


MAX_EXAMPLES = 2
CATEGORY: str | None = None  # 이번 실행의 카테고리 id (prompts/categories.json) — main이 set_category로 정한다


def set_category(cid: str | None) -> None:
    global CATEGORY
    CATEGORY = cid


def _category_name() -> str | None:
    from .categories import get

    return (get(CATEGORY) or {}).get("name")


def _examples() -> str:
    """본보기 카드 세트 (prompts/examples/ — run.bat --sync-notion이 노션 콘텐츠 예시 DB에서 내려받음).
    같은 카테고리의 채택 → 다른 카테고리 채택 → 같은 카테고리 후보 순으로 MAX_EXAMPLES개(후보는 1개).
    짜임·말투만 보여 주고 사실은 가져오지 못하게 못 박는다."""
    index_file = PROMPT_DIR / "examples" / "index.json"
    if not index_file.exists():
        return ""
    index = [x for x in json.loads(index_file.read_text(encoding="utf-8")) if x["file"].endswith(".json")]
    cat = _category_name()
    adopted = [x for x in reversed(index) if x["status"] == "채택"]
    picked = ([x for x in adopted if x.get("category") == cat] + [x for x in adopted if x.get("category") != cat])[:MAX_EXAMPLES]
    picked = picked or [x for x in reversed(index) if x["status"] == "후보" and (not cat or x.get("category") == cat)][:1]
    parts = []
    for x in picked:
        f = PROMPT_DIR / "examples" / x["file"]
        if not f.exists():
            continue
        deck = json.loads(f.read_text(encoding="utf-8"))
        deck = {k: deck[k] for k in ("topic", "host", "cards", "caption") if k in deck}
        parts.append(f"  ▸ {x['title']} ({x['status']} · 훅 {x.get('hook') or '-'} · {', '.join(x.get('topics', []))})"
                     + (f" — {x['why']}" if x.get("why") else "")
                     + "\n```json\n" + json.dumps(deck, ensure_ascii=False, separators=(",", ":")) + "\n```")
    if not parts:
        return ""
    return ("- 본보기 세트(노션 콘텐츠 예시 DB): 장 흐름·훅·캐릭터 쓰임·`say` 길이·캡션 짜임만 참고한다. "
            "**사실·수치·고유명사·문구는 가져오지 않는다** — 이번 주제의 근거로만 쓴다.\n" + "\n".join(parts))


MAX_REFS = 12
REF_LINES = 5  # 사례마다 앞 5줄(카테고리·근거 / 릴스 / 카드 / 훅 / 주의)만 — 카테고리별 패턴을 다 싣고 주제에 맞는 걸 고르게 한다


def _refs() -> str:
    """외부 사례(다른 계정)의 구조 요약 — 채택만, 최근 MAX_REFS개, 사례마다 REF_LINES줄. 카드(cards.md)와 릴스(reels.md) 지침에 들어간다."""
    index_file = PROMPT_DIR / "examples" / "index.json"
    if not index_file.exists():
        return ""
    index = json.loads(index_file.read_text(encoding="utf-8"))
    refs = [x for x in reversed(index) if x["status"] == "채택" and x["file"].endswith(".md")]
    cat = _category_name()
    same = [x for x in refs if cat and x.get("category") == cat]
    parts = []
    for x in (same or refs)[:MAX_REFS]:  # 카테고리가 정해지면 그 카테고리 것만 전부, 아니면 모든 카테고리를 앞 몇 줄씩
        f = PROMPT_DIR / "examples" / x["file"]
        if f.exists():
            lines = f.read_text(encoding="utf-8").strip().splitlines()
            parts.append(f"  ▸ {x['title']} (훅 {x.get('hook') or '-'} · {', '.join(x.get('formats', []))})\n"
                         + "\n".join("    " + line for line in (lines if same else lines[:REF_LINES])))
    guide = _category_guide()
    if not parts:
        return guide
    how = ("이번 카테고리의 패턴" if same else "이번 주제와 **같은 카테고리**의 패턴을 골라")
    return (guide + "- 참고 사례(다른 계정, 노션 콘텐츠 예시 DB의 외부 사례): " + how + " **구조만** 본받는다 — "
            "장 수·길이·배치·강조 방식·마무리 장치. "
            "그 계정의 문구·사진·로고·캐릭터는 쓰지 않고, 우리 캐릭터와 채널 키트 디자인으로 바꾼다.\n" + "\n".join(parts))


def _category_guide() -> str:
    """카테고리 기본값 한 묶음(진행·리액션 캐릭터, 형식, 릴스 길이, 나레이션 톤)."""
    from .categories import get

    c = get(CATEGORY)
    if not c:
        return ""
    fmt = "짧은 형식(2~3장, cards_short 규칙)" if c["format"] == "short" else "기본 형식(5~8장)"
    return (f"- 카테고리: **{c['name']}** — 진행 `{c['host']}`, 리액션 `{c['reaction']}`, {fmt}, 릴스 {c['reel']}.\n"
            f"  나레이션 톤(`say`를 쓸 때): {c['tone']}\n")


def _render(template: str, analysis: Analysis, plan: str = "", with_urls: bool = False) -> str:
    insight = json.dumps(analysis.insight, ensure_ascii=False, indent=2)
    return (template
            .replace("{{plan}}", plan)
            .replace("{{insight}}", f"## 리서치 인사이트\n```json\n{insight}\n```")
            .replace("{{digest}}", digest(analysis, with_urls=with_urls)))


def generate(analysis: Analysis, fmt: str, llm: LLM | None,
             draft: bool = True, web_search: bool = True, log=print) -> Plan:
    if fmt not in FORMATS:
        raise ValueError(f"알 수 없는 포맷: {fmt} (가능: {list(FORMATS)})")
    plan_name, draft_name = STAGE_NAMES[fmt]
    if not llm:
        body = (_blog_template if fmt == "blog" else _reels_template)(analysis)
        return Plan(fmt, FORMATS[fmt], body, "템플릿 (LLM 미사용)")

    system = _prompt("system")
    try:
        log(f"  · {plan_name}")
        plan = Plan(fmt, FORMATS[fmt], llm.text(system, _render(_prompt(fmt), analysis, with_urls=True)), llm.label)
    except LLMError as e:
        analysis.notes.append(f"{FORMATS[fmt]} {plan_name} LLM 생성 실패 → 템플릿 사용: {e}")
        return Plan(fmt, FORMATS[fmt], (_blog_template if fmt == "blog" else _reels_template)(analysis),
                    "템플릿 (LLM 실패)")

    if draft:
        try:
            log(f"  · {draft_name}{' (웹 검색으로 원문 확인)' if web_search else ''}")
            prompt = _render(_prompt(DRAFT_PROMPT[fmt]), analysis, plan=plan.body, with_urls=True)
            plan.draft = llm.text(system, prompt, web_search=web_search)
            plan.draft_by = llm.label + (" + 웹 검색" if web_search else "")
        except LLMError as e:
            analysis.notes.append(f"{FORMATS[fmt]} {draft_name} 생성 실패: {e}")
    return plan


# ---------------------------------------------------------------- LLM 없을 때의 골격


def _sources(analysis: Analysis, n: int = 5) -> list[str]:
    out = []
    for iss in analysis.issues[:3]:
        for it in iss.items[:2]:
            if it.url:
                out.append(f"- [{it.title}]({it.url}) — {it.source}")
    return out[:n] or ["- (수집된 링크 없음)"]


def _blog_template(a: Analysis) -> str:
    ins = a.insight
    seo = ins["seo_keywords"]
    main, subs, tails = seo["main"], seo["sub"], seo["long_tail"]
    issues = a.issues[:3]
    sections = "\n".join(
        f"| H2-{i + 1} | {iss.title[:40]} | 이슈 요약 + 내 관점 정리 | {', '.join(subs[i * 2:i * 2 + 2]) or main} | 500자 |"
        for i, iss in enumerate(issues)
    )
    return f"""### 1. 포스팅 개요
- 메인 키워드: **{main}**
- 서브 키워드: {', '.join(subs) or '-'}
- 롱테일 키워드: {', '.join(tails)}

### 2. 제목 후보
1. {main} 총정리: {subs[0] if subs else '핵심'}부터 {subs[1] if len(subs) > 1 else '실전 팁'}까지
2. 요즘 뜨는 {main}, 지금 알아야 할 3가지
3. {main} {subs[0] if subs else ''} 직접 비교해 봤습니다

### 3. SEO 키워드 배치 맵
| 위치 | 넣을 키워드 | 작성 가이드 |
|---|---|---|
| 제목 | {main} | 앞쪽에 배치, 25~35자 |
| 첫 문단 | {main}, {subs[0] if subs else ''} | 첫 2~3문장 안에 자연스럽게 |
| 소제목 | {', '.join(subs[:4])} | 소제목마다 서브 키워드 1개 |
| 본문 | {main} | 4~6회, 억지 반복 금지 |
| 이미지 | {main} | 대체텍스트·파일명에 키워드 |
| 태그 | {', '.join([main, *subs][:10])} | 10개 |

### 4. 본문 구성안 (목표 2,000~2,500자)
| 구간 | 소제목 | 담을 내용 | 키워드 | 분량 |
|---|---|---|---|---|
| 도입 | (없음) | 왜 지금 {main}인지 — 최근 이슈 한 줄 | {main} | 300자 |
{sections}
| 마무리 | 한눈에 정리 | 요약 표 + 댓글 유도 질문 | {main} | 300자 |

### 5. 참고 출처
{chr(10).join(_sources(a))}

> LLM 키(ANTHROPIC_API_KEY 또는 GEMINI_API_KEY)를 설정하면 제목·본문 구성이 이슈 맥락에 맞게 상세히 작성됩니다.
"""


def _reels_template(a: Analysis) -> str:
    ins = a.insight
    main = ins["seo_keywords"]["main"]
    top = a.issues[0].title if a.issues else main
    tags = " ".join(ins["hashtags"][:13])
    return f"""### 1. 콘셉트
- 주제: {ins['main_topic']}
- 핵심 이슈: {top}

### 2. 3초 훅 후보
1. 질문형 — 자막: "{main}, 아직도 모르세요?"
2. 숫자형 — 자막: "{main} 핵심 3가지"
3. 결과 먼저 — 완성 장면/결론을 첫 컷에 보여주고 "어떻게?"로 연결

### 3. 스토리보드 (25초)
| 컷 | 시간 | 화면 | 자막 | 나레이션 | 효과 |
|---|---|---|---|---|---|
| 1 | 0~3초 | 클로즈업 + 큰 자막 | 훅 문구 | 훅 문구 | 줌인 |
| 2 | 3~9초 | 이슈 화면/자료 | 포인트 1 | - | 컷 전환 |
| 3 | 9~15초 | 시연/비교 | 포인트 2 | - | 컷 전환 |
| 4 | 15~21초 | 결과 | 포인트 3 | - | 효과음 |
| 5 | 21~25초 | 정면 + 텍스트 | 저장해두세요 | 저장 유도 | 페이드 |

### 4. 캡션 & 해시태그
{top} — 지금 화제인 이유와 핵심만 30초로 정리했어요. 저장해두고 필요할 때 꺼내 보세요!

{tags}

### 5. 참고 출처
{chr(10).join(_sources(a))}

> LLM 키를 설정하면 자막 대본 전문과 시각적 연출 가이드가 이슈에 맞게 작성됩니다.
"""
