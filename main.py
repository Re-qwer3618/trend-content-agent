"""트렌드 리서치 → 콘텐츠 기획 에이전트 CLI.

    run.bat "제주 가을 여행"                 키워드 리서치 + 블로그·릴스 기획서
    run.bat                                  키워드 입력 프롬프트 (엔터만 치면 오늘의 트렌드 모드)
    run.bat --today                          오늘의 급상승 트렌드에서 주제를 골라 기획
    run.bat "러닝화" --formats blog --llm gemini
    run.bat --check                          API 키·수집기 상태 확인
"""
from __future__ import annotations

import argparse
import sys

from agent.analyzer import analyze
from agent.collectors import COLLECTORS, collect_all
from agent.config import load_settings
from agent.generator import FORMATS, generate
from agent.llm import LLMError, get_llm
from agent.report import SOURCE_LABEL, save_raw, save_report


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="트렌드 수집 → 분석 → 네이버 블로그/인스타 릴스 기획서 생성")
    p.add_argument("keyword", nargs="*", help="주제 또는 키워드 (여러 단어 가능)")
    p.add_argument("--today", action="store_true", help="키워드 없이 오늘의 트렌드 모드")
    p.add_argument("--sources", nargs="+", choices=list(COLLECTORS), help="사용할 수집기 (기본: 전부)")
    p.add_argument("--formats", nargs="+", choices=list(FORMATS), default=list(FORMATS), help="생성할 기획서")
    p.add_argument("--llm", choices=["auto", "claude", "gemini", "none"], help="LLM 선택 (기본: .env의 LLM_PROVIDER)")
    p.add_argument("--limit", type=int, default=20, help="플랫폼당 수집 개수 (기본 20)")
    p.add_argument("--top", type=int, default=7, help="핵심 이슈 개수 (기본 7)")
    p.add_argument("--no-raw", action="store_true", help="수집 원본 JSON을 저장하지 않음")
    p.add_argument("--check", action="store_true", help="키·수집기 상태만 출력")
    return p.parse_args(argv)


def check(settings) -> None:
    print("API 키 (값은 표시하지 않음)")
    for name, ok in settings.key_status().items():
        print(f"  {'O' if ok else '-'} {name}")
    print("\n수집기")
    for name, cls in COLLECTORS.items():
        ok, reason = cls(settings).available()
        print(f"  {'O' if ok else '-'} {SOURCE_LABEL.get(name, name):<14} {reason}")
    try:
        llm = get_llm(settings)
        print(f"\nLLM: {llm.label if llm else '없음 (템플릿 모드)'}")
    except LLMError as e:
        print(f"\nLLM: 설정 오류 — {e}")
    print(f"리포트 폴더: {settings.report_dir}")


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = load_settings()
    if args.check:
        check(settings)
        return 0

    keyword = " ".join(args.keyword).strip() or None
    if not keyword and not args.today and sys.stdin.isatty():
        keyword = input("주제/키워드 입력 (엔터 = 오늘의 트렌드): ").strip() or None

    try:
        llm = get_llm(settings, args.llm)
    except LLMError as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 2

    print(f"▶ 수집: {keyword or '오늘의 트렌드'}")
    results = collect_all(settings, keyword, args.sources, args.limit)
    for r in results:
        state = f"{len(r.items)}건" if not (r.skipped or r.error) else (f"건너뜀 ({r.skipped})" if r.skipped else f"실패 ({r.error})")
        print(f"  - {SOURCE_LABEL.get(r.source, r.source)}: {state}")
    if not any(r.items for r in results):
        print("[오류] 수집된 데이터가 없습니다. --check 로 키·네트워크를 확인하세요.", file=sys.stderr)
        return 1

    print(f"▶ 분석 ({llm.label if llm else '규칙 기반'})")
    analysis = analyze(results, keyword, settings, llm, top_issues=args.top)
    for i, iss in enumerate(analysis.issues[:5]):
        print(f"  [{i}] {iss.score:5.1f}  {iss.title[:60]}")
    print(f"  연관 키워드: {', '.join(k.word for k in analysis.keywords[:10])}")

    plans = []
    for fmt in args.formats:
        print(f"▶ 생성: {FORMATS[fmt]}")
        plans.append(generate(analysis, fmt, llm))

    for note in analysis.notes:
        print(f"  ! {note}")
    if not args.no_raw:
        save_raw(analysis, settings.data_dir)
    path = save_report(analysis, plans, settings.report_dir)
    print(f"\n✔ 리포트 저장: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
