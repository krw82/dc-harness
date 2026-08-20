"""웹 관제판용 백그라운드 작업 — 측정(수집→분석→리포트) 실행, 온톨로지 질문, 진행 이벤트.

작업 스레드는 Store을 새로 연다(sqlite 연결은 스레드 간 공유 금지).
자격증명은 환경변수로만 읽는다(cli._make_llm 재사용 — I7).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .analyze.kinds import PROMPT_VERSION
from .analyze.runner import Analyzer
from .collect.dcinside import BlockedError, DcInsideCollector
from .config import Config
from .normalize import author_hash
from .store import Store

Emit = Callable[..., None]

_KINDS = ["topics", "sentiment", "entities", "voices"]  # krw-ontology-dc run 기본값과 동일


class JobBusyError(RuntimeError):
    """이미 실행 중인 작업이 있을 때 새 작업 시작 거부."""


@dataclass
class JobState:
    job_id: int
    kind: str          # "run" | "ask"
    gallery: str
    status: str = "running"   # running | done | error
    phase: str = "준비"
    detail: str = ""
    events: list[tuple[float, str]] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    finished: float | None = None
    result: str = ""
    error: str = ""


class JobManager:
    """1인용 로컬 관제판 — 동시 실행 작업 1개로 제한."""

    def __init__(self, max_events: int = 200):
        self._lock = threading.Lock()
        self._jobs: dict[int, JobState] = {}
        self._next = 0
        self._max_events = max_events

    def start(self, kind: str, gallery: str, fn: Callable[[Emit], str]) -> int:
        with self._lock:
            if any(j.status == "running" for j in self._jobs.values()):
                raise JobBusyError("이미 실행 중인 작업이 있습니다 — 끝난 뒤 시도하세요")
            self._next += 1
            job = JobState(self._next, kind, gallery)
            self._jobs[job.job_id] = job
            job_id = job.job_id

        def emit(event: str = "msg", value: str = "", **kv) -> None:
            with self._lock:
                if event == "phase":
                    job.phase = value
                elif event == "detail":
                    job.detail = value
                else:
                    stamp = time.strftime("%H:%M:%S")
                    job.events.append((time.time(), f"{stamp}  {value}"))
                    del job.events[:-self._max_events]

        def worker() -> None:
            try:
                job.result = fn(emit) or ""
                job.status, job.phase = "done", "완료"
            except Exception as exc:  # 관제판 표시용 — 작업 스레드에서 잡아 상태로 보관
                job.status, job.phase = "error", "오류"
                job.error = f"{type(exc).__name__}: {exc}"
                stamp = time.strftime("%H:%M:%S")
                job.events.append((time.time(), f"{stamp}  ✗ {job.error}"))
            finally:
                job.finished = time.time()

        threading.Thread(target=worker, daemon=True, name=f"dch-job-{job_id}").start()
        return job_id

    def snapshot(self, job: JobState) -> dict:
        return {
            "job_id": job.job_id, "kind": job.kind, "gallery": job.gallery,
            "status": job.status, "phase": job.phase, "detail": job.detail,
            "elapsed": round((job.finished or time.time()) - job.started, 1),
            "events": [msg for _, msg in job.events[-30:]],
            "result": job.result if job.kind == "ask" else "",
            "summary": job.result if job.kind == "run" else "",
            "error": job.error,
        }

    def get(self, job_id: int) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return self.snapshot(job) if job else None

    def status(self) -> dict:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.job_id, reverse=True)
            active = next((j for j in jobs if j.status == "running"), None)
            return {"active": self.snapshot(active) if active else None,
                    "recent": [self.snapshot(j) for j in jobs[:5]]}


def run_pipeline(db_path: Path, cfg: Config, gallery: str, days: int,
                 pages: int, minor: bool, emit: Emit) -> str:
    """collect → analyze → materialize → report. `krw-ontology-dc run` 과 동일 흐름 + 진행 이벤트."""
    import os

    from .analyze.trends import TrendAnalyzer
    from .cli import _make_llm
    from .ontology.materialize import materialize
    from .report.render import render_report, save_report

    cookies = os.environ.get(cfg.collect.cookies_env) or None
    collector = DcInsideCollector(gallery, cfg.collect, cookies=cookies, minor=minor)
    collected = 0
    with Store(db_path) as store:
        emit("phase", "수집")
        emit("msg", f"갤러리 `{gallery}` 페이지 {pages}개 수집 시작"
             + (" (마이너 갤러리 경로)" if minor else ""))

        def collect_progress(msg: str) -> None:
            emit("msg", f"[수집] {msg}")

        try:
            for post in collector.collect(pages, progress=collect_progress):
                post.author = author_hash(post.author, cfg.privacy_salt)
                store.upsert_post(post)
                store.replace_comments(post.gallery_id, post.post_no, post.comments)
                collected += 1
                emit("detail", f"{collected}건 저장")
        except BlockedError as exc:
            emit("msg", f"[수집] 차단 감지 — 여기까지({collected}건) 저장: {exc}")
        if collected == 0:
            raise RuntimeError("수집된 글이 없습니다 — 갤러리 ID·차단 상태를 확인하세요")

        emit("phase", "분석")
        emit("detail", "LLM 분석 준비 중")
        start, end = date.today() - timedelta(days=days), date.today()
        llm = _make_llm(cfg)

        def analyze_progress(msg: str) -> None:
            emit("msg", f"[분석] {msg}")
            emit("detail", msg)

        analyzer = Analyzer(store, llm, progress=analyze_progress)
        run_id, results, coverage = analyzer.run(
            gallery, start, end, _KINDS, max_chars=cfg.llm.max_chunk_chars)
        if run_id <= 0:
            raise RuntimeError("분석 기간에 글이 없습니다")
        materialize(store, gallery, run_id, PROMPT_VERSION, start, end, results)
        total, failed = coverage.get("chunks_total", 0), coverage.get("chunks_failed", 0)
        if total and failed == total:
            raise RuntimeError("모든 LLM 청크가 실패했습니다 — API 키/엔드포인트를 확인하세요")

        results = dict(results)
        try:
            trender = TrendAnalyzer(llm)
            prev_start, prev_end = start - (end - start), start - timedelta(days=1)
            prev = store.latest_analyses(gallery, prev_start, prev_end)
            if prev and len(results) >= 2:
                emit("msg", "[트렌드] 이전 기간과 비교")
                results["trends"] = trender.diff(
                    gallery, prev, {k: v for k, v in results.items() if k != "trends"},
                    f"{prev_start}~{prev_end}", f"{start}~{end}")
        except Exception as exc:  # 트렌드는 부가 결과 — 실패해도 측정은 완료
            emit("msg", f"[트렌드] 생략: {type(exc).__name__}")

        emit("phase", "리포트")
        analyses = store.latest_analyses(gallery, start, end)
        top = store.top_posts(gallery, start, end)
        md, payload = render_report(gallery, start, end, analyses, top, coverage)
        out = save_report(Path("reports"), gallery, start, end, md, payload)
        emit("msg", f"리포트 저장: {out}")
        emit("detail", f"run #{run_id} 완료")
    return f"{collected}건 수집 · 청크 {total - failed}/{total} 성공 · run #{run_id}"


def ask_job(db_path: Path, cfg: Config, gallery: str, question: str, emit: Emit) -> str:
    """온톨로지 도구 기반 질의(krw-ontology-dc ask) — 읽기 전용, 근거 인용 포함 답변."""
    from .cli import _make_llm
    from .ontology.ask import ask
    from .ontology.defn import load_ontology

    with Store(db_path) as store:
        emit("phase", "질의")
        emit("msg", "온톨로지 도구로 조사 중… reasoning 모델이라 수 분 걸릴 수 있습니다")
        answer = ask(store, load_ontology(None), _make_llm(cfg), gallery, question)
        emit("msg", "답변 완성")
    return answer
