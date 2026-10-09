"""릴스/쇼츠 영상 자동 제작 (9:16 mp4).

MoneyPrinterTurbo(harry0703/MoneyPrinterTurbo, MIT)의 파이프라인 구성을 참고해 이 프로젝트에 맞게 다시 작성했다:
  대본 → edge-tts 나레이션(무료, 한국어 음성) → 단어 단위 타이밍으로 자막 → 장면별 화면(스톡 영상/이미지) → MoviePy 합성

대본 출처 (우선순위)
  1) 웹 LLM·API가 쓴 촬영 대본 텍스트 — `[컷 N]` 블록의 `나레이션:` / `자막:` / `영상 검색어:` 줄을 읽는다
  2) 없으면 분석 결과(상위 이슈)로 짧은 나레이션을 자동 구성 → LLM 없이도 영상까지 무료로 완성
화면 소스 (장면마다)
  1) PEXELS_API_KEY 가 있고 장면에 영문 검색어가 있으면 Pexels 세로 스톡 영상
  2) images/<리포트>/ 의 생성 이미지 (릴스 커버 우선) — 천천히 확대(Ken Burns) + 흐린 배경
  3) 둘 다 없으면 단색 그라데이션 배경

필요: moviepy 2.x, edge-tts 7.x (requirements.txt). 한글 폰트는 Windows 맑은 고딕, Linux Noto Sans CJK (SHORTS_FONT로 지정 가능).
edge-tts는 Microsoft Edge 읽어주기 서비스를 쓰는 비공식 라이브러리라 사용량이 많으면 막힐 수 있다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageFilter

from .config import Settings

W, H = 1080, 1920
FPS = 30
VOICES = {"female": "ko-KR-SunHiNeural", "male": "ko-KR-InJoonNeural", "multi": "ko-KR-HyunsuMultilingualNeural"}
FONT_CANDIDATES = [
    os.getenv("SHORTS_FONT", ""),
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]


class ShortsError(RuntimeError):
    pass


@dataclass
class Scene:
    narration: str                 # 읽을 문장 (자막도 여기서 나온다)
    caption: str = ""              # 화면 상단 큰 제목 (선택)
    search: str = ""               # 스톡 영상 영문 검색어 (선택)
    image: Path | None = None      # 이 장면에 쓸 이미지 (선택)
    issue_index: int | None = None  # 어느 이슈 장면인지 → 그 이슈의 생성 이미지를 쓴다


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class ShortsResult:
    video: Path
    srt: Path
    script: Path
    duration: float
    sources: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 대본


_CUT_RE = re.compile(r"\[컷\s*(\d+)\]")


def parse_script(text: str) -> list[Scene]:
    """웹 LLM이 쓴 촬영 대본에서 장면 추출. `[컷 N]` 블록이 없으면 빈 줄로 나뉜 문단을 장면으로 본다."""
    text = text.replace("\r\n", "\n")
    blocks = _CUT_RE.split(text)
    scenes = []
    if len(blocks) > 1:
        for body in blocks[2::2]:  # split 결과: [앞부분, 번호, 본문, 번호, 본문, ...]
            def field_of(name: str) -> str:
                m = re.search(rf"^\s*{name}\s*[:：]\s*(.+)$", body, re.M)
                return m.group(1).strip().strip('"“”') if m else ""
            narration = field_of("나레이션") or field_of("대사")
            if narration and narration not in ("-", "없음"):
                issue = field_of("이슈")
                scenes.append(Scene(narration, caption=field_of("자막").replace(" / ", "\n"),
                                    search=field_of(r"영상\s*검색어(?:\(영문\))?"),
                                    issue_index=int(issue) if issue.isdigit() else None))
    else:
        for para in re.split(r"\n\s*\n", text):
            para = re.sub(r"^#+.*$", "", para, flags=re.M).strip()
            if para:
                scenes.append(Scene(" ".join(para.split())))
    return scenes


def scenes_to_text(scenes: list[Scene], header: str = "") -> str:
    """사람이 고치기 쉬운 대본 파일 형식 (parse_script로 다시 읽힌다)."""
    blocks = [f"[컷 {i}]\n자막: {s.caption.replace(chr(10), ' / ')}\n나레이션: {s.narration}"
              + (f"\n영상 검색어: {s.search}" if s.search else "")
              + (f"\n이슈: {s.issue_index}" if s.issue_index is not None else "")
              for i, s in enumerate(scenes, 1)]
    return (header + "\n\n" if header else "") + "\n\n".join(blocks) + "\n"


SCRIPT_HEADER = """# 쇼츠 대본 — 이 파일을 고친 뒤 `run.bat --video-from <리포트.md>` 로 영상을 다시 만들 수 있습니다.
# 웹 LLM(요청_reels 프롬프트)이 쓴 대본을 통째로 붙여 넣어도 됩니다. 읽는 줄: [컷 N] / 자막 / 나레이션 / 영상 검색어 / 이슈
# 자막의 ' / '는 줄바꿈, '이슈: 숫자'는 그 이슈의 생성 이미지를 쓰라는 뜻, '영상 검색어'(영문)는 PEXELS_API_KEY가 있을 때 스톡 영상 검색"""


