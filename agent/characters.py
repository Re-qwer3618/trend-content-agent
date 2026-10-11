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
# 원본에서 얼굴을 잘라 원형 아바타를 만드는 영역 — 비율(왼, 위, 오른, 아래). 노션 인형 사진은 얼굴 위치를 재서 지정,
# --make-character로 만든 그림은 '가운데 인물' 프롬프트라 기본값(가운데 위쪽)을 쓴다
AVATAR_BOX = {"kkobuk": (0.322, 0.293, 0.625, 0.596), "tokki_v1": (0.322, 0.283, 0.640, 0.601),
              "tokki_v2": (0.317, 0.293, 0.635, 0.610),
              "fan_shock": (0.30, 0.30, 0.70, 0.70), "fan_smile": (0.30, 0.30, 0.70, 0.70)}
AVATAR_DEFAULT = (0.28, 0.14, 0.72, 0.58)


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
        ava = src.with_name(f"{src.stem}_avatar.png")
        if not ava.exists():
            im = Image.open(src).convert("RGB")
            l, t, r, b = AVATAR_BOX.get(src.stem, AVATAR_DEFAULT)
            im = im.crop((int(l * im.width), int(t * im.height), int(r * im.width), int(b * im.height)))
            im = im.resize((320, 320), Image.LANCZOS)
            mask = Image.new("L", im.size, 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 319, 319), fill=255)
            out = Image.new("RGBA", im.size)
            out.paste(im, (0, 0), mask)
            out.save(ava)
            made.append(ava.name)
    return made


def make(cid: str, force: bool = False, log=print) -> list[str]:
    """characters.json의 gen(프롬프트·표정·seed)으로 표정별 이미지를 만든다 — 같은 seed라 얼굴·옷·배경이 이어진다.
    무료 Pollinations(프롬프트가 외부 서비스로 전송됨). 만든 뒤 prep()으로 카드용 jpg·아바타까지."""
    import os
    import time
    import zlib
    from urllib.parse import quote

    import requests

    c = get(cid)
    if not c or not c.get("gen"):
        raise ValueError(f"{cid}: characters.json에 gen(프롬프트)이 없습니다")
    gen = c["gen"]
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    token = os.getenv("POLLINATIONS_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    interval = float(os.getenv("POLLINATIONS_INTERVAL", "35"))
    made, last = [], 0.0
    for mood, key in c["images"].items():
        out = ASSET_DIR / f"{key}.png"
        if out.exists() and not force:
            continue
        # 무료 모델은 앞쪽 70단어 안팎만 읽는다 → 스타일·인물 → {mood}(표정) → 장소 순서의 짧은 문장 하나
        prompt = gen["prompt"].replace("{mood}", gen["moods"].get(mood, ""))
        seed = gen.get("seed", zlib.crc32(cid.encode()) % 10**6)
        for attempt in range(3):
            time.sleep(max(0.0, last + interval - time.time()))
            r = requests.get("https://image.pollinations.ai/prompt/" + quote(prompt[:950], safe=""), headers=headers,
                             params={"width": 1024, "height": 1024, "nologo": "true", "seed": seed, "model": "flux"}, timeout=180)
            last = time.time()
            if r.ok and r.headers.get("content-type", "").startswith("image/"):
                from io import BytesIO
                from PIL import Image
                Image.open(BytesIO(r.content)).convert("RGB").save(out)
                for stale in (out.with_suffix(".jpg"), out.with_name(f"{out.stem}_avatar.png")):
                    stale.unlink(missing_ok=True)
                made.append(out.name)
                log(f"  · {c['name']} {mood} → {out.name}")
                break
            log(f"  ! {mood} HTTP {r.status_code} — 다시 시도")
        else:
            raise RuntimeError(f"{cid} {mood} 이미지 생성 실패 (무료 등급 속도 제한일 수 있음)")
    return made + prep()
