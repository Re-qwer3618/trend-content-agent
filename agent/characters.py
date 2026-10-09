"""출연 캐릭터 — prompts/characters.json (페르소나·음성·이미지).

마스코트(꼬북이·토끼양)는 노션 에셋 모음집의 미니어처 인형 사진을 그대로 쓴다(얼굴이 고정이라 매번 같은 캐릭터).
가상 인물(명숙 할머니 등)은 아직 기준 이미지가 없어 말투·목소리로만 출연하고, 카드에는 이름 글자 배지로 표시한다.
이미지는 assets/characters/ (git 제외): <id>.png 원본 → prep()이 <id>.jpg(1080, 카드용)와 <id>_avatar.png(원형)를 만든다.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .config import PROJECT_DIR

CHAR_FILE = Path(__file__).parent / "prompts" / "characters.json"
ASSET_DIR = PROJECT_DIR / "assets" / "characters"
# 원본에서 얼굴을 잘라 원형 아바타를 만드는 영역 (2048px 원본 기준)
AVATAR_BOX = {"kkobuk": (660, 600, 1280, 1220), "tokki_v1": (660, 580, 1310, 1230), "tokki_v2": (650, 600, 1300, 1250)}


@lru_cache(maxsize=1)
def all_characters() -> dict:
    data = json.loads(CHAR_FILE.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def get(cid: str | None) -> dict | None:
    return all_characters().get(cid) if cid else None


def image_path(cid: str, mood: str | None = None) -> Path | None:
    c = get(cid)
    if not c or not c.get("images"):
        return None
    key = c["images"].get(mood) or next(iter(c["images"].values()))
    p = ASSET_DIR / f"{key}.jpg"
    return p if p.is_file() else None


def avatar_path(cid: str) -> Path | None:
    c = get(cid)
    if not c or not c.get("avatar"):
        return None
    p = ASSET_DIR / f"{c['avatar']}_avatar.png"
    return p if p.is_file() else None


def voice(cid: str | None) -> dict | None:
    c = get(cid)
    return c.get("voice") if c else None


def prep() -> list[str]:
    """원본 png → 카드용 jpg + 원형 아바타. 이미 있으면 건너뛴다."""
    from PIL import Image, ImageDraw

    made = []
    for src in sorted(ASSET_DIR.glob("*.png")):
        if src.stem.endswith("_avatar"):
            continue
        jpg = src.with_suffix(".jpg")
        if not jpg.exists():
            Image.open(src).convert("RGB").resize((1080, 1080), Image.LANCZOS).save(jpg, quality=86)
            made.append(jpg.name)
        box = AVATAR_BOX.get(src.stem)
        ava = src.with_name(f"{src.stem}_avatar.png")
        if box and not ava.exists():
            im = Image.open(src).convert("RGB").crop(box).resize((320, 320), Image.LANCZOS)
            mask = Image.new("L", im.size, 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 319, 319), fill=255)
            out = Image.new("RGBA", im.size)
            out.paste(im, (0, 0), mask)
            out.save(ava)
            made.append(ava.name)
    return made