_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def _clean_title(title: str) -> tuple[str, str]:
    """뉴스·유튜브 제목 → (장소 머리말, 읽기 좋은 본문).
    [팔도핫플-경북 구미 낙동강체육공원] 같은 머리말의 장소는 살리고, 해시태그·이모지·'| 부제'·'- 언론사'는 버린다."""
    m = re.match(r"^\s*\[([^\]]*)\]\s*", title)
    head = m.group(1).split("-", 1)[1].strip() if m and "-" in m.group(1) else ""
    t = title[m.end():] if m else title
    t = re.split(r"\s[|｜]\s", t)[0]                           # 유튜브식 "제목 | 부제 | 장소"
    t = re.sub(r"#\S+", "", t)                                 # 해시태그
    t = _EMOJI_RE.sub("", t)
    t = re.sub(r"\[[^\]]*\]|【[^】]*】|\([^)]*\)", "", t)
    t = re.sub(r"\s+-\s+[^-]{2,15}$", "", t)                   # 끝의 " - 언론사"
    t = re.sub(r"[‘’“”\"']", "", t).replace("…", ", ")
    t = re.sub(r"([!?])[!?]+", r"\1", t)
    return head, " ".join(t.split()).strip(" ,.")


def _short_caption(text: str, limit: int = 24) -> str:
    """화면 제목용: 쉼표 앞이나 단어 경계에서 limit자 이내로 (쉼표 앞이 너무 짧으면 쉼표를 무시)."""
    text = text.replace("...", ",").replace("..", ",")
    first = re.split(r"[,，]", text)[0].strip()
    if 6 <= len(first) <= limit:
        return first
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if "," in cut[6:]:                                   # 한도 안의 마지막 쉼표에서 자르기
        return cut[:cut.rindex(",")].strip()
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip("·, ")


def _speakable(text: str) -> str:
    return text.replace("·", ", ").replace("  ", " ")


def scenes_from_analysis(analysis, max_points: int = 3) -> list[Scene]:
    """LLM 없이 상위 이슈로 25~35초 나레이션을 만든다 (훅 → 이슈 3개 → 저장 유도)."""
    main = analysis.insight.get("seo_keywords", {}).get("main") or analysis.keyword or "오늘의 트렌드"
    issues = analysis.issues[:max_points]
    if not issues:
        raise ShortsError("영상으로 만들 이슈가 없습니다")
    order = ["첫 번째", "두 번째", "세 번째", "네 번째"]
    scenes = [Scene(f"요즘 {main}, 이 소식들 알고 계셨나요? 지금 화제인 {len(issues)}가지를 30초로 정리해 드릴게요.",
                    caption=f"{main}\n지금 알아야 할 {len(issues)}가지")]
    for i, iss in enumerate(issues):
        head, body = _clean_title(iss.title)
        spoken = f"{head}, {body}" if head else body
        end = "" if spoken.endswith(("!", "?")) else "."
        scenes.append(Scene(_speakable(f"{order[i]}, {spoken}{end}"),
                            caption=f"{i + 1}. {_short_caption(body)}", issue_index=i))
    scenes.append(Scene("자세한 내용은 원문에서 꼭 확인하시고, 도움이 됐다면 저장해 두세요!",
                        caption="저장해 두고 확인하세요"))
    return scenes


