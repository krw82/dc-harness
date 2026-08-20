from __future__ import annotations

import json
from datetime import date

from ..llm.chunker import chunk_posts, render_post_text
from ..llm.client import LlmClient
from ..store import Store
from .kinds import KINDS, PROMPT_VERSION, AnalysisKind, merge_chunk_results


class Analyzer:
    def __init__(self, store: Store, llm: LlmClient, progress=None):
        """progress: 선택적 콜백(str) — 웹 관제판 등에서 진행 메시지 수신."""
        self.store, self.llm = store, llm
        self._progress = progress or (lambda msg: None)

    def _map(self, kind: AnalysisKind, run_id: int, chunks) -> tuple[list[dict], int]:
        results: list[dict] = []
        failed = 0
        for idx, chunk in enumerate(chunks, 1):
            self._progress(f"[{kind.name}] 청크 {idx}/{len(chunks)} 요청…")
            corpus = "\n\n".join(render_post_text(p) for p in chunk)
            user = (f"{kind.instruction}\n\n출력 스키마(JSON):\n{kind.schema_hint}\n\n"
                    f"=== 데이터 ===\n{corpus}")
            result = None
            for attempt in range(2):  # 타임아웃 등 일시 실패 1회 재시도 (실측: 서버 혼잡 잦음)
                try:
                    result = self.llm.chat_json(kind.system, user)
                    self.store.log_llm_call(  # I5: 모든 호출 감사
                        run_id, kind.name, kind.system, user,
                        json.dumps(result, ensure_ascii=False),
                        getattr(self.llm, "model", "unknown"), PROMPT_VERSION)
                    break
                except Exception as exc:
                    self.store.log_llm_call(  # 실패한 호출도 감사 대상
                        run_id, kind.name, kind.system, user,
                        f"(failed attempt {attempt + 1}) {type(exc).__name__}: {exc}",
                        getattr(self.llm, "model", "unknown"), PROMPT_VERSION)
            if result is None:
                failed += 1
                self._progress(f"[{kind.name}] 청크 {idx}/{len(chunks)} 실패(재시도 소진)")
            else:
                results.append(result)
                self._progress(f"[{kind.name}] 청크 {idx}/{len(chunks)} 완료")
        return results, failed

    def run(self, gallery_id: str, start: date, end: date, kinds: list[str],
            max_chars: int = 12000) -> tuple[int, dict[str, dict], dict]:
        posts = self.store.fetch_posts(gallery_id, start, end)
        if not posts:
            return -1, {}, {"chunks_total": 0, "chunks_failed": 0,
                            "posts_included": 0, "posts_total": 0}
        chunks = chunk_posts(posts, max_chars=max_chars)
        run_id = self.store.start_run(gallery_id)
        self._progress(f"분석 대상 {len(posts)}건 → 청크 {len(chunks)}개 × 종류 {len(kinds)}개")
        results: dict[str, dict] = {}
        total_failed = 0
        for name in kinds:
            kind = KINDS[name]
            chunk_results, failed = self._map(kind, run_id, chunks)
            total_failed += failed
            results[name] = merge_chunk_results(name, chunk_results)
            self.store.save_analysis(run_id, name, gallery_id, start, end, results[name])
        coverage = {
            "chunks_total": len(chunks) * len(kinds),
            "chunks_failed": total_failed,
            "posts_included": len(posts),
            "posts_total": len(self.store.fetch_posts(gallery_id)),
        }
        self.store.finish_run(run_id, "done", coverage)
        return run_id, results, coverage
