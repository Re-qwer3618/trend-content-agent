"""카드형 릴스 — 구운 카드뉴스 세트를 세로 9:16 한 편(mp4)으로: edge-tts 나레이션 + 자막 + (있으면) BGM.

영상은 cardnews-kit의 cardnews-video 스킬(`video.cjs --format reel`)이 만든다. 이 모듈은
카드마다 읽을 문장을 정하고(카드의 `say`, 없으면 제목 — 표지·마무리는 설명까지), edge-tts로 목소리 파일을 만들어 `narration.json`에 적고,
릴스용 복사본에서 "밀어서 보기" 버튼을 숨긴 뒤(자막과 겹침) 굽는다. 원본 세트(out/ PNG)는 건드리지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import categories, characters
from .cardnews import CardError, check_engine, engine_dir
from .config import PROJECT_DIR
from .shorts_maker import VOICES, _speakable, pick_bgm

HIDE_SWIPE = "<style>.swipe { visibility: hidden; }</style>\n</head>"
TYPEWRITER = Path(__file__).with_name("typewriter.js")  # 제목 타자 효과 (릴스 복사본에만)
BGM_VOLUME = 0.12


@dataclass
class ReelResult:
    video: Path
    frames: Path | None
    duration: float
    lines: int
    bgm: str
    voice_engine: str = "edge-tts"


def video_dir() -> Path:
    return engine_dir().parent.parent / "cardnews-video" / "scripts"


def narration_lines(deck: dict) -> list[list[str]]:
    """카드마다 읽을 문장. `say`(문자열 또는 목록)가 있으면 그대로, 없으면 제목 + 설명을 말하듯 이어 붙인다."""
    out = []
    for card in deck["cards"]:
        say = card.get("say")
        if say:
            lines = [say] if isinstance(say, str) else list(say)
        else:  # 릴스는 30초 안팎이 목표라 내지는 제목만, 표지·마무리는 설명까지
            title, desc = _plain(card.get("title", "")), _plain(card.get("desc", ""))
            parts = (title, desc) if card.get("type") in ("cover", "closing") else (title,)
            lines = [" ".join(_sentence(x) for x in parts if x)]
        out.append([_plain(x) for x in lines if _plain(x)])
    return out


def _plain(text: str) -> str:
    text = re.sub(r"\*?\[확인 필요[^\]]*\]\*?", "확인이 필요해요", text or "")
    text = text.replace("*", "").replace("\n", " ")
    return " ".join(text.split())


def _sentence(text: str) -> str:
    if not text:
        return ""
    return text if text[-1] in ".!?…" else text + "."


def card_voices(deck: dict, default: str) -> list[dict]:
    """장마다 읽을 목소리: 그 장의 speaker 캐릭터 → 덱의 host 캐릭터 → 기본(SHORTS_VOICE)."""
    base = {"name": default, "rate": "+8%", "pitch": "+0Hz"}
    host = characters.voice(deck.get("host"))
    voices = [{**base, **(characters.voice(c.get("speaker")) or host or {})} for c in deck["cards"]]
    rate, pitch = categories.voice_offset(deck.get("category"))  # 카테고리 톤: 생활 꿀팁은 빠르게, 건강은 느리게 …
    return [{**v, "rate": _shift(v["rate"], rate, "%"), "pitch": _shift(v["pitch"], pitch, "Hz")} for v in voices]


def _shift(value: str, delta: int, unit: str) -> str:
    n = int(re.sub(r"[^\d-]", "", value) or 0) + delta
    return f"{n:+d}{unit}"


def synthesize_lines(lines: list[list[str]], voice_dir: Path, voices: list[dict],
                     log=print) -> tuple[list[list[dict]], str]:
    """장마다 목소리 파일. edge-tts가 막히면(403 등) Windows 내장 한국어 음성으로 전부 다시 만든다
    (캐릭터별 목소리 구분은 없어지지만 릴스는 나온다). 돌려주는 값: (narration 항목, 쓴 엔진 이름)."""
    voice_dir.mkdir(parents=True, exist_ok=True)
    try:
        return _synthesize(lines, voice_dir, voices, _edge), "edge-tts"
    except CardError as e:
        if os.name != "nt":
            raise
        log(f"  ! {e} → Windows 내장 음성으로 대신 만듦 (캐릭터별 목소리 구분 없음)")
        return _synthesize(lines, voice_dir, voices, _sapi), "Windows 내장 음성"


def _synthesize(lines, voice_dir: Path, voices, engine) -> list[list[dict]]:
    cards = []
    for i, (card_lines, v) in enumerate(zip(lines, voices), start=1):
        entries = []
        for k, text in enumerate(card_lines, start=1):
            path = voice_dir / f"{i:02d}-{k}.mp3"
            for attempt in range(3):
                try:
                    engine(_speakable(text), v, path)
                    if path.stat().st_size > 0:
                        break
                except Exception as e:  # edge-tts는 네트워크 오류를 여러 종류로 던진다
                    if attempt == 2:
                        raise CardError(f"나레이션 합성 실패 ({i}번 장): {str(e)[:120]}") from e
            entries.append({"show": text, "file": f"voice/{path.name}"})
        cards.append(entries)
    return cards


def _edge(text: str, v: dict, path: Path) -> None:
    import edge_tts

    edge_tts.Communicate(text, v["name"], rate=v["rate"], pitch=v["pitch"]).save_sync(str(path))


SAPI_PS = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
           "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'ko-KR' } | Select-Object -First 1; "
           "if (-not $v) { exit 3 }; $s.SelectVoice($v.VoiceInfo.Name); $s.Rate = [int]$env:SAPI_RATE; "
           "$s.SetOutputToWaveFile($env:SAPI_OUT); $s.Speak($env:SAPI_TEXT); $s.Dispose()")


def _sapi(text: str, v: dict, path: Path) -> None:
    """Windows 내장 한국어 음성(예: Microsoft Heami) → wav → mp3. 속도만 edge의 rate(+10% ≈ 1단계)를 따른다."""
    rate = max(-10, min(10, round(int(re.sub(r"[^\d-]", "", v.get("rate", "0")) or 0) / 10)))
    wav = path.with_suffix(".wav")
    env = {**os.environ, "SAPI_RATE": str(rate), "SAPI_OUT": str(wav), "SAPI_TEXT": text}
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", SAPI_PS], env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if proc.returncode != 0 or not wav.is_file():
        raise CardError("Windows 내장 한국어 음성이 없습니다" if proc.returncode == 3 else proc.stderr.strip()[-200:])
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "3", str(path)],
                   check=True, capture_output=True)
    wav.unlink(missing_ok=True)


SAFE_FORMAT = "reelsafe"
# 인스타 릴스 UI가 덮는 곳(SNS 레퍼런스 허브 플랫폼 규격): 위 250px, 아래 420px(캡션·버튼), 오른쪽 120px(좋아요·댓글).
# 키트의 reel은 카드를 화면 폭 그대로(1080) 둬서 오른쪽 글자와 자막(카드 아래 끝)이 이 영역에 걸린다
# → 카드를 0.8배로 줄여 가운데에 두는 형식을 키트 설정에 한 번 추가해 쓴다(키트는 git 밖이라 PC마다 자동으로).
SAFE_LAYOUT = {"cardScale": 0.8, "cardTop": 300}
SAFE_SIDE = 130


def ensure_safe_format() -> str:
    cfg_path = video_dir() / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    want = {**cfg["formats"]["reel"], **SAFE_LAYOUT}
    # 아래 진행 줄·장 번호(chrome)도 오른쪽 120px 밖에 오게: 좌우 여백 130px 이상
    if cfg["formats"].get(SAFE_FORMAT) != want or cfg["chrome"].get("sideMargin", 0) < SAFE_SIDE:
        cfg["formats"][SAFE_FORMAT] = want
        cfg["chrome"]["sideMargin"] = max(cfg["chrome"].get("sideMargin", 0), SAFE_SIDE)
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return SAFE_FORMAT


def make_card_reel(deck: dict, set_dir: Path, out_dir: Path, voice: str | None = None,
                   bgm: Path | None = None, timeout: int = 900) -> ReelResult:
    ok, why = check_engine()
    if not ok:
        raise CardError(why)
    if not (video_dir() / "video.cjs").is_file():
        raise CardError(f"cardnews-video 스킬이 없습니다: {video_dir()}")
    if not shutil.which("ffmpeg"):
        raise CardError("ffmpeg가 없습니다 (PATH 확인)")
    if not (set_dir / "cards.html").is_file():
        raise CardError(f"구운 카드 세트가 없습니다: {set_dir} — 먼저 --cards-from 으로 카드를 굽는다")
    voice = voice or VOICES.get(os.getenv("SHORTS_VOICE", "female"), os.getenv("SHORTS_VOICE") or VOICES["female"])
    lines = narration_lines(deck)

    # 한글 경로에서 node가 죽으므로(cardnews.render_deck 참고) 영문 임시 폴더에서 만든다
    with tempfile.TemporaryDirectory(prefix="cardreel-") as tmp:
        work = Path(tmp) / "set"
        shutil.copytree(set_dir, work, ignore=shutil.ignore_patterns("out", "preview", "video"))
        html = (work / "cards.html").read_text(encoding="utf-8")
        script = f"<script>\n{TYPEWRITER.read_text(encoding='utf-8')}\n</script>\n"
        (work / "cards.html").write_text(html.replace("</head>", script + HIDE_SWIPE, 1), encoding="utf-8")
        narration, engine = synthesize_lines(lines, work / "voice", card_voices(deck, voice))
        (work / "narration.json").write_text(json.dumps({"cards": narration}, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
        fmt = ensure_safe_format()
        proc = subprocess.run(["node", str(video_dir() / "video.cjs"), str(work), "--format", fmt],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout).strip().splitlines()
            raise CardError("릴스 렌더 실패: " + (msg[-1] if msg else f"종료 코드 {proc.returncode}"))
        made = work / "video" / f"{fmt}.mp4"
        if not made.is_file():
            raise CardError("릴스 파일이 만들어지지 않았습니다: " + proc.stdout.strip()[-300:])
        out_dir.mkdir(parents=True, exist_ok=True)
        video = out_dir / "cards_reel.mp4"
        bgm_name = ""
        if bgm and bgm.is_file():
            _mix_bgm(made, bgm, video)
            bgm_name = bgm.name
        else:
            shutil.copy2(made, video)
        frames_src = work / "video" / f"{fmt}-frames.png"
        frames = out_dir / "cards_reel-frames.png"
        if frames_src.is_file():
            shutil.copy2(frames_src, frames)
        (out_dir / "cards_reel_script.txt").write_text(
            "\n".join(f"[{i}] {' / '.join(x)}" for i, x in enumerate(lines, start=1)) + "\n", encoding="utf-8")
    return ReelResult(video, frames if frames.exists() else None, _duration(video),
                      sum(len(x) for x in lines), bgm_name, engine)


def _mix_bgm(video: Path, bgm: Path, out: Path) -> None:
    """나레이션 아래에 BGM을 낮게 깐다 (영상 길이에 맞춰 반복, 끝 2초 페이드아웃)."""
    dur = _duration(video)
    fade = max(dur - 2, 0)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-stream_loop", "-1", "-i", str(bgm),
           "-filter_complex",
           f"[1:a]volume={BGM_VOLUME},afade=t=out:st={fade:.2f}:d=2[b];[0:a][b]amix=inputs=2:duration=first:dropout_transition=0[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise CardError("BGM 합성 실패: " + proc.stderr.strip()[-200:])


def _duration(path: Path) -> float:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True)
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def default_bgm() -> Path | None:
    return pick_bgm(PROJECT_DIR)