# ---------------------------------------------------------------- 나레이션 (edge-tts)


def synthesize(scenes: list[Scene], out_dir: Path, voice: str, rate: str = "+8%",
               gap: float = 0.25) -> tuple[Path, list[list[Word]], list[tuple[float, float]]]:
    """장면별로 합성해 이어 붙인다. (오디오, 장면별 단어 목록(전체 타임라인 기준), 장면별 [시작, 끝])"""
    import edge_tts
    from moviepy import AudioFileClip, concatenate_audioclips
    from moviepy.audio.AudioClip import AudioClip

    out_dir.mkdir(parents=True, exist_ok=True)
    clips, words, bounds, t = [], [], [], 0.0
    for n, sc in enumerate(scenes):
        path = out_dir / f"voice_{n:02d}.mp3"
        local: list[Word] = []
        for attempt in range(3):
            try:
                comm = edge_tts.Communicate(sc.narration, voice, rate=rate, boundary="WordBoundary")
                with path.open("wb") as f:
                    for ch in comm.stream_sync():
                        if ch["type"] == "audio":
                            f.write(ch["data"])
                        elif ch["type"] == "WordBoundary":
                            s = ch["offset"] / 1e7
                            local.append(Word(s, s + ch["duration"] / 1e7, ch["text"]))
                if path.stat().st_size > 0:
                    break
            except Exception as e:  # 네트워크·서비스 오류 → 재시도
                local = []
                if attempt == 2:
                    raise ShortsError(f"edge-tts 실패: {type(e).__name__}: {str(e)[:120]}") from e
        clip = AudioFileClip(str(path))
        dur = clip.duration
        words.append([Word(w.start + t, w.end + t, w.text) for w in local])
        bounds.append((t, t + dur + gap))
        clips += [clip, AudioClip(lambda _t: [0, 0], duration=gap, fps=44100)]
        t += dur + gap
    audio_path = out_dir / "narration.mp3"
    full = concatenate_audioclips(clips)
    full.write_audiofile(str(audio_path), fps=44100, logger=None)
    for c in clips:
        c.close()
    return audio_path, words, bounds


def subtitle_chunks(scene_words: list[list[Word]], max_chars: int = 14, pause: float = 0.3) -> list[Word]:
    """단어를 화면 한 줄(공백 포함 max_chars자)씩 묶는다.
    장면 경계와 말이 쉬는 지점(쉼표·마침표 자리, pause초 이상)에서 끊는다 — edge-tts 단어에는 문장부호가 없다."""
    chunks, cur = [], []

    def flush():
        if cur:
            chunks.append(Word(cur[0].start, cur[-1].end, " ".join(w.text for w in cur)))
            cur.clear()
    for words in scene_words:
        for w in words:
            if cur and (len(" ".join(x.text for x in cur + [w])) > max_chars or w.start - cur[-1].end >= pause):
                flush()
            cur.append(w)
        flush()
    # 다음 자막 시작까지 이어서 보이게 (깜빡임 방지)
    for a, b in zip(chunks, chunks[1:]):
        if b.start - a.end < 0.6:
            a.end = b.start
    return chunks


def write_srt(chunks: list[Word], path: Path) -> None:
    def ts(x: float) -> str:
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    path.write_text("\n".join(f"{i}\n{ts(c.start)} --> {ts(c.end)}\n{c.text}\n" for i, c in enumerate(chunks, 1)),
                    encoding="utf-8")


# ---------------------------------------------------------------- 화면 소스


