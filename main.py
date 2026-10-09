"""트렌드 리서치 → 콘텐츠 기획 에이전트 CLI.

    run.bat "제주 가을 여행"                 키워드 리서치 + 기획서 + 웹 LLM용 제작 요청 프롬프트 (API 비용 0)
    run.bat "제주 가을 여행" --mode api      LLM API로 원고·대본까지 직접 생성 (유료)
    run.bat                                  키워드 입력 프롬프트 (엔터만 치면 오늘의 트렌드 모드)
    run.bat --today                          오늘의 급상승 트렌드에서 주제를 골라 기획
    run.bat "러닝화" --formats blog --llm gemini
    run.bat "러닝화" --no-draft --no-web        기획서만 (빠르고 저렴)
    run.bat "러닝화" --make-images               리포트 + 썸네일 이미지 생성 (images/)
    run.bat --images-from reports\20261002_0019_가을_캠핑.md   기존 리포트로 이미지만
    run.bat "가을 캠핑" --make-video            리포트 + 이미지 + 쇼츠 영상(mp4, 나레이션·자막) — 전부 무료
    run.bat --video-from reports\…_가을_캠핑.md --script 대본.txt   웹 LLM이 쓴 대본으로 영상 다시 만들기
    run.bat --check                          API 키·수집기 상태 확인
    run.bat --today --list                   이슈 TOP 10 목록만 (기획서 없음)
    run.bat --pick 2 5                       최근 목록의 2·5위를 상세 작성
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent.analyzer import analyze
from agent.collectors import COLLECTORS, collect_all
from agent.config import load_settings
from agent.generator import FORMATS, generate
from agent.image_maker import ImageError, run_for_report
from agent.images import generate_image_prompts
from agent.issue_list import load_issue_list, save_issue_list
from agent.llm import LLMError, get_llm
from agent.prompt_pack import build_request_prompts
from agent.shorts_maker import (SCRIPT_HEADER, ShortsError, make_shorts, parse_script, scenes_from_analysis,
                                scenes_to_text)
from agent.report import SOURCE_LABEL, save_raw, save_report


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="트렌드 수집 → 분석 → 네이버 블로그/인스타 릴스 기획서 생성")
    p.add_argument("keyword", nargs="*", help="주제 또는 키워드 (여러 단어 가능)")
    p.add_argument("--today", action="store_true", help="키워드 없이 오늘의 트렌드 모드")
    p.add_argument("--sources", nargs="+", choices=list(COLLECTORS), help="사용할 수집기 (기본: 전부)")
    p.add_argument("--formats", nargs="+", choices=list(FORMATS), default=list(FORMATS), help="생성할 기획서")
    p.add_argument("--mode", choices=["prompt", "api", "auto"],
                   help="prompt: API 호출 없이 웹 LLM용 제작 요청 프롬프트 작성 / api: API로 직접 생성 / "
                        "auto: API 시도 후 실패분만 프롬프트 (기본: .env의 GENERATION_MODE, prompt)")
    p.add_argument("--llm", choices=["auto", "claude", "gemini", "none"], help="LLM 선택 (기본: .env의 LLM_PROVIDER)")
    p.add_argument("--limit", type=int, default=20, help="플랫폼당 수집 개수 (기본 20)")
    p.add_argument("--top", type=int, default=7, help="핵심 이슈 개수 (기본 7)")
    p.add_argument("--no-draft", action="store_true", help="기획서만 만들고 본문 원고·촬영 대본은 생략 (LLM 호출 절반)")
    p.add_argument("--no-web", action="store_true", help="원고 작성 때 웹 검색으로 원문을 확인하지 않음")
    p.add_argument("--no-images", action="store_true", help="이미지 생성 프롬프트를 만들지 않음")
    p.add_argument("--image-issues", type=int, default=3, help="이미지 프롬프트를 만들 상위 이슈 수 (기본 3)")
    p.add_argument("--make-images", action="store_true", help="리포트 생성 후 프롬프트로 실제 이미지까지 생성 (images/)")
    p.add_argument("--images-from", metavar="REPORT", help="기존 리포트(.md 또는 _images.json)로 이미지만 생성")
    p.add_argument("--image-provider", choices=["auto", "openai", "gemini", "pollinations"],
                   help="이미지 공급자 (기본: .env의 IMAGE_PROVIDER, auto)")
    p.add_argument("--make-video", action="store_true",
                   help="쇼츠 영상(mp4)까지 생성 — 이미지가 없으면 먼저 만든다 (videos/)")
    p.add_argument("--video-from", metavar="REPORT", help="기존 리포트의 쇼츠 대본(…_쇼츠대본.txt)으로 영상만 다시 생성")
    p.add_argument("--script", metavar="FILE", help="--video-from 과 함께: 웹 LLM이 쓴 대본 파일을 대신 사용")
    p.add_argument("--voice", choices=["female", "male", "multi"], help="나레이션 음성 (기본 female)")
    p.add_argument("--list", action="store_true",
                   help="기획서 없이 이슈 TOP N(기본 10) 목록만 저장 (reports/..._issues.md/.json)")
    p.add_argument("--pick", nargs="+", type=int, metavar="N",
                   help="이슈 목록에서 고른 순위의 이슈를 상세 작성 (그 이슈의 검색어로 키워드 모드 실행)")
    p.add_argument("--from", dest="list_from", metavar="LIST",
                   help="--pick에 쓸 이슈 목록 파일 (기본: 가장 최근 *_issues.json)")
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
    print(f"\n생성 모드: {settings.generation_mode}"
          + ("  (LLM API 호출 없음 — 웹 LLM용 제작 요청 프롬프트 작성)" if settings.generation_mode == "prompt" else ""))
    try:
        llm = get_llm(settings)
        print(f"LLM: {llm.label if llm else '없음 (템플릿 모드)'}")
    except LLMError as e:
        print(f"LLM: 설정 오류 — {e}")
    print(f"리포트 폴더: {settings.report_dir}")


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = load_settings()
    if args.mode:
        settings.generation_mode = args.mode
    mode = settings.generation_mode
    if mode not in ("prompt", "api", "auto"):
        print(f"[오류] 알 수 없는 GENERATION_MODE: {mode} (prompt / api / auto)", file=sys.stderr)
        return 2
    if args.check:
        check(settings)
        return 0
    if args.voice:
        os.environ["SHORTS_VOICE"] = args.voice
    if args.images_from:
        return make_images_for(Path(args.images_from), settings, args.image_provider)
    if args.video_from:
        return make_video_for(Path(args.video_from), settings, Path(args.script) if args.script else None)
    if args.pick:
        return pick_issues(args, settings)

    keyword = " ".join(args.keyword).strip() or None
    if not keyword and not args.today and sys.stdin.isatty():
        keyword = input("주제/키워드 입력 (엔터 = 오늘의 트렌드): ").strip() or None
    return run(args, settings, keyword)


def pick_issues(args, settings) -> int:
    try:
        src, entries = load_issue_list(settings.report_dir, args.list_from)
    except (OSError, ValueError, KeyError) as e:
        print(f"[오류] 이슈 목록을 읽지 못함: {e}", file=sys.stderr)
        return 2
    by_rank = {e["rank"]: e for e in entries}
    missing = [n for n in args.pick if n not in by_rank]
    if missing:
        print(f"[오류] 목록({src.name})에 없는 순위: {missing} (1~{len(entries)})", file=sys.stderr)
        return 2
    code = 0
    for n in args.pick:
        e = by_rank[n]
        print(f"\n━━ {n}위 {e['title']}  →  검색어 '{e['query']}'")
        code = max(code, run(args, settings, e["query"]))
    return code


def run(args, settings, keyword: str | None) -> int:
    mode = settings.generation_mode
    llm = None
    if args.list:
        pass  # 목록만 만들 때는 LLM을 쓰지 않는다
    elif mode == "prompt":
        print("ℹ 프롬프트 모드: LLM API를 호출하지 않고, 웹 LLM에 붙여 넣을 제작 요청 프롬프트를 만듭니다.")
    else:
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
    analysis = analyze(results, keyword, settings, llm, top_issues=max(args.top, 10) if args.list else args.top)
    if args.list:
        if not args.no_raw:
            save_raw(analysis, settings.data_dir)
        path = save_issue_list(analysis, settings.report_dir, top=max(args.top, 10))
        for i, iss in enumerate(analysis.issues[:10], start=1):
            print(f"  {i:2}. {iss.score:5.1f}  {iss.title[:60]}")
        print(f"\n✔ 이슈 목록 저장: {path}\n  상세 작성: run.bat --pick 번호 [번호 ...]")
        return 0
    for i, iss in enumerate(analysis.issues[:5]):
        print(f"  [{i}] {iss.score:5.1f}  {iss.title[:60]}")
    print(f"  연관 키워드: {', '.join(k.word for k in analysis.keywords[:10])}")

    plans = []
    for fmt in args.formats:
        print(f"▶ 생성: {FORMATS[fmt]}")
        plans.append(generate(analysis, fmt, llm, draft=not args.no_draft, web_search=not args.no_web))

    images, images_by = [], ""
    if not args.no_images:
        print("▶ 생성: 이미지 프롬프트")
        images, images_by = generate_image_prompts(analysis, llm, max_issues=args.image_issues)

    # 완성본이 API로 만들어지지 않은 포맷은 웹 LLM용 제작 요청 프롬프트로 대신한다 (api 모드는 제외)
    requests = []
    if mode != "api":
        todo = [p.format for p in plans if not p.draft]
        need_images = bool(images) and not (llm and images_by == llm.label)
        if todo or need_images:
            print("▶ 생성: LLM 제작 요청 프롬프트")
            requests = build_request_prompts(analysis, todo, args.image_issues, include_images=need_images)

    for note in analysis.notes:
        print(f"  ! {note}")
    if not args.no_raw:
        save_raw(analysis, settings.data_dir)
    path = save_report(analysis, plans, settings.report_dir, images, images_by, requests)
    print(f"\n✔ 리포트 저장: {path}")
    for p in plans:
        if p.draft:
            print(f"  └ {p.title} 완성본도 같은 폴더에 따로 저장")
    for r in requests:
        print(f"  └ 제작 요청 프롬프트: {path.stem}_요청_{r.key}.txt")

    # 쇼츠 대본: API가 쓴 촬영 대본이 있으면 그것을, 없으면 상위 이슈로 만든 나레이션을 저장 (고쳐서 다시 렌더링 가능)
    reels = next((p for p in plans if p.format == "reels" and p.draft), None)
    scenes = parse_script(reels.draft) if reels else []
    if not scenes and analysis.issues:
        scenes = scenes_from_analysis(analysis)
    if scenes:
        shorts_script_path(path).write_text(scenes_to_text(scenes, SCRIPT_HEADER), encoding="utf-8")
        print(f"  └ 쇼츠 대본: {shorts_script_path(path).name}")

    if (args.make_images or args.make_video) and images:
        rc = make_images_for(path, settings, args.image_provider)
        if rc and not args.make_video:
            return rc
    if args.make_video and scenes:
        return make_video_for(path, settings)
    return 0


def shorts_script_path(report: Path) -> Path:
    return report.with_name(f"{report.stem}_쇼츠대본.txt")


def make_video_for(report: Path, settings, script: Path | None = None) -> int:
    report = report.resolve()
    script = script or shorts_script_path(report)
    if not script.exists():
        print(f"[오류] 대본 파일이 없습니다: {script}", file=sys.stderr)
        return 1
    scenes = parse_script(script.read_text(encoding="utf-8"))
    if not scenes:
        print(f"[오류] 대본에서 '[컷 N] … 나레이션:' 블록을 찾지 못했습니다: {script.name}", file=sys.stderr)
        return 1
    print(f"▶ 쇼츠 영상 생성: 장면 {len(scenes)}개 ({script.name})")
    try:
        r = make_shorts(settings, report, scenes)
    except (ShortsError, OSError) as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    print(f"✔ 쇼츠 저장: {r.video}  ({r.duration:.1f}초, 자막 {r.srt.name})")
    for s in r.sources:
        print(f"  · {s}")
    return 0


def make_images_for(report: Path, settings, provider: str | None) -> int:
    try:
        made = run_for_report(report, settings, provider)
    except (ImageError, OSError) as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    ok = sum(1 for m in made if m.path)
    print(f"✔ 이미지 {ok}/{len(made)}장 저장" + (" — 리포트 하단에 연결됨" if ok else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
