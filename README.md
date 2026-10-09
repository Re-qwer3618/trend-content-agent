# trend-content-agent

네이버·유튜브·구글·인스타그램의 최신 트렌드를 모으고 분석해서 **네이버 블로그 포스팅 기획서**와 **인스타그램 릴스 기획서**를 마크다운 리포트로 만들어 주는 CLI입니다.

## 실행

```bat
run.bat "가을 캠핑"                     :: 리서치 + 기획서 + 웹 LLM용 제작 요청 프롬프트 (LLM API 비용 0)
run.bat "가을 캠핑" --mode api          :: LLM API로 원고·대본까지 직접 생성 (유료)
run.bat "가을 캠핑" --mode auto         :: API 시도, 크레딧 부족 등 실패분만 요청 프롬프트로
run.bat                                 :: 키워드 입력 프롬프트 (엔터 = 오늘의 트렌드)
run.bat --today                         :: 오늘의 급상승 트렌드에서 주제 선정
run.bat "러닝화" --formats blog --llm gemini --limit 30
run.bat "러닝화" --sources google_news youtube
run.bat "러닝화" --no-draft --no-web    :: 기획서만 (빠르고 저렴)
run.bat "러닝화" --make-images          :: 리포트 + 썸네일·커버 이미지 생성 (images\)
run.bat --images-from reports\20261002_0019_가을_캠핑.md   :: 기존 리포트로 이미지만
run.bat "가을 캠핑" --make-cards        :: 리포트 + 인스타 피드 카드뉴스 PNG (images\<리포트>\cards\)
run.bat --cards-from reports\…_가을_캠핑.md   :: 고친 카드 문구(…_cards.json)로 카드만 다시 굽기
run.bat --cards-from reports\…_가을_캠핑.md --card-reel   :: 카드 + 카드형 릴스(9:16 mp4, 나레이션·자막)
run.bat --check                         :: 키·수집기·LLM·카드뉴스 엔진 상태 확인
run.bat --today --list                  :: 기획서 없이 이슈 TOP 10 목록만 (reports\..._issues.md/.json)
run.bat --pick 2 5                      :: 최근 목록의 2·5위를 그 이슈 검색어로 다시 수집해 상세 리포트
```

### 이슈 목록 → 골라서 작성

1. `--today --list`로 이슈 1~10위 목록만 만듭니다. 각 이슈에는 상세 작성 때 쓸 검색어(구글 급상승어는 검색어 그대로, 영상·기사는 제목을 다듬은 것)가 붙습니다.
2. 원하는 순위를 `--pick 번호`로 고르면 그 검색어로 키워드 모드를 다시 돌려(뉴스·영상 추가 수집) 기획서·요청 프롬프트가 든 상세 리포트를 만듭니다. 목록 파일은 `--from`으로 지정할 수 있고, 생략하면 가장 최근 것을 씁니다.

Claude 데스크톱 앱의 예약 작업이 이 두 단계로 노션 `Trend-Reports`에 매일 목록 페이지를 만들고, 체크된 이슈를 상세 리포트로 작성합니다(설정은 `CLAUDE.md`).