def pexels_video(query: str, out: Path, min_duration: float, used: set[int] | None = None) -> Path | None:
    """Pexels 세로 스톡 영상 1개 다운로드 (무료 API 키 필요: pexels.com/api).
    한글 검색어면 locale=ko-KR 로 검색한다(Pexels 지원). used 에 든 영상은 건너뛰어 장면마다 다른 영상을 쓴다."""
    key = os.getenv("PEXELS_API_KEY")
    if not key or not query:
        return None
    params = {"query": query, "orientation": "portrait", "per_page": 15}
    if re.search(r"[가-힣]", query):
        params["locale"] = "ko-KR"
    r = requests.get("https://api.pexels.com/videos/search", timeout=30, headers={"Authorization": key},
                     params=params)
    if not r.ok:
        return None
    for v in r.json().get("videos", []):
        if v.get("duration", 0) < min(min_duration, 8) or (used is not None and v.get("id") in used):
            continue
        if used is not None:
            used.add(v.get("id"))
        files = [f for f in v.get("video_files", []) if f.get("height", 0) >= 1280 and f.get("width", 0) < f.get("height", 0)]
        if files:
            full_hd = [f for f in files if f["height"] >= H]          # 1920 이상이 있으면 그중 가장 작은 것(용량↓)
            best = min(full_hd, key=lambda f: f["height"]) if full_hd else max(files, key=lambda f: f["height"])
            with requests.get(best["link"], stream=True, timeout=120) as dl:
                dl.raise_for_status()
                with out.open("wb") as fh:
                    for chunk in dl.iter_content(1 << 20):
                        fh.write(chunk)
            return out
    return None


def report_images(image_dir: Path) -> list[Path]:
    """images/<리포트>/ 에서 릴스 커버(9:16) 우선, 그다음 썸네일."""
    if not image_dir.is_dir():
        return []
    files = sorted(p for p in image_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    return [p for p in files if "reels_cover" in p.name] + [p for p in files if "reels_cover" not in p.name]


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / im.width, h / im.height)
    r = im.resize((max(w, round(im.width * scale)), max(h, round(im.height * scale))), Image.LANCZOS)
    left, top = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((left, top, left + w, top + h))


def _image_layers(img: Path) -> tuple[np.ndarray, np.ndarray]:
    """세로 화면용: 흐린 배경(꽉 채움) + 전경. 전경은 화면보다 8% 크게 만들어 두고 위치만 옮겨 천천히 흐르게(팬) 한다."""
    im = Image.open(img).convert("RGB")
    bg = _cover(im, W, H).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.35)
    tall = im.height / im.width >= H / W * 0.9          # 세로 이미지는 화면을 꽉, 정사각·가로는 가로폭에 맞춤
    fit = max(W / im.width, H / im.height) if tall else W / im.width
    fg = im.resize((round(im.width * fit * 1.08), round(im.height * fit * 1.08)), Image.LANCZOS)
    return np.asarray(bg), np.asarray(fg)


