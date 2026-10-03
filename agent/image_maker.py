"""리포트의 이미지 프롬프트로 실제 썸네일·커버 이미지를 만들어 images/ 에 저장.

공급자 (IMAGE_PROVIDER=auto 이면 위에서부터 키가 있고 동작하는 것을 사용)
  openai        OPENAI_API_KEY 필요. 기본 gpt-image-1-mini, quality=low (dall-e-3는 2026-05-12 종료). 장당 유료
  gemini        GEMINI_API_KEY. 기본 gemini-3.1-flash-image (Nano Banana 2). 유료 프로젝트면 크레딧 필요
  pollinations  키 없음·무료 (image.pollinations.ai). 품질·속도는 들쭉날쭉, 프롬프트가 외부 서비스로 전송됨

실행
  run.bat --images-from reports\\20261002_0019_가을_캠핑.md     기존 리포트로 이미지만 생성
  run.bat "가을 캠핑" --make-images                              리포트 생성 후 바로 이미지까지
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote

import requests

from .config import Settings
from .images import NEGATIVE_DEFAULT, USAGES, ImagePrompt
from .llm import gemini_fatal_reason


class ImageError(RuntimeError):
    pass


class FatalImageError(ImageError):
    """크레딧 부족·키 오류처럼 다음 이미지도 똑같이 실패할 오류 → 다음 공급자로 넘어감."""


@dataclass
class MadeImage:
    prompt: ImagePrompt
    path: Path | None
    provider: str
    error: str = ""


# ---------------------------------------------------------------- 공급자


class OpenAIImages:
    name = "openai"
    URL = "https://api.openai.com/v1/images/generations"
    # gpt-image 계열 권장 크기 중 비율이 가장 가까운 것 (dall-e-3는 2026-05-12 종료)
    SIZES = {"1:1": "1024x1024", "9:16": "1024x1536", "16:9": "1536x1024"}

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise FatalImageError("OPENAI_API_KEY 없음")
        if settings.openai_image_model.startswith("dall-e"):
            raise FatalImageError(f"{settings.openai_image_model}는 종료된 모델 — OPENAI_IMAGE_MODEL=gpt-image-1-mini 로 변경")
        self.key, self.model, self.timeout = settings.openai_api_key, settings.openai_image_model, 180
        self.label = f"OpenAI {self.model}"

    def make(self, p: ImagePrompt) -> bytes:
        # gpt-image 계열은 항상 b64_json으로 돌려준다. quality=low가 가장 저렴 (썸네일엔 충분)
        body = {"model": self.model, "prompt": _with_negative(p), "n": 1,
                "size": self.SIZES.get(p.aspect_ratio, "1024x1024"),
                "quality": os.getenv("OPENAI_IMAGE_QUALITY", "low")}
        r = requests.post(self.URL, json=body, timeout=self.timeout,
                          headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code in (401, 403) or (r.status_code == 429 and "quota" in r.text):
            raise FatalImageError(f"OpenAI {r.status_code}: {_err_msg(r)}")
        if not r.ok:
            raise ImageError(f"OpenAI {r.status_code}: {_err_msg(r)}")
        return base64.b64decode(r.json()["data"][0]["b64_json"])


class GeminiImages:
    name = "gemini"

    def __init__(self, settings: Settings):
        if not settings.gemini_api_key:
            raise FatalImageError("GEMINI_API_KEY 없음")
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_image_model
        self.label = f"Gemini {self.model}"

    def make(self, p: ImagePrompt) -> bytes:
        t = self.types
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=_with_negative(p),
                config=t.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=t.ImageConfig(aspect_ratio=p.aspect_ratio),
                ),
            )
        except Exception as e:
            fatal = gemini_fatal_reason(str(e), self.model)
            raise (FatalImageError(fatal) if fatal else ImageError(f"Gemini: {str(e)[:200]}")) from e
        for cand in resp.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        raise ImageError("Gemini 응답에 이미지가 없음 (안전 필터 차단 가능)")


class PollinationsImages:
    name = "pollinations"
    URL = "https://image.pollinations.ai/prompt/{prompt}"
    SIZES = {"1:1": (1024, 1024), "9:16": (768, 1365), "16:9": (1365, 768)}

    # 익명 무료 등급은 약 30초에 1장 (그보다 빠르면 HTTP 402). 2026-10 실측 기준
    MIN_INTERVAL = float(os.getenv("POLLINATIONS_INTERVAL", "35"))

    def __init__(self, settings: Settings):
        self.label = "Pollinations (무료)"
        self._last = 0.0
        # 익명은 워터마크·768px 제한. auth.pollinations.ai 무료 가입 토큰이 있으면 nologo 적용
        token = os.getenv("POLLINATIONS_TOKEN")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _wait(self, seconds: float) -> None:
        remaining = self._last + seconds - time.time()
        if remaining > 0:
            time.sleep(remaining)

    def make(self, p: ImagePrompt) -> bytes:
        w, h = self.SIZES.get(p.aspect_ratio, (1024, 1024))
        # 무료 서비스라 프롬프트 길이(URL)를 적당히 제한
        prompt = f"{p.prompt_en[:900]} -- avoid: {p.negative_prompt[:150]}"
        last = ""
        for attempt in range(3):
            self._wait(self.MIN_INTERVAL if attempt == 0 else self.MIN_INTERVAL + 10)
            r = requests.get(self.URL.format(prompt=quote(prompt, safe="")), timeout=120, headers=self.headers,
                             params={"width": w, "height": h, "nologo": "true",
                                     "seed": zlib.crc32(p.prompt_en.encode()) % 10**6})  # 같은 프롬프트 = 같은 그림
            self._last = time.time()
            if r.ok and r.headers.get("content-type", "").startswith("image/"):
                return r.content
            last = f"HTTP {r.status_code}"
            if r.status_code not in (402, 429) and r.status_code < 500:
                break
        raise ImageError(f"Pollinations 실패 ({last}) — 무료 등급 속도 제한일 수 있음")


PROVIDERS = {c.name: c for c in (OpenAIImages, GeminiImages, PollinationsImages)}


# ---------------------------------------------------------------- 실행


def make_images(prompts: list[ImagePrompt], settings: Settings, out_dir: Path,
                provider: str | None = None, log=print) -> list[MadeImage]:
    """프롬프트마다 이미지 1장. 공급자가 치명적으로 실패하면 다음 공급자로 넘어간다."""
    choice = (provider or settings.image_provider or "auto").lower()
    order = list(PROVIDERS) if choice == "auto" else [choice]
    if choice not in PROVIDERS and choice != "auto":
        raise ImageError(f"알 수 없는 IMAGE_PROVIDER: {choice} (가능: auto, {', '.join(PROVIDERS)})")

    out_dir.mkdir(parents=True, exist_ok=True)
    prompts = ensure_english(prompts, settings, log)
    engines = []
    for name in order:
        try:
            engines.append(PROVIDERS[name](settings))
        except FatalImageError as e:
            log(f"  - {name}: 건너뜀 ({e})")
    results = []
    for p in prompts:
        made = None
        while engines and made is None:
            eng = engines[0]
            try:
                data = eng.make(p)
                path = out_dir / f"{p.issue_index}_{p.usage}.{_ext(data)}"
                path.write_bytes(data)
                made = MadeImage(p, path, eng.label)
                log(f"  ✔ [{p.issue_index}] {USAGES[p.usage][0]} → {path.name} ({eng.label})")
            except FatalImageError as e:
                log(f"  - {eng.label}: {e} → 다음 공급자로")
                engines.pop(0)
            except (ImageError, requests.RequestException) as e:
                made = MadeImage(p, None, eng.label, str(e)[:200])
                log(f"  ✖ [{p.issue_index}] {USAGES[p.usage][0]}: {made.error}")
        if made is None:
            made = MadeImage(p, None, "-", "사용 가능한 이미지 공급자 없음")
        results.append(made)
    return results


def load_prompts(source: Path) -> tuple[list[ImagePrompt], Path]:
    """리포트(.md) 또는 *_images.json 에서 프롬프트 읽기. (프롬프트, 리포트 경로)"""
    source = source.resolve()
    if source.suffix == ".json":
        report = source.with_name(source.stem.removesuffix("_images") + ".md")
        data = json.loads(source.read_text(encoding="utf-8"))
        return [ImagePrompt(**d) for d in data["prompts"]], report
    sidecar = source.with_name(f"{source.stem}_images.json")
    if sidecar.exists():
        return load_prompts(sidecar)[0], source
    return _parse_report(source.read_text(encoding="utf-8")), source


_SECTION_RE = re.compile(r"^### \[(\d+)\] (.+?) — (.+?) \(([\d:]+)\)$", re.M)


def _parse_report(md: str) -> list[ImagePrompt]:
    """JSON이 없는 예전 리포트용: '## 이미지 생성 프롬프트' 섹션을 파싱."""
    md = md.split("## 이미지 생성 프롬프트", 1)[-1] if "## 이미지 생성 프롬프트" in md else ""
    label_to_usage = {v[0]: k for k, v in USAGES.items()}
    out = []
    blocks = list(_SECTION_RE.finditer(md))
    for m, nxt in zip(blocks, blocks[1:] + [None]):
        chunk = md[m.end(): nxt.start() if nxt else len(md)]
        code = re.search(r"```text\n(.*?)\n```", chunk, re.S)
        if not code or m.group(3) not in label_to_usage:
            continue
        field = lambda name: (re.search(rf"- {name}: \**(.*?)\**$", chunk, re.M) or [None, ""])[1]
        neg = re.search(r"Negative: `(.*?)`", chunk)
        out.append(ImagePrompt(
            issue_index=int(m.group(1)), issue_title=m.group(2), usage=label_to_usage[m.group(3)],
            aspect_ratio=m.group(4), prompt_en=code.group(1).strip(),
            negative_prompt=neg.group(1) if neg else NEGATIVE_DEFAULT,
            style=field("스타일"), overlay_text_ko=field("얹을 문구"), alt_text_ko=field(r"대체텍스트\(alt\)"),
        ))
    return out


def append_to_report(report: Path, made: list[MadeImage]) -> None:
    """리포트 끝에 생성된 이미지를 붙인다 (리포트 기준 상대 경로)."""
    ok = [m for m in made if m.path]
    if not report.exists() or not ok:
        return
    marker = "\n---\n\n## 생성된 이미지\n"
    md = report.read_text(encoding="utf-8").split(marker)[0].rstrip("\n")  # 다시 실행하면 이전 섹션 교체
    lines = [marker.rstrip("\n"), ""]
    for m in ok:
        rel = Path(os.path.relpath(m.path, report.parent)).as_posix()
        lines += [f"**[{m.prompt.issue_index}] {USAGES[m.prompt.usage][0]}** — {m.provider} · 얹을 문구: "
                  f"{m.prompt.overlay_text_ko}", "", f"![{m.prompt.alt_text_ko}]({rel})", "",
                  "<details><summary>사용한 프롬프트</summary>", "", "```text", m.prompt.prompt_en, "```",
                  "", "</details>", ""]
    report.write_text(md + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def run_for_report(source: Path, settings: Settings, provider: str | None = None, log=print) -> list[MadeImage]:
    prompts, report = load_prompts(source)
    if not prompts:
        raise ImageError(f"이미지 프롬프트가 없습니다: {source}")
    out_dir = settings.image_dir / report.stem
    log(f"▶ 이미지 생성: {len(prompts)}장 → {out_dir}")
    made = make_images(prompts, settings, out_dir, provider, log)
    # 실제로 쓴 프롬프트(영문 변환 후)를 이미지 옆에 남긴다 — 다시 만들거나 다른 생성기에 쓸 때 필요
    (out_dir / "prompts.json").write_text(json.dumps(
        [{**asdict(m.prompt), "file": m.path.name if m.path else None, "provider": m.provider, "error": m.error}
         for m in made], ensure_ascii=False, indent=2), encoding="utf-8")
    append_to_report(report, made)
    return made


# ---------------------------------------------------------------- 한글 프롬프트 → 영문

_HANGUL = re.compile(r"[가-힣]")
_REWRITE = ("Write one English image-generation prompt for EACH numbered item below. Each prompt: a concrete, "
            "generic scene that fits the Korean topic (subject, setting, composition with empty space for a caption, "
            "lighting, colors, style). No real people, brands or logos; the image must contain no text.\n"
            "Reply with exactly one line per item in the form `N: prompt`, nothing else.\n\n{items}")
_LINE_RE = re.compile(r"^\s*(\d+)\s*[:.)]\s*(.+)$")


def ensure_english(prompts: list[ImagePrompt], settings: Settings, log=print) -> list[ImagePrompt]:
    """LLM 없이 만든 템플릿 프롬프트는 한글 제목이 그대로 들어 있어 이미지 모델이 엉뚱한 그림을 그린다.
    한글이 있으면 영문 장면 묘사로 바꾼다: 동작하는 LLM → 없으면 Pollinations 무료 텍스트 API."""
    from dataclasses import replace

    from .llm import LLMError, get_llm

    todo = [p for p in prompts if _HANGUL.search(p.prompt_en)]
    if not todo:
        return prompts
    llm = None
    if settings.generation_mode != "prompt":  # prompt 모드는 유료 LLM API를 쓰지 않는다
        try:
            llm = get_llm(settings)
        except LLMError:
            pass
    log(f"  · 한글이 섞인 프롬프트 {len(todo)}개를 영문으로 변환")
    # 무료 API는 요청 속도 제한이 있어 한 번에 묶어서 보낸다
    q = _REWRITE.format(items="\n".join(
        f"{n}: [{USAGES[p.usage][0]}, {p.aspect_ratio}, style: {p.style}] {p.issue_title}"
        for n, p in enumerate(todo, start=1)))
    text = ""
    if llm:
        try:
            text = llm.text("You write prompts for image generation models.", q)
        except LLMError:
            pass  # 크레딧 부족 등 → 무료 API로
    if not text:
        try:
            r = requests.post("https://text.pollinations.ai/openai", timeout=120,
                              json={"model": "openai", "messages": [{"role": "user", "content": q}]})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, ValueError) as e:
            log(f"  - 무료 텍스트 API 변환 실패 ({type(e).__name__}) — 제목만 번역해 템플릿에 넣기")
    lines = {int(m.group(1)): m.group(2).strip().strip('"`')
             for m in map(_LINE_RE.match, text.splitlines()) if m}
    fixed = {id(p): replace(p, prompt_en=lines[n]) for n, p in enumerate(todo, start=1)
             if n in lines and not _HANGUL.search(lines[n])}
    # 마지막 수단: 이슈 제목만 기계 번역해서 템플릿의 한글 자리에 넣는다 (한글 그대로 보내면 무관한 그림이 나옴)
    for p in todo:
        if id(p) in fixed:
            continue
        title_en = _translate_title(p.issue_title)
        if title_en:
            prompt = p.prompt_en.replace(f'"{p.issue_title}" (← 영어로 바꿔 넣기)', f'"{title_en}"')
            if not _HANGUL.search(prompt):
                fixed[id(p)] = replace(p, prompt_en=prompt)
    if len(fixed) < len(todo):
        log(f"  - {len(todo) - len(fixed)}개는 변환 결과가 없어 원래 프롬프트 사용")
    return [fixed.get(id(p), p) for p in prompts]


_title_cache: dict[str, str] = {}


def _translate_title(title: str) -> str:
    """MyMemory 무료 번역 API (키 불필요, 익명 하루 5,000자). 실패하면 빈 문자열."""
    if title not in _title_cache:
        try:
            r = requests.get("https://api.mymemory.translated.net/get", timeout=20,
                             params={"q": title[:400], "langpair": "ko|en"})
            r.raise_for_status()
            out = r.json()["responseData"]["translatedText"] or ""
            _title_cache[title] = "" if _HANGUL.search(out) else out.strip()
        except (requests.RequestException, KeyError, ValueError, TypeError):
            _title_cache[title] = ""
    return _title_cache[title]


# ---------------------------------------------------------------- 유틸


def _with_negative(p: ImagePrompt) -> str:
    # DALL·E·Gemini는 negative prompt 파라미터가 없어 문장으로 덧붙인다
    return f"{p.prompt_en}\n\nAvoid: {p.negative_prompt}" if p.negative_prompt else p.prompt_en


def _err_msg(r: requests.Response) -> str:
    try:
        return r.json().get("error", {}).get("message", "")[:200]
    except ValueError:
        return r.text[:200]


def _ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "png"
