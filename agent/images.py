"""이슈별 이미지 생성용 프롬프트(영문) — 블로그 썸네일 / 릴스 커버.

Midjourney·DALL·E·Imagen·Stable Diffusion 등에 그대로 붙여 넣을 수 있게 만든다.
이미지 모델은 한글 글자를 잘 못 그리므로 글자는 이미지에 넣지 않고(`no text`),
얹을 한글 문구(overlay_text_ko)를 따로 뽑아 편집 단계(캔바·미리캔버스 등)에서 넣도록 한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from .analyzer import Analysis, digest
from .llm import LLM, LLMError

USAGES = {
    "blog_thumbnail": ("네이버 블로그 썸네일", "1:1"),
    "reels_cover": ("인스타 릴스 커버", "9:16"),
}

IMAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "prompts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_index": {"type": "integer"},
                    "usage": {"type": "string", "enum": list(USAGES)},
                    "prompt_en": {"type": "string",
                                  "description": "영문 프롬프트: 피사체, 장면, 구도, 조명, 색감, 스타일, 카메라/렌즈"},
                    "negative_prompt": {"type": "string"},
                    "style": {"type": "string", "description": "photorealistic / flat illustration / 3D 등"},
                    "overlay_text_ko": {"type": "string", "description": "편집 단계에서 얹을 한글 문구 (15자 이내)"},
                    "alt_text_ko": {"type": "string", "description": "네이버 이미지 대체텍스트 (메인 키워드 포함)"},
                },
                "required": ["issue_index", "usage", "prompt_en", "negative_prompt", "style",
                             "overlay_text_ko", "alt_text_ko"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["prompts"],
    "additionalProperties": False,
}

SYSTEM = (
    "너는 SNS 콘텐츠용 이미지 디렉터다. 이슈마다 블로그 썸네일(1:1)과 릴스 커버(9:16) 이미지 생성 프롬프트를 영문으로 쓴다. "
    "프롬프트는 한 문단, 구체적인 피사체·장면·구도·조명·색감·스타일을 담고, 썸네일·커버는 문구를 얹을 여백(negative space)을 "
    "의도적으로 남긴다. 이미지 안에 글자·로고가 생기지 않게 'no text, no logo'를 포함한다. "
    "실존 인물·상표·특정 언론 사진을 재현하지 말고 일반화된 장면으로 표현한다. 사건·사고 이슈는 자극적 묘사를 피한다. "
    "beautiful·stunning·cinematic·4K 같은 막연한 말은 쓰지 말고 조명·렌즈·샷 크기를 이름으로 쓴다"
    "(예: golden-hour backlight, 35mm shallow depth of field, overhead flat lay). "
    "'피해야 할 행동'을 다루는 이슈는 위험한 모습이 아니라 올바른 모습을 그린다."
)

NEGATIVE_DEFAULT = "text, letters, watermark, logo, signature, blurry, low quality, distorted hands, extra fingers"


@dataclass
class ImagePrompt:
    issue_index: int
    issue_title: str
    usage: str
    aspect_ratio: str
    prompt_en: str
    negative_prompt: str
    style: str
    overlay_text_ko: str
    alt_text_ko: str


def generate_image_prompts(analysis: Analysis, llm: LLM | None, max_issues: int = 3) -> tuple[list[ImagePrompt], str]:
    """(프롬프트 목록, 생성 주체). LLM이 없거나 실패하면 번역 없이 채운 템플릿."""
    issues = analysis.issues[:max_issues]
    if not issues:
        return [], "-"
    if llm:
        request = (
            f"아래 리서치의 이슈 [0]~[{len(issues) - 1}] 각각에 대해 usage별(blog_thumbnail, reels_cover) "
            f"프롬프트를 하나씩, 총 {len(issues) * len(USAGES)}개 만들어 줘. "
            f"메인 키워드: {analysis.insight.get('seo_keywords', {}).get('main', analysis.keyword or '')}\n\n"
            + digest(analysis, max_issues=len(issues))
        )
        try:
            data = llm.json(SYSTEM, request, IMAGE_SCHEMA)
            out = []
            for p in data.get("prompts", []):
                i = p["issue_index"]
                if not (0 <= i < len(issues)) or p["usage"] not in USAGES:
                    continue
                out.append(ImagePrompt(
                    issue_index=i, issue_title=issues[i].title, usage=p["usage"],
                    aspect_ratio=USAGES[p["usage"]][1], prompt_en=p["prompt_en"],
                    negative_prompt=p["negative_prompt"] or NEGATIVE_DEFAULT, style=p["style"],
                    overlay_text_ko=p["overlay_text_ko"], alt_text_ko=p["alt_text_ko"],
                ))
            out.sort(key=lambda x: (x.issue_index, list(USAGES).index(x.usage)))
            return out, llm.label
        except (LLMError, ValueError, KeyError) as e:
            analysis.notes.append(f"이미지 프롬프트 LLM 생성 실패 → 템플릿 사용: {e}")
    return _template(analysis, issues), "템플릿 (LLM 미사용 — 피사체를 영어로 바꿔 쓰세요)"


def _template(analysis: Analysis, issues) -> list[ImagePrompt]:
    main = analysis.insight.get("seo_keywords", {}).get("main", analysis.keyword or "")
    scenes = {
        "blog_thumbnail": ("Square editorial photo about {subject}, centered main subject, clean background with "
                           "generous negative space at the top for a headline, soft natural daylight, warm tones, "
                           "shallow depth of field, 35mm lens, high detail, no text, no logo"),
        "reels_cover": ("Vertical 9:16 cinematic shot about {subject}, subject in the lower two-thirds, empty sky or "
                        "wall in the upper third for caption, golden hour lighting, vivid but natural colors, "
                        "handheld smartphone look, no text, no logo"),
    }
    out = []
    for i, iss in enumerate(issues):
        for usage, template in scenes.items():
            out.append(ImagePrompt(
                issue_index=i, issue_title=iss.title, usage=usage, aspect_ratio=USAGES[usage][1],
                prompt_en=template.format(subject=f'"{iss.title}" (← 영어로 바꿔 넣기)'),
                negative_prompt=NEGATIVE_DEFAULT, style="photorealistic",
                overlay_text_ko=main[:15], alt_text_ko=f"{main} {iss.title[:30]}",
            ))
    return out