def _paste(frame: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
    """src를 frame의 (x, y)에 붙인다(화면 밖은 잘라냄)."""
    h, w = src.shape[:2]
    fx0, fy0, fx1, fy1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if fx0 < fx1 and fy0 < fy1:
        frame[fy0:fy1, fx0:fx1] = src[fy0 - y:fy1 - y, fx0 - x:fx1 - x]


def _font() -> str:
    for p in FONT_CANDIDATES:
        if p and Path(p).exists():
            return p
    raise ShortsError("한글 폰트를 찾지 못했습니다 — SHORTS_FONT 환경변수로 .ttf/.ttc 경로를 지정하세요")


def _text_sprite(text: str, font_path: str, size: int, fill: str, stroke: int, max_width: int) -> np.ndarray:
    """테두리 있는 여러 줄 글자를 RGBA 배열로 한 번만 그려 둔다 (프레임마다 다시 그리지 않음)."""
    from PIL import ImageDraw, ImageFont

    font = ImageFont.truetype(font_path, size)
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = f"{cur} {word}".strip()
            if cur and font.getlength(trial) > max_width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
    line_h = int(size * 1.25)
    width = int(max(font.getlength(l) for l in lines)) + stroke * 2 + 8
    canvas = Image.new("RGBA", (width, line_h * len(lines) + stroke * 2 + 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for i, line in enumerate(lines):
        x = (width - font.getlength(line)) / 2
        draw.text((x, stroke + 4 + i * line_h), line, font=font, fill=fill, stroke_width=stroke, stroke_fill="black")
    return np.asarray(canvas)


def _blend_sprite(frame: np.ndarray, sprite: np.ndarray, cx: int, y: int) -> None:
    h, w = sprite.shape[:2]
    x = cx - w // 2
    fx0, fy0, fx1, fy1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if fx0 >= fx1 or fy0 >= fy1:
        return
    s = sprite[fy0 - y:fy1 - y, fx0 - x:fx1 - x]
    a = s[..., 3:4].astype(np.float32) / 255.0
    region = frame[fy0:fy1, fx0:fx1].astype(np.float32)
    frame[fy0:fy1, fx0:fx1] = (region * (1 - a) + s[..., :3] * a).astype(np.uint8)


class _SceneVisual:
    """장면 하나의 프레임 생성기: 스톡 영상 / 이미지 팬 / 단색."""

    def __init__(self, sc: Scene, dur: float, idx: int, work: Path, sources: list[str],
                 fallback_query: str = "", used: set[int] | None = None):
        self.dur, self.idx, self.video, self.bg, self.fg = dur, idx, None, None, None
        # 우선순위: 장면 검색어로 스톡 영상 → 생성 이미지 → (이미지도 없으면) 주제 키워드로 스톡 영상 → 단색
        query = sc.search or ("" if sc.image else fallback_query)
        stock = None
        try:
            stock = pexels_video(query, work / f"stock_{idx:02d}.mp4", dur, used)
        except requests.RequestException:
            stock = None
        if stock:
            from moviepy import VideoFileClip

            clip = VideoFileClip(str(stock), audio=False)
            scale = max(W / clip.w, H / clip.h)
            self.video = clip.resized(scale).cropped(x_center=clip.w * scale / 2, y_center=clip.h * scale / 2,
                                                     width=W, height=H)
            sources.append(f"장면 {idx + 1}: Pexels '{query}'")
        elif sc.image:
            self.bg, self.fg = _image_layers(sc.image)
            sources.append(f"장면 {idx + 1}: 이미지 {sc.image.name}")
        else:
            palette = [(24, 45, 74), (64, 36, 70), (22, 70, 60), (80, 50, 20)]
            self.bg = np.full((H, W, 3), palette[idx % len(palette)], dtype=np.uint8)
            sources.append(f"장면 {idx + 1}: 단색 배경")

    def frame(self, t: float) -> np.ndarray:
        if self.video is not None:
            return self.video.get_frame(t % max(self.video.duration - 0.05, 0.1))
        out = self.bg.copy()
        if self.fg is not None:
            fh, fw = self.fg.shape[:2]
            p = min(max(t / self.dur, 0.0), 1.0)
            dx = (fw - W) / 2 * (1 if self.idx % 2 else -1)     # 장면마다 좌→우 / 우→좌로 번갈아 흐름
            _paste(out, self.fg, round((W - fw) / 2 + dx * (p - 0.5)), round((H - fh) / 2))
        return out


def render(scenes: list[Scene], out_dir: Path, images: list[Path] | None = None, voice: str = VOICES["female"],
           bgm: Path | None = None, log=print) -> ShortsResult:
    """프레임은 numpy로 직접 만든다 — MoviePy 레이어 합성보다 10배 이상 빠르다(1080x1920 기준)."""
    from moviepy import AudioFileClip, CompositeAudioClip, VideoClip, afx

    if not scenes:
        raise ShortsError("장면이 없습니다")
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(exist_ok=True)
    font = _font()
    images = images or []
    for i, sc in enumerate(scenes):              # 이미지가 지정되지 않은 장면은 있는 이미지를 돌려 쓴다
        if sc.image is None and images:
            sc.image = images[i % len(images)]

    script_path = out_dir / "script.txt"
    script_path.write_text("\n\n".join(f"[컷 {i}]\n자막: {s.caption}\n나레이션: {s.narration}"
                                       for i, s in enumerate(scenes, 1)), encoding="utf-8")

    log(f"  · 나레이션 합성 ({voice}, 장면 {len(scenes)}개)")
    audio_path, scene_words, bounds = synthesize(scenes, work, voice)
    chunks = subtitle_chunks(scene_words)
    srt = out_dir / "subtitles.srt"
    write_srt(chunks, srt)
    total = bounds[-1][1]

    log("  · 화면 구성")
    sources: list[str] = []
    # 주제 키워드 = 첫 장면 제목 첫 줄 (예: '가을 캠핑') — 이미지가 없을 때 스톡 영상 검색에 쓴다
    topic = scenes[0].caption.split("\n")[0].strip() if scenes[0].caption else ""
    used: set[int] = set()
    visuals = [_SceneVisual(sc, e - s, i, work, sources, topic, used)
               for i, (sc, (s, e)) in enumerate(zip(scenes, bounds))]
    titles = [_text_sprite(sc.caption, font, 76, "#FFE14D", 7, W - 140) if sc.caption else None for sc in scenes]
    subs = [(c.start, c.end, _text_sprite(c.text, font, 70, "white", 6, W - 160)) for c in chunks]
    fade = 0.25

    def make_frame(t: float) -> np.ndarray:
        i = next((k for k, (s, e) in enumerate(bounds) if t < e), len(bounds) - 1)
        s = bounds[i][0]
        frame = visuals[i].frame(t - s)
        if i and t - s < fade:                    # 장면 전환: 앞 장면 마지막 화면과 짧게 겹치기
            prev = visuals[i - 1].frame(bounds[i - 1][1] - bounds[i - 1][0])
            a = (t - s) / fade
            frame = (prev * (1 - a) + frame * a).astype(np.uint8)
        else:
            frame = np.array(frame, dtype=np.uint8, copy=True)
        if titles[i] is not None:
            _blend_sprite(frame, titles[i], W // 2, int(H * 0.11))
        for cs, ce, sprite in subs:
            if cs <= t < ce:
                _blend_sprite(frame, sprite, W // 2, int(H * 0.66))
                break
        return frame

    narration = AudioFileClip(str(audio_path))
    audio = narration
    if bgm and bgm.exists():
        music = (AudioFileClip(str(bgm)).with_effects([afx.AudioLoop(duration=total)])
                 .with_volume_scaled(0.12).with_effects([afx.AudioFadeOut(1.5)]))
        audio = CompositeAudioClip([narration, music])
        sources.append(f"BGM: {bgm.name}")

    video = VideoClip(make_frame, duration=total).with_audio(audio)
    out = out_dir / "shorts.mp4"
    log(f"  · 인코딩 ({total:.1f}초, {W}x{H})")
    video.write_videofile(str(out), fps=FPS, codec="libx264", audio_codec="aac", preset="veryfast",
                          threads=os.cpu_count() or 4, logger=None,
                          temp_audiofile=str(work / "temp_audio.m4a"))
    video.close()
    narration.close()
    for v in visuals:
        if v.video is not None:
            v.video.close()
    return ShortsResult(out, srt, script_path, total, sources)


def pick_bgm(project_dir: Path) -> Path | None:
    """assets/bgm/ 에 넣어 둔 음악 중 첫 번째 (저작권 없는 음원만 넣을 것)."""
    folder = project_dir / "assets" / "bgm"
    files = sorted(folder.glob("*.mp3")) if folder.is_dir() else []
    return files[0] if files else None


def make_shorts(settings: Settings, report: Path, scenes: list[Scene], log=print) -> ShortsResult:
    from .config import PROJECT_DIR

    images = report_images(settings.image_dir / report.stem)
    for sc in scenes:  # 이슈 장면에는 그 이슈의 이미지 (릴스 커버 → 썸네일 순)
        if sc.image is None and sc.issue_index is not None:
            sc.image = next((p for kind in ("reels_cover", "blog_thumbnail") for p in images
                             if p.stem == f"{sc.issue_index}_{kind}"), None)
    # 훅·마무리처럼 이슈가 없는 장면은 아직 안 쓴 이미지(썸네일 우선)로 채운다
    spare = [p for p in images[::-1] if p not in {s.image for s in scenes}]
    for sc in scenes:
        if sc.image is None and spare:
            sc.image = spare.pop(0)
    voice =VOICES.get(os.getenv("SHORTS_VOICE", "female"), os.getenv("SHORTS_VOICE", VOICES["female"]))
    return render(scenes, PROJECT_DIR / "videos" / report.stem, images, voice, pick_bgm(PROJECT_DIR), log)
