from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from .analyze.runner import Analyzer
from .analyze.trends import TrendAnalyzer
from .collect.dcinside import BlockedError, DcInsideCollector
from .collect.jsonl import JsonlCollector
from .config import Config, load_config, resolve_api_key
from .llm.client import LlmClient
from .normalize import author_hash
from .report.render import render_report, save_report
from .store import Store

DEFAULT_KINDS = "topics,sentiment,entities,voices"


def _period(days: int) -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=days), today


def _make_llm(cfg: Config) -> LlmClient:
    return LlmClient(cfg.llm.base_url, cfg.llm.model, resolve_api_key(cfg),
                     temperature=cfg.llm.temperature, timeout=cfg.llm.timeout)


def _cmd_collect(args, cfg: Config) -> int:
    if args.pages <= 0:
        print("pages=0: nothing to collect")
        return 0
    cookies = os.environ.get(cfg.collect.cookies_env) or None
    collector = DcInsideCollector(args.gallery, cfg.collect, cookies=cookies,
                                  minor=getattr(args, "minor", False))
    collected = 0
    with Store(Path(args.db)) as store:
        try:
            for post in collector.collect(args.pages):
                post.author = author_hash(post.author, cfg.privacy_salt)
                store.upsert_post(post)
                store.replace_comments(post.gallery_id, post.post_no, post.comments)
                collected += 1
        except BlockedError as exc:
            print(f"차단 감지, 여기까지 저장({collected}건): {exc}", file=sys.stderr)
            return 2
    print(f"collected {collected} posts into {args.db}")
    return 0


def _cmd_ingest(args, cfg: Config) -> int:
    posts = JsonlCollector(Path(args.file)).read_posts()
    with Store(Path(args.db)) as store:
        for post in posts:
            post.author = author_hash(post.author, cfg.privacy_salt)
            store.upsert_post(post)
            store.replace_comments(post.gallery_id, post.post_no, post.comments)
    print(f"ingested {len(posts)} posts into {args.db}")
    return 0


def _analyze_period(store: Store, analyzer: Analyzer, trender: TrendAnalyzer | None,
                    gallery: str, start: date, end: date,
                    kinds: list[str], max_chars: int = 12000
                    ) -> tuple[dict[str, dict], dict]:
    run_id, results, coverage = analyzer.run(gallery, start, end, kinds,
                                             max_chars=max_chars)
    if run_id > 0:
        from .analyze.kinds import PROMPT_VERSION
        from .ontology.materialize import materialize
        materialize(store, gallery, run_id, PROMPT_VERSION, start, end, results)
    results = dict(results)
    if run_id > 0 and trender is not None and len(results) >= 2:
        prev_start, prev_end = start - (end - start), start - timedelta(days=1)
        prev = store.latest_analyses(gallery, prev_start, prev_end)
        if prev:
            results["trends"] = trender.diff(
                gallery, prev, {k: v for k, v in results.items() if k != "trends"},
                f"{prev_start}~{prev_end}", f"{start}~{end}")
    return results, coverage


def _cmd_analyze(args, cfg: Config, llm_factory=None) -> int:
    start, end = _period(args.days)
    with Store(Path(args.db)) as store:
        factory = llm_factory or _make_llm
        analyzer = Analyzer(store, factory(cfg))
        trender = TrendAnalyzer(factory(cfg))
        results, coverage = _analyze_period(store, analyzer, trender, args.gallery,
                                            start, end, args.kinds.split(","),
                                            max_chars=cfg.llm.max_chunk_chars)
        total, failed = coverage.get("chunks_total", 0), coverage.get("chunks_failed", 0)
        if total and failed == total:
            print("오류: 모든 LLM 청크가 실패했습니다 — llm_calls 로그를 확인하세요 "
                  "(API 키/엔드포인트 점검).", file=sys.stderr)
            return 1
        if failed:
            print(f"경고: 청크 {failed}/{total} 실패 — 결과가 부분적입니다.", file=sys.stderr)
        print(f"analyzed {len(results)} kinds: {', '.join(results)}")
    return 0


def _cmd_report(args, cfg: Config, llm_factory=None) -> int:
    start, end = _period(args.days)
    with Store(Path(args.db)) as store:
        analyses = store.latest_analyses(args.gallery, start, end)
        if not analyses:
            print("분석 결과가 없습니다. 먼저 `dch analyze`를 실행하세요.", file=sys.stderr)
            return 1
        top = store.top_posts(args.gallery, start, end)
        md, payload = render_report(args.gallery, start, end, analyses, top, {})
        out = save_report(Path(args.out), args.gallery, start, end, md, payload)
    print(f"report saved: {out}")
    return 0


def _cmd_run(args, cfg: Config, llm_factory=None) -> int:
    if getattr(args, "file", None):
        _cmd_ingest(args, cfg)
    elif args.pages > 0:
        rc = _cmd_collect(args, cfg)
        if rc != 0:
            return rc
    return _cmd_analyze(args, cfg, llm_factory) or _cmd_report(args, cfg, llm_factory)


def _cmd_query(args, cfg: Config) -> int:
    from .ontology.defn import load_ontology
    from .ontology.query import print_rows, query_objects
    start, end = _period(args.days)
    with Store(Path(args.db)) as store:
        rows = query_objects(store, load_ontology(None), args.object,
                             args.gallery, start, end, args.limit)
    print(print_rows(rows))
    return 0


