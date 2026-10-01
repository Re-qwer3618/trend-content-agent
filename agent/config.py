"""설정 로드.

키 우선순위: 프로젝트 .env > 중앙 .env(상위 폴더로 올라가며 처음 만나는 것) > 기존 환경변수.
키 값은 절대 출력하지 않는다 — 상태 확인은 `Settings.key_status()`(있음/없음만).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))  # Windows에는 tz DB가 없어 zoneinfo 대신 고정 오프셋


def _find_central_env() -> Path | None:
    for parent in PROJECT_DIR.parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def _load_env() -> None:
    central = _find_central_env()
    if central:
        load_dotenv(central, override=False)
    project_env = PROJECT_DIR / ".env"
    if project_env.is_file():
        load_dotenv(project_env, override=True)


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else (PROJECT_DIR / p).resolve()


@dataclass
class Settings:
    data_dir: Path
    report_dir: Path
    llm_provider: str
    claude_model: str
    claude_effort: str
    gemini_model: str
    anthropic_api_key: str | None = field(repr=False)
    gemini_api_key: str | None = field(repr=False)
    naver_client_id: str | None = field(repr=False)
    naver_client_secret: str | None = field(repr=False)
    youtube_api_key: str | None = field(repr=False)
    instagram_access_token: str | None = field(repr=False)
    instagram_user_id: str | None = field(repr=False)
    instagram_graph_version: str = "v23.0"
    http_timeout: float = 15.0
    user_agent: str = "Mozilla/5.0 (trend-content-agent)"

    def key_status(self) -> dict[str, bool]:
        return {
            "ANTHROPIC_API_KEY": bool(self.anthropic_api_key),
            "GEMINI_API_KEY": bool(self.gemini_api_key),
            "NAVER_CLIENT_ID/SECRET": bool(self.naver_client_id and self.naver_client_secret),
            "YOUTUBE_API_KEY": bool(self.youtube_api_key),
            "INSTAGRAM_ACCESS_TOKEN/USER_ID": bool(self.instagram_access_token and self.instagram_user_id),
        }


def load_settings() -> Settings:
    _load_env()
    env = os.getenv
    return Settings(
        data_dir=_path("DATA_DIR", "./data"),
        report_dir=_path("REPORT_DIR", "./reports"),
        llm_provider=env("LLM_PROVIDER", "auto").lower(),
        claude_model=env("CLAUDE_MODEL", "claude-opus-5-5"),
        claude_effort=env("CLAUDE_EFFORT", "medium"),
        gemini_model=env("GEMINI_MODEL", "gemini-2.5-flash"),
        anthropic_api_key=env("ANTHROPIC_API_KEY"),
        gemini_api_key=env("GEMINI_API_KEY") or env("GOOGLE_API_KEY"),
        naver_client_id=env("NAVER_CLIENT_ID"),
        naver_client_secret=env("NAVER_CLIENT_SECRET"),
        youtube_api_key=env("YOUTUBE_API_KEY"),
        instagram_access_token=env("INSTAGRAM_ACCESS_TOKEN"),
        instagram_user_id=env("INSTAGRAM_USER_ID"),
        instagram_graph_version=env("INSTAGRAM_GRAPH_VERSION", "v23.0"),
    )
