"""노션 → 프로젝트 동기화 (run.bat --sync-notion). 노션이 원본이고, 이 모듈은 ntn CLI(노션 로그인)로 읽어 파일을 다시 쓴다.

- 캐릭터 프로필 DB(캐릭터ID가 있는 행) → agent/prompts/characters.json
  노션에 없는 필드(name·_doc)와 노션에 없는 캐릭터는 그대로 둔다. 얼굴 자르는 영역(AVATAR_BOX)은 characters.py에.
- 디자인 레퍼런스 허브(카테고리 SNS/카드뉴스) → 스킬 references/sns-hub-rules.md (자동 생성, 손으로 고치지 않음)
  사람이 고른 요약 sns-reference.md는 건드리지 않는다 — 허브가 바뀌었다고 나오면 그 파일을 같이 손본다.
- 콘텐츠 예시 DB(상태 채택·후보) → agent/prompts/examples/ (index.json + 세트마다 카드 JSON)
  우리 콘텐츠는 본문의 ```json 카드 코드 블록(attach_deck이 붙인다), 외부 사례(다른 계정)는 ```markdown 구조 요약 블록.
  채택 행이 카드·릴스 작성의 본보기가 된다(외부 사례는 구조만 — 문구·사진·캐릭터는 가져오지 않음).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .config import PROJECT_DIR

CHAR_DS = "4f14d8ef-8a6d-4fd2-b9e6-4618e8e35177"     # AI 엔터테인먼트 캐릭터 프로필
HUB_DS = "8a5b120a-2719-46c7-9d45-8169e3fc99f2"      # 🎨 디자인 레퍼런스 허브
EXAMPLE_DS = "80cd5120-2971-4dde-ac5c-5a75ff2d6570"  # 콘텐츠 예시 (본보기)
HUB_CATEGORY = "SNS/카드뉴스"

PROMPT_DIR = PROJECT_DIR / "agent" / "prompts"
CHAR_FILE = PROMPT_DIR / "characters.json"
EXAMPLE_DIR = PROMPT_DIR / "examples"
HUB_FILE = PROJECT_DIR / ".claude" / "skills" / "trend-content-style" / "references" / "sns-hub-rules.md"
CODE_CHUNK = 1900  # 노션 rich_text 한 조각은 2000자까지


class SyncError(RuntimeError):
    pass


# ---------- ntn api ----------

def _api(path: str, method: str | None = None, body: dict | None = None) -> dict:
    exe = shutil.which("ntn")
    if not exe:
        raise SyncError("ntn(Notion CLI)이 없습니다 — PATH의 tools\\ntn\\node_modules\\.bin 확인, 로그인은 ntn login")
    cmd = [exe, "api", path] + (["-X", method] if method else []) + (["-d", "@-"] if body is not None else [])
    proc = subprocess.run(cmd, input=json.dumps(body, ensure_ascii=False) if body is not None else None,
                          stdin=None if body is not None else subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if proc.returncode != 0:
        raise SyncError(f"ntn api {path} 실패: " + (proc.stderr or proc.stdout).strip()[-300:])
    return json.loads(proc.stdout or "{}")


def _query(ds: str) -> list[dict]:
    rows, cursor = [], None
    while True:
        body = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
        data = _api(f"/v1/data_sources/{ds}/query", "POST", body)
        rows += data.get("results", [])
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")


def _children(block_id: str) -> list[dict]:
    out, cursor = [], None
    while True:
        data = _api(f"/v1/blocks/{block_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else ""))
        out += data.get("results", [])
        if not data.get("has_more"):
            return out
        cursor = data.get("next_cursor")


def _url(page: dict) -> str:
    return "https://app.notion.com/p/" + page["id"].replace("-", "")


def _val(page: dict, name: str):
    """속성 값을 파이썬 값으로: 글 → str, 선택 → str, 다중 선택 → list, 숫자, url, 관계 → id 목록."""
    p = page.get("properties", {}).get(name)
    if not p:
        return None
    t = p["type"]
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in p[t]).strip()
    if t in ("select", "status"):
        return (p[t] or {}).get("name")
    if t == "multi_select":
        return [x["name"] for x in p[t]]
    if t == "relation":
        return [x["id"] for x in p[t]]
    return p.get(t)


# ---------- 캐릭터 ----------

def _voice(text: str) -> dict | None:
    """'ko-KR-SunHiNeural +4% +6Hz' → {name, rate, pitch}"""
    parts = (text or "").split()
    if not parts:
        return None
    rate = next((x for x in parts[1:] if x.endswith("%")), "+0%")
    pitch = next((x for x in parts[1:] if x.lower().endswith("hz")), "+0Hz")
    return {"name": parts[0], "rate": rate, "pitch": pitch}


def _pairs(text: str, sep: str) -> dict:
    """'shock=a, smile=b' 또는 'shock=... | smile=...' → 순서 있는 dict"""
    out = {}
    for part in (text or "").split(sep):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _character(page: dict, old: dict) -> dict:
    images = _pairs(_val(page, "이미지 키"), ",")
    mascot = _val(page, "구분") == "마스코트"
    c = {"name": old.get("name") or _val(page, "활동명"), "kind": "mascot" if mascot else "virtual_human"}
    if not mascot:
        age, keys = _val(page, "설정 나이"), _val(page, "캐릭터 키워드") or []
        c["profile"] = " · ".join(x for x in [_val(page, "활동명"), f"{int(age)}세" if age else "",
                                             _val(page, "소속/그룹") or "", "·".join(keys)] if x)
    c["persona"] = _val(page, "말투") or old.get("persona", "")
    c["images"] = images
    c["avatar"] = next(iter(images.values()), None)
    if not images:
        c["badge"] = _val(page, "배지") or old.get("badge") or c["name"][:1]
    c["voice"] = _voice(_val(page, "음성")) or old.get("voice")
    c["topics"] = _val(page, "어울리는 주제") or old.get("topics", [])
    if _val(page, "생성 프롬프트"):
        seed = _val(page, "시드")
        c["gen"] = {**({"seed": int(seed)} if seed is not None else {}), "prompt": _val(page, "생성 프롬프트"),
                    "moods": _pairs(_val(page, "표정 프롬프트"), "|")}
        poses = _pairs(_val(page, "포즈 프롬프트"), "|")  # peek=… (오른쪽 위 설명 컷, 흰 배경 통째 프롬프트)
        if poses:
            c["gen"]["poses"] = poses
    c["notion"] = _url(page)
    return c


def sync_characters(rows: list[dict]) -> list[str]:
    data = json.loads(CHAR_FILE.read_text(encoding="utf-8"))
    report, seen = [], set()
    for page in rows:
        cid = _val(page, "캐릭터ID")
        if not cid:
            continue
        seen.add(cid)
        new = _character(page, data.get(cid, {}))
        if cid not in data:
            report.append(f"  + {cid} {new['name']} (새 캐릭터)")
        elif new != data[cid]:
            diff = sorted(k for k in set(new) | set(data[cid]) if new.get(k) != data[cid].get(k))
            report.append(f"  ~ {cid} {new['name']}: {', '.join(diff)}")
        data[cid] = new
    for cid in data:
        if not cid.startswith("_") and cid not in seen:
            report.append(f"  ? {cid}: 노션에 캐릭터ID 행이 없어 그대로 둠")
    CHAR_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from . import characters
    characters.all_characters.cache_clear()
    return report or ["  (바뀐 것 없음)"]


# ---------- 레퍼런스 허브 ----------

def sync_hub(rows: list[dict]) -> list[str]:
    picked = []
    for page in rows:
        cat = _val(page, "카테고리")
        if HUB_CATEGORY in (cat if isinstance(cat, list) else [cat]):
            picked.append(page)
    picked.sort(key=lambda p: _val(p, "사이트 이름") or "")
    lines = ["# SNS 레퍼런스 허브 원문 (자동 생성 — 손으로 고치지 않는다)", "",
             f"`run.bat --sync-notion`이 노션 🎨 디자인 레퍼런스 허브(`collection://{HUB_DS}`)의 "
             f"`카테고리 = {HUB_CATEGORY}` 행을 그대로 옮긴 것. 이 프로젝트에 맞게 고른 규칙은 `sns-reference.md`가 기준이고,",
             "이 파일과 어긋나면 sns-reference.md를 손본다.", ""]
    for p in picked:
        use = _val(p, "핵심 용도")
        lines += [f"## {_val(p, '사이트 이름')}" + (f" — {', '.join(use) if isinstance(use, list) else use}" if use else ""), ""]
        for field in ("활용 팁 및 특징", "적용 규칙"):
            if _val(p, field):
                lines += [f"**{field}**: {_val(p, field)}", ""]
        if _val(p, "링크"):
            lines += [f"링크: {_val(p, '링크')}", ""]
    text = "\n".join(lines).rstrip() + "\n"
    old = HUB_FILE.read_text(encoding="utf-8") if HUB_FILE.exists() else ""
    if text == old:
        return [f"  (바뀐 것 없음, {len(picked)}행)"]
    HUB_FILE.write_text(text, encoding="utf-8")
    return [f"  ~ {HUB_FILE.name} 갱신 ({len(picked)}행) — sns-reference.md도 맞는지 확인"]


# ---------- 콘텐츠 예시 ----------

def _code_blocks(page_id: str, language: str) -> list[str]:
    return ["".join(x.get("plain_text", "") for x in b["code"]["rich_text"]) for b in _children(page_id)
            if b["type"] == "code" and b["code"].get("language") == language]


def _deck_from_page(page_id: str) -> dict | None:
    for text in _code_blocks(page_id, "json"):
        try:
            deck = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(deck, dict) and deck.get("cards"):
            return deck
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^\w가-힣]+", "_", text).strip("_")[:40] or "example"


def sync_examples(rows: list[dict], char_rows: list[dict]) -> list[str]:
    ids = {p["id"]: _val(p, "캐릭터ID") for p in char_rows if _val(p, "캐릭터ID")}
    EXAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    index, report, keep = [], [], {"index.json"}
    for page in sorted(rows, key=lambda p: p.get("created_time", "")):
        status = _val(page, "상태")
        if status not in ("채택", "후보"):
            continue
        title = _val(page, "제목")
        source = _val(page, "출처") or "우리 콘텐츠"
        if source == "외부 사례":  # 다른 계정 사례: 문구·사진 없이 본문 ```markdown 구조 요약만
            summary = "\n".join(_code_blocks(page["id"], "markdown")).strip()
            if not summary:
                report.append(f"  ! {title}: 본문에 ```markdown 구조 요약 코드 블록이 없어 건너뜀")
                continue
            file = f"{_slug(title)}.md"
            (EXAMPLE_DIR / file).write_text(summary + "\n", encoding="utf-8")
        else:
            deck = _deck_from_page(page["id"])
            if not deck:
                report.append(f"  ! {title}: 본문에 ```json 카드 코드 블록이 없어 건너뜀 (run.bat --attach-cards)")
                continue
            file = f"{_slug(title)}.json"
            (EXAMPLE_DIR / file).write_text(json.dumps(deck, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        keep.add(file)
        index.append({"title": title, "status": status, "source": source, "account": _val(page, "계정") or "",
                      "formats": _val(page, "형식") or [],
                      "topics": _val(page, "주제") or [], "hook": _val(page, "훅 유형"),
                      "why": _val(page, "잘된 이유") or "", "characters": [ids[i] for i in _val(page, "캐릭터") or [] if i in ids],
                      "metrics": {k: _val(page, k) for k in ("저장", "공유", "댓글") if _val(page, k) is not None},
                      "notion": _url(page), "file": file})
        report.append(f"  · [{status}·{source}] {title}")
    for stale in [*EXAMPLE_DIR.glob("*.json"), *EXAMPLE_DIR.glob("*.md")]:
        if stale.name not in keep:
            stale.unlink()
            report.append(f"  - {stale.name} (노션에서 빠져 지움)")
    (EXAMPLE_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report or ["  (예시 없음)"]


def attach_deck(page: str, deck_file: Path) -> int:
    """카드 JSON을 예시 페이지 본문 끝에 ```json 코드 블록으로 붙인다 (동기화가 이 블록을 읽는다)."""
    page_id = re.sub(r"[^0-9a-f]", "", page.split("?")[0].split("/")[-1].lower())[-32:]
    deck = json.loads(deck_file.read_text(encoding="utf-8"))
    text = json.dumps(deck, ensure_ascii=False, indent=1)
    chunks = [text[i:i + CODE_CHUNK] for i in range(0, len(text), CODE_CHUNK)]
    block = {"object": "block", "type": "code",
             "code": {"language": "json", "rich_text": [{"type": "text", "text": {"content": c}} for c in chunks]}}
    _api(f"/v1/blocks/{page_id}/children", "PATCH", {"children": [block]})
    return len(text)


def sync_all(log=print) -> None:
    log("노션 동기화 (읽기 전용 — 노션이 원본)")
    char_rows = _query(CHAR_DS)
    log("▸ 캐릭터 → agent/prompts/characters.json")
    for line in sync_characters(char_rows):
        log(line)
    log("▸ 레퍼런스 허브 → 스킬 references/sns-hub-rules.md")
    for line in sync_hub(_query(HUB_DS)):
        log(line)
    log("▸ 콘텐츠 예시 → agent/prompts/examples/")
    for line in sync_examples(_query(EXAMPLE_DS), char_rows):
        log(line)
    log("바뀐 파일은 git diff로 확인하고 커밋한다 (노션 → 파일 한 방향).")
