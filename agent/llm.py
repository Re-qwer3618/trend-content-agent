"""LLM 공통 인터페이스. Claude / Gemini 중 하나를 고르고, 둘 다 없으면 None(템플릿 모드).

- text(system, prompt, web_search=False) -> 마크다운 등 자유 텍스트 (web_search: 웹 검색으로 사실 확인하며 작성)
- json(system, prompt, schema) -> JSON 스키마를 지키는 dict
"""
from __future__ import annotations

import json
from typing import Protocol

from .config import Settings


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    label: str

    def text(self, system: str, prompt: str, web_search: bool = False) -> str: ...

    def json(self, system: str, prompt: str, schema: dict) -> dict: ...


class ClaudeLLM:
    # 안전 분류기가 요청을 거절하면 서버가 다른 모델로 자동 재시도 (거절 범주별로 알아서 라우팅)
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, settings: Settings):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.effort = settings.claude_effort
        self.label = f"Claude ({self.model}, effort={self.effort})"
        self.fatal = ""

    # 서버측 웹 검색: Anthropic 서버가 검색을 수행하고 결과를 근거로 답한다 (검색 1,000건당 $10 + 토큰)
    WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6,
                       "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"}}

    def _run(self, system: str, prompt: str, output_format: dict | None = None,
             web_search: bool = False) -> str:
        if self.fatal:  # 크레딧 부족·인증 실패는 재시도해도 같으므로 바로 실패
            raise LLMError(self.fatal)
        output_config: dict = {"effort": self.effort}
        if output_format:
            output_config["format"] = output_format
        messages: list = [{"role": "user", "content": prompt}]
        extra = {"tools": [self.WEB_SEARCH_TOOL]} if web_search else {}
        try:
            # 서버 도구가 오래 돌면 pause_turn으로 끊겨 오므로, 받은 내용을 붙여 이어서 요청한다
            for _ in range(4):
                # 원고는 출력이 길어 스트리밍으로 받아 HTTP 타임아웃을 피한다
                with self.client.beta.messages.stream(
                    model=self.model,
                    max_tokens=64000,
                    system=system,
                    messages=messages,
                    output_config=output_config,
                    betas=[self.FALLBACK_BETA],
                    fallbacks="default",
                    **extra,
                ) as stream:
                    msg = stream.get_final_message()
                if msg.stop_reason != "pause_turn":
                    break
                messages = [messages[0], {"role": "assistant", "content": msg.content}]
        except self._anthropic.AuthenticationError as e:
            self.fatal = "Claude 인증 실패 — ANTHROPIC_API_KEY 확인"
            raise LLMError(self.fatal) from e
        except self._anthropic.RateLimitError as e:
            raise LLMError("Claude 요청 한도 초과(429) — 잠시 후 다시 실행") from e
        except self._anthropic.APIStatusError as e:
            detail = (e.body or {}).get("error", {}).get("message", "") if isinstance(e.body, dict) else ""
            if "credit balance" in detail:
                self.fatal = "Anthropic 크레딧 잔액 부족 — platform.claude.com 결제(Billing)에서 충전 필요"
                raise LLMError(self.fatal) from e
            raise LLMError(f"Claude API 오류 {e.status_code}: {detail or e.message}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError("Claude 연결 실패 (네트워크)") from e

        if msg.stop_reason == "refusal":
            category = getattr(msg.stop_details, "category", None) if msg.stop_details else None
            raise LLMError(f"Claude가 요청을 거절함 (category={category})")
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if msg.stop_reason == "max_tokens":
            raise LLMError("출력이 max_tokens에서 잘림")
        return text

    def text(self, system, prompt, web_search=False):
        return self._run(system, prompt, web_search=web_search)

    def json(self, system, prompt, schema):
        raw = self._run(system, prompt, {"type": "json_schema", "schema": schema})
        return json.loads(raw)


class GeminiLLM:
    def __init__(self, settings: Settings):
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model
        self.label = f"Gemini ({self.model})"
        self.fatal = ""

    def _run(self, system: str, prompt: str, schema: dict | None = None, web_search: bool = False) -> str:
        if self.fatal:
            raise LLMError(self.fatal)
        cfg: dict = {"system_instruction": system}
        if schema:
            cfg |= {"response_mime_type": "application/json", "response_json_schema": schema}
        if web_search:  # Google 검색 그라운딩
            cfg["tools"] = [self.types.Tool(google_search=self.types.GoogleSearch())]
        try:
            resp = self.client.models.generate_content(
                model=self.model, contents=prompt, config=self.types.GenerateContentConfig(**cfg)
            )
        except Exception as e:  # google-genai는 오류 타입이 버전마다 달라 메시지로 구분
            self.fatal = gemini_fatal_reason(str(e), self.model)
            raise LLMError(self.fatal or f"Gemini 오류: {str(e)[:300]}") from e
        if not resp.text:
            raise LLMError("Gemini 응답이 비어 있음 (안전 필터 차단 가능)")
        return resp.text.strip()

    def text(self, system, prompt, web_search=False):
        return self._run(system, prompt, web_search=web_search)

    def json(self, system, prompt, schema):
        return json.loads(self._run(system, prompt, schema))


def gemini_fatal_reason(message: str, model: str) -> str:
    """재시도해도 소용없는 Gemini 오류면 한 줄 설명, 아니면 빈 문자열."""
    if "credits are depleted" in message or message.startswith("402"):
        return "Gemini 선불 크레딧 소진(402) — ai.studio/projects 에서 결제 확인"
    if "API key not valid" in message or "API_KEY_INVALID" in message:
        return "Gemini API 키가 유효하지 않음 — GEMINI_API_KEY 확인"
    if message.startswith("404") and "model" in message.lower():
        return f"Gemini 모델 {model} 사용 불가(404) — .env의 GEMINI_MODEL 변경 필요"
    return ""


def get_llm(settings: Settings, provider: str | None = None) -> LLM | None:
    """provider: auto | claude | gemini | none"""
    p = (provider or settings.llm_provider or "auto").lower()
    if p == "none":
        return None
    if p == "claude" or (p == "auto" and settings.anthropic_api_key):
        if not settings.anthropic_api_key:
            raise LLMError("LLM_PROVIDER=claude 인데 ANTHROPIC_API_KEY가 없음")
        return ClaudeLLM(settings)
    if p == "gemini" or (p == "auto" and settings.gemini_api_key):
        if not settings.gemini_api_key:
            raise LLMError("LLM_PROVIDER=gemini 인데 GEMINI_API_KEY가 없음")
        return GeminiLLM(settings)
    if p != "auto":
        raise LLMError(f"알 수 없는 LLM_PROVIDER: {p}")
    return None