결과는 `reports\YYYYMMDD_HHMM_키워드.md`, 수집 원본 JSON은 `data\raw\`에 저장됩니다.
LLM을 쓰면 블로그 본문 원고와 릴스 대본이 `..._blog_원고.md`, `..._reels_대본.md`로도 따로 저장됩니다.

## 생성 모드 (`GENERATION_MODE`, 기본 `prompt`)

| 모드 | LLM API | 결과 |
|---|---|---|
| `prompt` (기본) | 호출 안 함 | 규칙 기반 분석·기획서 골격 + **LLM 제작 요청 프롬프트** (`..._요청_blog.txt`, `_요청_reels.txt`, `_요청_channels.txt`(인스타 피드 카드뉴스+유튜브), `_요청_images.txt`) |
| `api` | 호출 (유료) | LLM이 기획서 → 발행용 원고 / 촬영 대본, 이미지 프롬프트까지 작성 |
| `auto` | 시도 | API로 만들고, 크레딧 부족 등으로 실패한 부분만 요청 프롬프트로 대체 |

요청 프롬프트는 수집 데이터·출처 URL·작성 지침이 다 들어간 **한 번에 붙여 넣는** 형태입니다.
웹 검색이 되는 ChatGPT(검색 켜기)·Claude.ai·Gemini에 `.txt` 내용을 통째로 붙여 넣으면 기획서와 완성 원고가 한 답변에 나옵니다.
작성 지침은 API 모드와 같은 `agent/prompts/*.md`를 쓰므로, 지침을 고치면 두 모드에 같이 반영됩니다.

## 리포트 구성

1. 요약 · 수집 현황 · 핵심 이슈 · 연관 키워드
2. **네이버 블로그**: 기획서(제목 후보, SEO 키워드 배치 맵, 구성안) → **발행용 본문 원고**(출처 링크, 사진 자리, 태그 포함)
3. **인스타 릴스**: 기획서(3초 훅, 스토리보드) → **촬영·편집 대본**(컷별 화면·자막·나레이션, 나레이션 전문, 캡션)
4. 부록: 이슈별 원문 링크
5. **이미지 생성 프롬프트**: 상위 이슈별 블로그 썸네일(1:1)·릴스 커버(9:16) 영문 프롬프트, 네거티브 프롬프트, 얹을 한글 문구, alt 텍스트

원고·대본 단계는 수집 데이터가 헤드라인 위주라 **웹 검색으로 기사 원문을 확인하며** 씁니다(Claude `web_search` / Gemini Google 검색).
확인하지 못한 기간·요금 같은 세부 정보는 `[확인 필요]`로 남으니 발행 전에 채우세요.
한 번 실행에 LLM을 약 7번 호출합니다(인사이트 1, 기획서 2, 완성본 2, 이미지 1, 카드뉴스 1). 비용을 줄이려면 `--no-draft`, `--no-web`, `--no-images`를 쓰세요.

## 파이프라인

```
main.py (CLI)
  └─ collectors.collect_all()   플랫폼별 병렬 수집 → TrendItem 공통 형식
  └─ analyzer.analyze()         이슈 묶기·점수, 연관 키워드, 네이버 데이터랩 검색량, (LLM) 인사이트
  └─ generator.generate()       블로그 / 릴스: 기획서 → 완성본(웹 검색 근거) — LLM 없으면 템플릿 골격
  └─ images.generate_image_prompts()  이슈별 썸네일·커버 이미지 프롬프트(영문)
  └─ report.save_report()       마크다운 리포트
```

```
trend-content-agent/
├─ main.py                  CLI 진입점
├─ run.bat                  agent-py313으로 main.py 실행
├─ agent/
│  ├─ config.py             .env 로드(프로젝트 > 중앙), 설정
│  ├─ collectors/
│  │  ├─ base.py            TrendItem, BaseCollector (실패해도 파이프라인은 계속)
│  │  ├─ google.py          구글 트렌드 실시간 RSS, 구글 뉴스 RSS  ← 키 불필요
│  │  ├─ naver.py           네이버 뉴스·블로그 검색, 데이터랩 검색어 트렌드
│  │  ├─ youtube.py         YouTube Data API v3 (검색 / 인기 급상승)
│  │  └─ instagram.py       Instagram Graph API 해시태그 (선택)
│  ├─ analyzer.py           핵심 이슈 선별·연관 키워드·LLM 인사이트(JSON 스키마)
│  ├─ llm.py                Claude / Gemini 공통 인터페이스
│  ├─ generator.py          기획서 → 완성본 2단계 생성 + LLM 없을 때 템플릿
│  ├─ images.py             이미지 생성 프롬프트 (LLM 없으면 템플릿)
│  ├─ image_maker.py        프롬프트 → 실제 이미지 (OpenAI / Gemini / Pollinations 무료)
│  ├─ card_reel.py          카드형 릴스: 카드 세트 + edge-tts 나레이션 → 9:16 mp4 (cardnews-video 호출)
│  ├─ cardnews.py           카드뉴스: 카드 문구 JSON → cards.html → PNG (cardnews-kit 스킬의 렌더러 호출)
│  ├─ shorts_maker.py       쇼츠 영상: edge-tts 나레이션 + 단어 타이밍 자막 + 스톡 영상/이미지 → mp4
│  ├─ report.py             마크다운 리포트·원본 JSON 저장
│  └─ prompts/              system.md, blog.md, reels.md (기획서), blog_draft.md, reels_script.md (완성본)
├─ .github/workflows/trend_bot.yml   매일 자동 실행 (GitHub Actions)
├─ reports/                 생성된 리포트 (git 제외)
├─ images/                  생성된 이미지 (git 제외)
├─ videos/                  생성된 쇼츠 영상 (git 제외)
├─ assets/bgm/              배경음악 넣는 곳 (선택, git 제외)
└─ data/raw/                수집 원본 (git 제외)
```

## 쇼츠·릴스 영상 자동 제작 (agent/shorts_maker.py)

```bat
run.bat "가을 캠핑" --make-video                          :: 리포트 → 이미지 → 쇼츠 mp4 까지 한 번에 (전부 무료)
run.bat --video-from reports\20261002_0019_가을_캠핑.md     :: 대본 파일을 고친 뒤 영상만 다시 만들기
run.bat --video-from reports\…md --script 대본.txt --voice male   :: 웹 LLM이 쓴 대본 + 남성 음성
```

[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)(MIT)의 파이프라인 구성을 참고해 이 프로젝트에 맞게 다시 작성했습니다.

1. **대본** — 리포트를 만들 때 `…_쇼츠대본.txt`가 자동 저장됩니다(훅 → 상위 이슈 3개 → 저장 유도, 약 30초).
   API 모드면 LLM이 쓴 촬영 대본을, 프롬프트 모드면 `_요청_reels.txt` 결과를 이 파일에 붙여 넣어 쓰면 됩니다.
2. **나레이션** — edge-tts 한국어 음성(선희·인준·현수, 무료). 단어 단위 타이밍을 받아 **말과 정확히 맞는 자막**을 만듭니다.
3. **화면** — 장면마다 `PEXELS_API_KEY`가 있으면 Pexels 세로 스톡 영상, 없으면 그 이슈의 생성 이미지를 흐린 배경 + 천천히 흐르는 전경으로.
4. **합성** — 1080×1920·30fps mp4, 상단 장면 제목(노랑) + 하단 나레이션 자막(흰색, 인스타 UI에 안 가리는 위치), 장면 전환 페이드,
   `assets/bgm/`에 음원을 넣으면 배경음악. 프레임을 numpy로 직접 합성해 30초 영상이 **약 20초**에 만들어집니다.

결과: `videos\<리포트>\shorts.mp4`, `subtitles.srt`(업로드 시 자막 파일로도 사용), `script.txt`.

- edge-tts는 Microsoft Edge 읽어주기 서비스를 쓰는 비공식 라이브러리라, 너무 자주 호출하면 막힐 수 있습니다.
- 무료 이미지(Pollinations)는 워터마크·768px 제한이 있어 화질이 거칩니다. Pexels 키(무료)를 넣거나 직접 촬영 영상을 쓰면 좋아집니다.

## 인스타 피드 카드뉴스 (agent/cardnews.py)

```bat
run.bat "가을 캠핑" --make-cards                       :: 리포트 → 카드 문구 → 1080×1350 PNG
run.bat --cards-from reports\20261009_2148_가을_캠핑.md  :: …_cards.json을 고친 뒤 카드만 다시 굽기
```

1. **카드 문구** — 리포트를 만들 때 `…_cards.json`이 자동 저장됩니다. 규칙은 `agent/prompts/cards.md` 한 파일
   (8장 흐름, 장마다 다른 화면 칸, 근거 표기, `[확인 필요]`)이고 세 경로가 같이 씁니다.
   - 프롬프트 모드(기본): 수집한 제목·출처·날짜만으로 기본본(표지 → 상위 이슈 4장 → 확인할 것 → 마무리).
     `_요청_channels.txt`를 웹 LLM에 넣으면 답변 끝에 카드 JSON이 나오고, 그 답변을 파일로 저장해
     `run.bat --cards-from reports\….md --cards-file 답변.txt`로 굽습니다.
   - API 모드: LLM이 카드 문구를 바로 씁니다(호출 1번 추가, 실패하면 기본본).
   - Claude(노션 상세 리포트): 스킬 `trend-content-style`의 "카드뉴스 굽기" 순서로 JSON을 쓰고 굽습니다.
2. **굽기** — cardnews-kit의 `cardnews-engine` 스킬(`render.cjs`)이 로컬 Chrome으로 PNG를 만들고
   넘침·24px 미만 글자·어색한 줄바꿈을 자동 검사합니다. 경고는 실행 결과에 `!`로 나옵니다.
3. **결과** — `images\<리포트>\cards\out\NN-이름.png`(납품용), `preview\sheet.png`(모아보기), `preview\phone\`(휴대폰 폭).

설치(PC마다 한 번): 키트의 `skills\cardnews-engine`, `cardnews-starter`, `cardnews-video`를
이 프로젝트의 `.claude\skills\`에 복사(git 제외 — 키트 코드에 재배포 라이선스가 없음) → `cardnews-engine\scripts`에서 `npm install`(Node 18+, Chrome 또는 Edge 필요).
다른 위치에 두었다면 `.env`의 `CARDNEWS_ENGINE`. 엔진이 없으면 카드만 건너뛰고 리포트·영상은 그대로 만듭니다(`--check`로 확인).

### 캐릭터 출연 (agent/characters.py)

`agent/prompts/characters.json`의 캐릭터가 카드·릴스에 나옵니다 — 마스코트 꼬북이·토끼양(노션 에셋 모음집의 인형 사진),
가상 인물 명숙 할머니·세아·도윤(노션 캐릭터 프로필, 아직 이미지 없음 → 말투·목소리·이름 배지로만).
카드 JSON의 `host`(진행 캐릭터), 장마다 `speaker`+`line`(한마디 말풍선), 화면 칸 `character`(마스코트 리액션 컷 + 말풍선).
릴스는 장의 `speaker`(없으면 `host`) 목소리로 읽습니다(edge-tts 음성 + 속도·높낮이). 바이럴 포맷 규칙은 `agent/prompts/viral.md`.
이미지는 git 밖 `assets\characters\` — 새 PC에서는 `characters.json`의 노션 링크에서 원본 png를 받아 넣고 `run.bat --prep-characters`.

### 카드형 릴스 (agent/card_reel.py)

`--card-reel`을 붙이면 구운 카드를 세로 9:16 한 편(`videos\<리포트>\cards_reel.mp4`, 30초 안팎)으로 이어 붙입니다 — 전부 무료·로컬.
카드마다 `say`(릴스에서 읽을 말, `cards.md` 규칙)를 edge-tts로 읽고(`SHORTS_VOICE`·`--voice`), 키트의 `cardnews-video`가 장 전환·자막을 넣고,
`assets\bgm\`에 mp3가 있으면 낮게 깝니다. `say`가 없으면 제목(표지·마무리는 설명까지)을 읽습니다.
결과 옆에 장면 모음 `cards_reel-frames.png`와 읽은 문장 `cards_reel_script.txt`. 릴스용 복사본에서만 "밀어서 보기" 버튼을 숨깁니다(자막과 겹침).

## 블로그 원고 품질 (STORM 방식)

`agent/prompts/blog_draft.md`의 작성 절차에 [STORM](https://github.com/stanford-oval/storm)(MIT)의
"독자 관점 정하기 → 관점별 질문 → 질문마다 근거 검색 → 개요 → 집필 → 다듬기" 흐름을 넣었습니다.
API 모드와 웹 LLM용 제작 요청 프롬프트 양쪽에 같이 적용되며, 원고에 **FAQ 3개**와 **참고 자료 목록**이 추가됩니다.

## AI 영상·이미지 생성 프롬프트 규칙

릴스 기획서·촬영 대본의 "생성 프롬프트"와 썸네일 프롬프트는 `agent/prompts/visual_rules.md` 한 파일의 규칙을 따릅니다
([higgsfield-ai-prompt-skill](https://github.com/OSideMedia/higgsfield-ai-prompt-skill)(MIT)의 MCSLA 공식·카메라 용어·네거티브 지침을 요약·번안).

- 영문 한 문단: 피사체 → 행동 1개 → `Camera:` 이름 붙은 무빙 1개 → 장소·시간 → `Look:` 조명·색감·렌즈
- 릴스 구간별 카메라 사전(훅 Crash Zoom In, 정보 static·Overhead, 장소 Crane Down …), 막연한 말 금지표, "하지 말 것" 대신 원하는 모습 쓰기
- Higgsfield·Kling·Seedance·Wan·LTX 등 **어느 생성기에 붙여 넣어도** 쓰이게 썼습니다(이 프로젝트가 유료 생성기를 직접 호출하지는 않음)
- 프롬프트 파일에서 `{{include:visual_rules}}`로 불러오므로, 규칙은 이 파일만 고치면 API 모드·웹 LLM 요청 프롬프트·스킬에 같이 반영됩니다

## 이미지 생성 (agent/image_maker.py)

리포트의 이미지 프롬프트(`..._images.json`)로 실제 이미지를 만들어 `images\<리포트이름>\<이슈번호>_<용도>.jpg|png`에 저장하고,
리포트 맨 아래 `생성된 이미지` 섹션에 연결합니다. `IMAGE_PROVIDER=auto`면 아래 순서로 **되는 것**을 씁니다
(크레딧 부족·키 오류가 나면 다음 공급자로 자동 전환).

| 공급자 | 필요 | 비고 |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | `gpt-image-1-mini`, quality `low` (DALL-E 3는 2026-05-12 종료), 장당 유료 |
| `gemini` | `GEMINI_API_KEY` | `gemini-3.1-flash-image` (Nano Banana 2), 결제 크레딧 필요 |
| `pollinations` | 없음 (무료) | 약 30초에 1장 속도 제한(자동 대기), 익명은 워터마크·768px. `POLLINATIONS_TOKEN`(무료 가입)으로 워터마크 제거 |

- LLM 없이 만든 템플릿 프롬프트는 한글 제목이 들어 있어, 생성 전에 영문 장면 묘사로 자동 변환합니다(LLM → 안 되면 Pollinations 무료 텍스트 API).
- 이미지 안 글자는 넣지 않습니다. `얹을 문구`는 캔바·미리캔버스 등에서 올리세요.
- 무료 공급자를 쓰면 프롬프트가 외부 서비스로 전송되고, 생성물이 공개 피드에 노출될 수 있습니다.

## 매일 자동 실행 (GitHub Actions)

`.github/workflows/trend_bot.yml` — 매일 **한국시간 06:07**(GitHub 사정으로 1~3시간 밀릴 수 있어 일찍 잡음)에 GitHub 서버에서 리포트를 만들어 저장소의 **`reports` 브랜치**에
`reports/`, `images/`로 올립니다. PC가 꺼져 있어도 되고, GitHub 웹·앱에서 바로 읽을 수 있습니다(실행별 Artifact도 30일 보관).

1. 저장소 **Settings → Secrets and variables → Actions**
   - **Secrets**: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `YOUTUBE_API_KEY`, `OPENAI_API_KEY`, `POLLINATIONS_TOKEN` 중 있는 것
   - **Variables**: `TREND_KEYWORDS`(예: `가을 캠핑,러닝화` — 비우면 오늘의 트렌드), `GENERATION_MODE`(기본 `prompt` = LLM 비용 0), `MAKE_IMAGES`(`true`면 이미지까지), `LLM_PROVIDER`, `IMAGE_PROVIDER`
2. **Actions** 탭에서 워크플로 활성화 → `trend-bot` → **Run workflow**로 한 번 수동 실행해 확인
3. 결과: 저장소에서 브랜치를 `reports`로 바꿔 `reports/` 폴더 열기

- **이 저장소는 공개(public)라 `reports` 브랜치의 리포트·이미지도 누구나 볼 수 있습니다.** 공개가 곤란하면 저장소를 비공개로 바꾸세요(무료 계정은 Actions 월 2,000분 — 이 봇은 하루 5분 안팎).
- 예약 실행은 GitHub 사정으로 수십 분 늦을 수 있고, 공개 저장소는 60일간 커밋이 없으면 예약이 자동 중지됩니다(Actions 탭에서 다시 켜기).
- 실행 시간: 키워드 1개당 LLM 사용 시 수 분, 이미지 6장(무료) 약 4분.

## 이슈 점수 (analyzer.py)

`0.30 × 관련도 + 0.20 × 최신성(반감기 3일) + 0.20 × 인기도(플랫폼 내 log 정규화) + 0.10 × 플랫폼 다양성 + 0.20 × 바이럴`

바이럴(`_viral`, 0~1)은 퍼질 가능성: 유튜브는 시간당 조회수·좋아요+댓글 비율, 모든 소스는 제목의 훅 단어(반전·꿀팁·비교·TOP·금지·할인 등)·물음표·숫자. 가중치는 `analyzer.SCORE_WEIGHTS`.

제목이 비슷한 뉴스·영상·글은 하나의 이슈로 묶이므로, 여러 플랫폼에서 동시에 뜨는 주제가 위로 올라옵니다.
LLM이 있으면 이 후보 중에서 콘텐츠화하기 좋은 이슈와 관점, SEO 키워드, 해시태그, 주의사항을 다시 골라 줍니다.

## API 키

키가 없는 플랫폼은 건너뛰고, LLM 키가 없으면 템플릿으로 골격만 만듭니다. **구글 트렌드·구글 뉴스는 키 없이 동작**합니다.
공용 키는 중앙 `.env`에 `_setup\keys.bat set 이름`으로 넣습니다 (값은 화면에 안 나옴).

| 이름 | 용도 | 발급 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude (기본 `claude-opus-5-5`) | platform.claude.com |
| `GEMINI_API_KEY` | Gemini `gemini-3.8-flash` (Claude 키가 없을 때 자동 선택) + 이미지 | aistudio.google.com |
| `OPENAI_API_KEY` | (선택) 이미지 생성 gpt-image-1-mini | platform.openai.com |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 네이버 뉴스·블로그 검색 + 데이터랩 | developers.naver.com → 애플리케이션 등록, API에 '검색'·'데이터랩(검색어트렌드)' 추가 |
| `YOUTUBE_API_KEY` | 유튜브 검색·인기 동영상 | Google Cloud 콘솔 → YouTube Data API v3 사용 설정 → API 키 |
| `INSTAGRAM_ACCESS_TOKEN` / `INSTAGRAM_USER_ID` | 인스타 해시태그 상위 게시물 (선택) | Meta 개발자 앱 + 비즈니스/크리에이터 계정 |

LLM 선택·모델은 프로젝트 `.env`의 `LLM_PROVIDER`(auto/claude/gemini/none), `CLAUDE_MODEL`, `CLAUDE_EFFORT`, `GEMINI_MODEL` (`.env.example` 참고).
Claude 호출은 서버측 거절 폴백(`fallbacks="default"`)을 켜 둬서, 안전 분류기가 요청을 거절하면 다른 모델로 자동 재시도합니다.

## 한계와 다음 단계

- **인스타그램**은 공개 트렌드 API가 없어, 공식 Graph API(비즈니스 계정, 해시태그 7일 30개 제한)만 지원합니다. 로그인 스크레이핑은 약관 위반이라 넣지 않았습니다.
- **네이버 실시간 검색어**는 서비스가 종료돼 공개 데이터가 없습니다. 대신 데이터랩으로 키워드별 검색량 증감을 봅니다.
- 키워드 추출은 형태소 분석기 없이 조사만 떼는 방식이라 거칩니다. 정확도가 필요하면 `kiwipiepy`로 `analyzer.tokenize()`만 바꾸면 됩니다.
- 이후 후보: 네이버 쇼핑인사이트, 유튜브 댓글 분석, 같은 키워드 반복 실행 시 증감 비교, Streamlit 화면.
