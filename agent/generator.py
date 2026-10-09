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
    return text.replace("{{cast}}", _cast()) if "{{cast}}" in text else text


def _cast() -> str:
    """출연 캐릭터 명단 (prompts/characters.json) — 카드 규칙·요청 프롬프트에 끼워 넣는다."""
    from .characters import all_characters

    rows = [f"  - `{k}` {v['name']}{' (이미지 있음)' if v.get('images') else ''}: {v['persona']}"
            for k, v in all_characters().items()]
    return "  출연 캐릭터:\n" + "\n".join(rows)


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
