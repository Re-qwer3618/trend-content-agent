"""LLM 제작 요청 프롬프트 — API를 부르지 않고, 사용자가 ChatGPT·Claude.ai·Gemini 웹에 붙여 넣을 프롬프트를 만든다.

API 크레딧이 부족하거나 비용을 아끼고 싶을 때(GENERATION_MODE=prompt) 쓰며,
auto 모드에서는 API 생성이 실패한 포맷만 프롬프트로 대신한다.
프롬프트는 수집 데이터·출처 URL을 모두 담은 '한 번에 붙여 넣는' 형태로, 기획서 → 완성본을 한 대화에서 끝내게 한다.
작성 지침은 API 모드와 같은 agent/prompts/*.md 를 재사용하므로 지침을 고치면 양쪽에 같이 반영된다.
"""
from __future__ import annotations

from dataclasses import dataclass

from .analyzer import Analysis, digest
from .generator import DRAFT_PROMPT, FORMATS, STAGE_NAMES, _prompt, _render
from .images import USAGES

INSIGHT_NOTE = ("아래 '리서치 인사이트'는 규칙 기반으로 자동 추출한 초안이다. 데이터를 보고 더 나은 메인 키워드·관점이 있으면 "
                "고쳐서 써도 된다.")


@dataclass
class RequestPrompt:
    key: str          # blog / reels / images
    title: str
    text: str
    tip: str          # 어디에 붙여 넣으면 좋은지


def _content_prompt(analysis: Analysis, fmt: str) -> str:
    plan_name, draft_name = STAGE_NAMES[fmt]
    system = _prompt("system").strip()
    plan_part = _render(_prompt(fmt), analysis, with_urls=True).strip()
    # 완성본 지침에서는 데이터를 다시 넣지 않고(중복), 작업 1의 결과를 이어서 쓰게 한다
    draft_part = (_prompt(DRAFT_PROMPT[fmt])
                  .replace("{{plan}}", f"(작업 1에서 작성한 {plan_name})")
                  .replace("{{insight}}", "(위 작업 1의 리서치 인사이트 참고)")
                  .replace("{{digest}}", "(위 작업 1의 데이터와 URL 참고)")).strip()
    # 공통 규칙(include)이 작업 1에 이미 들어 있으면 작업 2에서는 빼서 한 번만 싣는다
    rules = _prompt("visual_rules").strip()
    if rules in plan_part:
        draft_part = draft_part.replace(rules, "(위 작업 1의 'AI 영상·이미지 생성 프롬프트 규칙' 참고)")
    return _fence_safe("\n\n".join([
        f"# 역할\n{system}",
        f"# 진행 방식\n두 작업을 순서대로 한 답변에 모두 출력해 줘. 웹 검색을 쓸 수 있으면 켜고 원문을 확인해 줘.\n{INSIGHT_NOTE}",
        f"# 작업 1: {FORMATS[fmt]} {plan_name}\n\n{plan_part}",
        f"# 작업 2: {FORMATS[fmt]} {draft_name}\n\n{draft_part}",
    ]))


def _channels_prompt(analysis: Analysis) -> str:
    """인스타 피드(카드뉴스) + 유튜브 — API 생성 포맷은 아니고 웹 LLM 요청 프롬프트로만 만든다."""
    return _fence_safe("\n\n".join([
        f"# 역할\n{_prompt('system').strip()}",
        f"# 진행 방식\n웹 검색을 쓸 수 있으면 켜고 원문을 확인해 줘.\n{INSIGHT_NOTE}",
        f"# 작업\n\n{_render(_prompt('channels'), analysis, with_urls=True).strip()}",
    ]))


def _fence_safe(text: str) -> str:
    """프롬프트 안의 ``` 를 ~~~ 로 — 리포트·Notion에서 프롬프트 자체를 코드 블록으로 감쌀 때 블록이 깨지지 않게.
    LLM은 ~~~ 도 같은 코드 펜스로 읽는다."""
    return text.replace("```", "~~~")


def _images_prompt(analysis: Analysis, max_issues: int) -> str:
    issues = analysis.issues[:max_issues]
    main = analysis.insight.get("seo_keywords", {}).get("main", analysis.keyword or "")
    usages = ", ".join(f"{k}({v[0]}, {v[1]})" for k, v in USAGES.items())
    return "\n\n".join([
        "# 역할\n너는 SNS 콘텐츠용 이미지 디렉터다.",
        "# 작업\n"
        f"아래 이슈 [0]~[{len(issues) - 1}] 각각에 대해 용도별({usages}) 이미지 생성 프롬프트를 영문으로 하나씩 써 줘.\n"
        "- 한 문단, 구체적인 피사체·장면·구도·조명·색감·스타일. 문구를 얹을 여백(negative space)을 남길 것\n"
        "- 이미지 안에 글자·로고가 생기지 않게 'no text, no logo' 포함. 실존 인물·상표는 일반화해서 표현\n"
        "- beautiful·stunning·cinematic·4K 같은 막연한 말 대신 조명·렌즈·샷 크기를 이름으로 "
        "(예: golden-hour backlight, 35mm shallow depth of field, overhead flat lay)\n"
        "- '피해야 할 행동' 이슈는 올바른 모습을 그린다 (예: 텐트 안 난로 → 텐트 밖 화로 + 환기창 연 텐트)\n"
        f"- 메인 키워드: {main}",
        "# 출력 형식 (표)\n| 이슈 | 용도 | 비율 | 영문 프롬프트 | 네거티브 프롬프트 | 얹을 한글 문구(15자 이내) | 대체텍스트(alt, 메인 키워드 포함) |",
        "# 데이터\n" + digest(analysis, max_issues=len(issues)),
    ])


def build_request_prompts(analysis: Analysis, formats: list[str], image_issues: int = 3,
                          include_images: bool = True) -> list[RequestPrompt]:
    out = []
    for fmt in formats:
        plan_name, draft_name = STAGE_NAMES[fmt]
        out.append(RequestPrompt(
            fmt, f"{FORMATS[fmt]} — {plan_name} + {draft_name}", _content_prompt(analysis, fmt),
            "웹 검색이 되는 ChatGPT(검색 켜기)·Claude.ai·Gemini에 그대로 붙여 넣기. 긴 답변이 끊기면 '계속'이라고 입력"))
    if formats and analysis.issues:  # 블로그·릴스와 같은 주제로 나머지 채널도
        out.append(RequestPrompt(
            "channels", "인스타그램 피드(카드뉴스) + 유튜브", _channels_prompt(analysis),
            "블로그·릴스 요청과 같은 대화에 이어서 붙여 넣으면 메시지·CTA를 맞추기 쉬움"))
    if include_images and analysis.issues:
        out.append(RequestPrompt(
            "images", "이미지 생성 프롬프트 (영문)", _images_prompt(analysis, image_issues),
            "결과 표의 영문 프롬프트를 이미지 생성기에 붙여 넣기. ChatGPT·Gemini는 그 대화에서 바로 이미지도 만들 수 있음"))
    return out
