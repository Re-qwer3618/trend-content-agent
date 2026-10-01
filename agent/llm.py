"""LLM 공통 인터페이스. Claude / Gemini 중 하나를 고르고, 둘 다 없으면 None(템플릿 모드).

- text(system, prompt) -> 마크다운 등 자유 텍스트
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

    def text(self, system: str, prompt: str) -> str: ...

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

    def _run(self, system: str, prompt: str, output_format: dict | None = None) -> str:
        output_config: dict = {"effort": self.effort}
        if output_format:
            output_config["format"] = output_format
        try:
            # 기획서는 출력이 길어 스트리밍으로 받아 HTTP 타임아웃을 피한다
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config=output_config,
                betas=[self.FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                msg = stream.get_final_message()
        except self._anthropic.AuthenticationError as e:
            raise LLMError("Claude 인증 실패 — ANTHROPIC_API_KEY 확인") from e
        except self._anthropic.RateLimitError as e:
            raise LLMError("Claude 요청 한도 초과(429) — 잠시 후 다시 실행") from e
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"Claude API 오류 {e.status_code}: {e.message}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError("Claude 연결 실패 (네트워크)") from e

        if msg.stop_reason == "refusal":
            category = getattr(msg.stop_details, "category", None) if msg.stop_details else None
            raise LLMError(f"Claude가 요청을 거절함 (category={category})")
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if msg.stop_reason == "max_tokens":
            raise LLMError("출력이 max_tokens에서 잘림")
        return text

    def text(self, system, prompt):
        return self._run(system, prompt)

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

    def _run(self, system: str, prompt: str, schema: dict | None = None) -> str:
        cfg = {"system_instruction": system}
        if schema:
            cfg |= {"response_mime_type": "application/json", "response_json_schema": schema}
        try:
            resp = self.client.models.generate_content(
                model=self.model, contents=prompt, config=self.types.GenerateContentConfig(**cfg)
            )
        except Exception as e:  # google-genai는 오류 타입이 버전마다 달라 메시지만 전달
            raise LLMError(f"Gemini 오류: {str(e)[:300]}") from e
        if not resp.text:
            raise LLMError("Gemini 응답이 비어 있음 (안전 필터 차단 가능)")
        return resp.text.strip()

    def text(self, system, prompt):
        return self._run(system, prompt)

    def json(self, system, prompt, schema):
        return json.loads(self._run(system, prompt, schema))


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
