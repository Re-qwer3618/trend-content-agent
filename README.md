# trend-content-agent

네이버·유튜브·구글·인스타그램의 최신 트렌드를 모으고 분석해서 **네이버 블로그 포스팅 기획서**와 **인스타그램 릴스 기획서**를 마크다운 리포트로 만들어 주는 CLI입니다.

## 실행

```bat
run.bat "가을 캠핑"                     :: 키워드 리서치 + 블로그·릴스 기획서
run.bat                                 :: 키워드 입력 프롬프트 (엔터 = 오늘의 트렌드)
run.bat --today                         :: 오늘의 급상승 트렌드에서 주제 선정
run.bat "러닝화" --formats blog --llm gemini --limit 30
run.bat "러닝화" --sources google_news youtube
run.bat --check                         :: 키·수집기·LLM 상태 확인
```

결과는 `reports\YYYYMMDD_HHMM_키워드.md`, 수집 원본 JSON은 `data\raw\`에 저장됩니다.

## 파이프라인

```
main.py (CLI)
  └─ collectors.collect_all()   플랫폼별 병렬 수집 → TrendItem 공통 형식
  └─ analyzer.analyze()         이슈 묶기·점수, 연관 키워드, 네이버 데이터랩 검색량, (LLM) 인사이트
  └─ generator.generate()       블로그 / 릴스 기획서 (LLM, 없으면 템플릿 골격)
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
│  ├─ generator.py          기획서 생성 + LLM 없을 때 템플릿
│  ├─ report.py             마크다운 리포트·원본 JSON 저장
│  └─ prompts/              system.md, blog.md, reels.md  ← 기획서 형식은 여기서 수정
├─ reports/                 생성된 리포트 (git 제외)
└─ data/raw/                수집 원본 (git 제외)
```

## 이슈 점수 (analyzer.py)

`0.35 × 관련도 + 0.25 × 최신성(반감기 3일) + 0.25 × 인기도(플랫폼 내 log 정규화) + 0.15 × 플랫폼 다양성`

제목이 비슷한 뉴스·영상·글은 하나의 이슈로 묶이므로, 여러 플랫폼에서 동시에 뜨는 주제가 위로 올라옵니다.
LLM이 있으면 이 후보 중에서 콘텐츠화하기 좋은 이슈와 관점, SEO 키워드, 해시태그, 주의사항을 다시 골라 줍니다.

## API 키

키가 없는 플랫폼은 건너뛰고, LLM 키가 없으면 템플릿으로 골격만 만듭니다. **구글 트렌드·구글 뉴스는 키 없이 동작**합니다.
공용 키는 중앙 `.env`에 `_setup\keys.bat set 이름`으로 넣습니다 (값은 화면에 안 나옴).

| 이름 | 용도 | 발급 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude (기본 `claude-opus-5-5`) | platform.claude.com |
| `GEMINI_API_KEY` | Gemini (Claude 키가 없을 때 자동 선택) | aistudio.google.com |
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
