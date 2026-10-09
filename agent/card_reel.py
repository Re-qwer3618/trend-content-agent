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

from . import characters
from .cardnews import CardError, check_engine, engine_dir
from .config import PROJECT_DIR
from .shorts_maker import VOICES, _speakable, pick_bgm

HIDE_SWIPE = "<style>.swipe { visibility: hidden; }</style>\n</head>"
BGM_VOLUME = 0.12


@dataclass
class ReelResult:
    video: Path
    frames: Path | None
    duration: float
    lines: int
    bgm: str


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
    return [{**base, **(characters.voice(c.get("speaker")) or host or {})} for c in deck["cards"]]


def synthesize_lines(lines: list[list[str]], voice_dir: Path, voices: list[dict]) -> list[list[dict]]:
    import edge_tts

    voice_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for i, (card_lines, v) in enumerate(zip(lines, voices), start=1):
        entries = []
        for k, text in enumerate(card_lines, start=1):
            path = voice_dir / f"{i:02d}-{k}.mp3"
            for attempt in range(3):
                try:
                    edge_tts.Communicate(_speakable(text), v["name"], rate=v["rate"], pitch=v["pitch"]).save_sync(str(path))
                    if path.stat().st_size > 0:
                        break
                except Exception as e:  # edge-tts는 네트워크 오류를 여러 종류로 던진다
                    if attempt == 2:
                        raise CardError(f"나레이션 합성 실패 ({i}번 장): {e}") from e
            entries.append({"show": text, "file": f"voice/{path.name}"})
        cards.append(entries)
    return cards


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
        (work / "cards.html").write_text(html.replace("</head>", HIDE_SWIPE, 1), encoding="utf-8")
        narration = synthesize_lines(lines, work / "voice", card_voices(deck, voice))
        (work / "narration.json").write_text(json.dumps({"cards": narration}, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
        proc = subprocess.run(["node", str(video_dir() / "video.cjs"), str(work), "--format", "reel"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout).strip().splitlines()
            raise CardError("릴스 렌더 실패: " + (msg[-1] if msg else f"종료 코드 {proc.returncode}"))
        made = work / "video" / "reel.mp4"
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
        frames_src = work / "video" / "reel-frames.png"
        frames = out_dir / "cards_reel-frames.png"
        if frames_src.is_file():
            shutil.copy2(frames_src, frames)
        (out_dir / "cards_reel_script.txt").write_text(
            "\n".join(f"[{i}] {' / '.join(x)}" for i, x in enumerate(lines, start=1)) + "\n", encoding="utf-8")
    return ReelResult(video, frames if frames.exists() else None, _duration(video),
                      sum(len(x) for x in lines), bgm_name)


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
