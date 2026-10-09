# trend-content-agent

워크스페이스 공통 규칙 `..\..\CLAUDE.md`(집 PC `E:\dev`, 회사 PC `D:\dev`)를 상속합니다. 기능·구조·키 설명은 `README.md`가 기준입니다.

## 실행 환경

- `run.bat`은 프로젝트 `.venv`를 먼저 찾고, 없으면 conda `agent-py313`(3.13)으로 내려갑니다. 직접 돌릴 땐 `run.bat ...`.
- 회사 PC(`D:\dev`)는 `.venv` 없이 `agent-py313`을 씁니다(워크스페이스 규칙). 패키지는 `requirements.txt` → `_setup\setup-dev-env.bat`.
- `.venv`를 쓰는 PC라면: `uv venv --python <agent-py313의 python.exe> .venv` → `uv pip install --python .venv\Scripts\python.exe -r requirements.txt`
  (uv로 파이썬을 따로 받지 않음).
- 키 없이도 구글 트렌드·구글 뉴스만으로 끝까지 돕니다(`run.bat "키워드"`). 동작 확인은 `run.bat --check`.

## 규칙

- 기본 `GENERATION_MODE=prompt`는 LLM API 비용 0입니다. `--mode api`/`auto`는 유료 호출이니 사용자가 요청할 때만 돌리세요.
- `reports/`, `images/`, `data/`는 git 제외 대상입니다. GitHub Actions(`trend_bot.yml`)가 결과를 `reports` 브랜치로 올리고,
  **저장소가 public이라 그 리포트도 공개**됩니다.
- 네이버 키는 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`(개발자센터 앱). 401 응답의 메시지로 원인을 가릅니다:
  `NID AUTH Result Invalid` = 키 값이 틀림, `Scope Status Invalid` = 키는 맞고 앱의 사용 API에 검색/데이터랩이 빠짐.
- 이미지 프롬프트 영문 변환은 LLM → Pollinations 텍스트 API(2026-10 기준 장애·폐지 예정) → MyMemory 제목 번역 순으로 폴백합니다.
- 노션 발행은 코드가 아니라 **Claude 예약 작업**(데스크톱 앱, Claude의 노션 연결 사용)이 합니다. PC와 앱이 켜져 있어야 돕니다.
  - 아침: `run.bat --today --list` → `Trend-Reports` 아래 "YYYY-MM-DD · 오늘의 이슈 TOP 10" 페이지. 이슈마다 체크박스 하나.
  - 정해진 시각: 오늘·어제 목록 페이지에서 체크됐는데 아직 "→ ✅ 상세 리포트"가 없는 항목을 `run.bat --pick N --from <그날 목록>`으로
    상세 작성해 목록 페이지의 하위 페이지로 올리고, 목록 항목 끝에 링크를 단다.
  - 목록 페이지 맨 아래에 그날 목록 파일 이름(`reports/..._issues.json`)을 적어 둔다 — 며칠 뒤 체크해도 같은 순위로 작성되게.
  - 개인 건강·사생활·진행 중인 논란 이슈는 목록에 🔴 표시하고, 체크돼도 예약 작업은 작성하지 않고 "보류 — 대화에서 요청" 표시만 한다.
- Claude가 직접 쓰는 글(노션 상세 리포트, "N번 작성해줘")의 문체·구조는 스킬 `.claude/skills/trend-content-style/`이 기준.
  원천은 사용자의 노션 작성 팁 페이지 2개(스킬 SKILL.md에 링크). 팁이 바뀌면 "스타일 업데이트"로 다시 반영.
  같은 규칙이 `agent/prompts/*.md`(웹 LLM 요청 프롬프트·API 모드)에도 들어 있으니 둘을 같이 고친다. `channels.md`는 피드+유튜브용이며 요청 프롬프트로만 쓴다.
- 카드뉴스 PNG는 cardnews-kit 스킬(`.claude/skills/cardnews-*`, git 제외·PC마다 설치)이 굽는다. 카드 문구 JSON 규칙은 `agent/prompts/cards.md` 하나를
  요청 프롬프트(`channels.md`의 include)·API 모드·스킬이 같이 쓴다. Windows에서 한글 경로면 렌더러가 죽어서 영문 임시 폴더에서 굽는다.
- 작성 지침(`agent/prompts/*.md`)은 API 모드와 프롬프트 모드가 같이 씁니다 — 한쪽만 고치는 지침은 없습니다.
