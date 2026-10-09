---
name: cardnews-mumohan
description: 인스타그램 "무모한도전"(@adoni_s3618) 채널의 카드뉴스 키트. 이 채널용 카드뉴스, 트렌드 리포트의 피드 카드, "카드 굽기"에서 cardnews-engine과 함께 쓴다. 카드 문구는 trend-content-style 스킬과 agent/prompts/cards.md 규칙, 굽기는 run.bat --cards-from.
---

# 무모한도전 카드뉴스 키트

- 채널 이름 `무모한도전`, 계정 `@adoni_s3618` — `kit/kit.json`의 `tokens`. 카드 머리글과 마지막 장에 자동으로 채워진다.
- 짜임은 `cardnews-starter`의 `series`(밝은 바탕, 두 줄 제목, 장의 절반인 화면)를 그대로 쓰고, `kit/mumohan.css`가 덧입힌다:
  주황 강조색 `#e8541c`, 모든 장 아래의 사선 **도전 테이프**(표지는 위아래), 머리글 채널 이름 강조.
  starter를 불러오므로 `cardnews-starter`가 같은 스킬 폴더에 있어야 한다.
- 카드 문구·굽기는 이 프로젝트 방식대로: `reports/<리포트>_cards.json` → `run.bat --cards-from reports\<리포트>.md`
  (`agent/cardnews.py`가 cards.html을 만들어 `cardnews-engine`의 `render.cjs`로 굽는다). 문구 규칙은 `agent/prompts/cards.md`.
- 색을 바꿀 땐 `kit/mumohan.css`의 `--accent` 한 줄과 `kit/kit.json`의 `video.accent`를 같이 고친다. 흰 글자가 읽히는 진한 색만.
- 기준은 `references/brand.md`.