def _cmd_show(args, cfg: Config) -> int:
    from .ontology.query import show_post
    with Store(Path(args.db)) as store:
        detail = show_post(store, args.gallery, args.post)
    post = detail["post"]
    print(f"#{post.post_no} {post.title} (추천 {post.recommend})")
    print(f"토픽: {', '.join(detail['topics']) or '(없음)'}")
    for c in post.comments[:10]:
        print(f"  - (추천{c.recommend}) {c.text}")
    return 0


def _cmd_ask(args, cfg: Config, llm_factory=None) -> int:
    from .ontology.ask import ask
    from .ontology.defn import load_ontology
    with Store(Path(args.db)) as store:
        llm = (llm_factory or _make_llm)(cfg)
        print(ask(store, load_ontology(None), llm, args.gallery, args.question))
    return 0


def _cmd_ontology(args, cfg: Config) -> int:
    import dataclasses
    import json as _json

    from .ontology.ask import ontology_summary
    from .ontology.defn import load_ontology
    defn = load_ontology(None)
    if args.json:
        print(_json.dumps(dataclasses.asdict(defn), ensure_ascii=False, indent=2))
    else:
        print(ontology_summary(defn))
    return 0


def _cmd_web(args, cfg: Config) -> int:
    from .web import run_server
    run_server(Path(args.db), port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dch", description="DC Inside gallery opinion research harness")
    parser.add_argument("--config", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="DC Inside 갤러리 수집")
    p_collect.add_argument("--gallery", required=True)
    p_collect.add_argument("--pages", type=int, default=3)
    p_collect.add_argument("--minor", action="store_true",
                           help="마이너 갤러리(/mgallery/) 경로 사용")
    p_collect.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_collect.set_defaults(func=_cmd_collect)

    p_ingest = sub.add_parser("ingest", help="JSONL 파일 적재")
    p_ingest.add_argument("--gallery", required=True)
    p_ingest.add_argument("--file", type=Path, required=True)
    p_ingest.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_ingest.set_defaults(func=_cmd_ingest)

    def add_analyze_common(p):
        p.add_argument("--gallery", required=True)
        p.add_argument("--days", type=int, default=7)
        p.add_argument("--db", type=Path, default=Path("data/dch.db"))

    p_analyze = sub.add_parser("analyze", help="LLM 분석 실행")
    add_analyze_common(p_analyze)
    p_analyze.add_argument("--kinds", default=DEFAULT_KINDS)
    p_analyze.set_defaults(func=_cmd_analyze)

    p_report = sub.add_parser("report", help="리포트 생성")
    add_analyze_common(p_report)
    p_report.add_argument("--out", type=Path, default=Path("reports"))
    p_report.set_defaults(func=_cmd_report)

    p_run = sub.add_parser("run", help="수집→분석→리포트 전체 파이프라인")
    add_analyze_common(p_run)
    p_run.add_argument("--pages", type=int, default=3)
    p_run.add_argument("--minor", action="store_true",
                       help="마이너 갤러리(/mgallery/) 경로 사용")
    p_run.add_argument("--file", type=Path, default=None,
                       help="지정하면 수집 대신 JSONL 파일을 적재")
    p_run.add_argument("--kinds", default=DEFAULT_KINDS)
    p_run.add_argument("--out", type=Path, default=Path("reports"))
    p_run.set_defaults(func=_cmd_run)

    p_query = sub.add_parser("query", help="온톨로지 객체 질의 (결정적, LLM 없음)")
    p_query.add_argument("--object", required=True)
    p_query.add_argument("--gallery", required=True)
    p_query.add_argument("--days", type=int, default=7)
    p_query.add_argument("--limit", type=int, default=20)
    p_query.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_query.set_defaults(func=_cmd_query)

    p_show = sub.add_parser("show", help="게시글 상세 + 연결된 토픽")
    p_show.add_argument("--gallery", required=True)
    p_show.add_argument("--post", type=int, required=True)
    p_show.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_show.set_defaults(func=_cmd_show)

    p_ask = sub.add_parser("ask", help="온톨로지 도구 기반 질의 (LLM, 읽기 전용)")
    p_ask.add_argument("--gallery", required=True)
    p_ask.add_argument("question")
    p_ask.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_ask.set_defaults(func=_cmd_ask)

    p_onto = sub.add_parser("ontology", help="온톨로지 정의 인쇄 (객체·링크)")
    p_onto.add_argument("--json", action="store_true")
    p_onto.set_defaults(func=_cmd_ontology)

    p_web = sub.add_parser("web", help="로컬 웹 뷰어 가동 (127.0.0.1 전용)")
    p_web.add_argument("--port", type=int, default=8765)
    p_web.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_web.set_defaults(func=_cmd_web)
    return parser


def main(argv: list[str] | None = None, *,
         llm_factory: Callable[[Config], LlmClient] | None = None) -> int:
    # 배경 실행 환경(LANG 미설정)에서 ascii 스트림이 한국어 출력/로그를 죽이지 않게 강제
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    func = args.func
    import inspect
    if "llm_factory" in inspect.signature(func).parameters:
        return func(args, cfg, llm_factory=llm_factory)
    return func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
