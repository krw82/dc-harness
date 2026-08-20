"""초경량 로컬 웹 뷰어·관제판 — 1인용. stdlib http.server만 사용.

실행: .venv/bin/dch web   →  http://127.0.0.1:8765
읽기(뷰어) + 측정·질문 작업 시작(관제판). 자격증명은 환경변수로만(.env.local은 로컬 전용).
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import Config, load_config
from .store import Store
from .web_jobs import JobBusyError, JobManager, ask_job, run_pipeline

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 10_000


def _load_env_local(path: Path = Path(".env.local")) -> None:
    """로컬 전용 시크릿(.env.local, gitignore)을 환경변수에 적재 — 기존 env는 우선."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _latest_period(store: Store, gallery_id: str) -> tuple[date, date] | None:
    row = store.conn.execute(
        "SELECT period_start, period_end FROM analyses WHERE gallery_id=? ORDER BY run_id DESC, period_end DESC LIMIT 1",
        (gallery_id,)).fetchone()
    if row is None:
        return None
    return (date.fromisoformat(row["period_start"]),
            date.fromisoformat(row["period_end"]))


def _daily_counts(store: Store, gallery_id: str, start: date, end: date) -> list[dict]:
    rows = store.conn.execute(
        "SELECT date(created_at) AS d, COUNT(*) AS c FROM posts WHERE gallery_id=? AND created_at IS NOT NULL AND date(created_at)>=? AND date(created_at)<=? GROUP BY date(created_at) ORDER BY d",
        (gallery_id, start.isoformat(), end.isoformat())).fetchall()
    by_day = {r["d"]: r["c"] for r in rows}
    days = []
    cur = start
    while cur <= end:
        days.append({"date": cur.isoformat(), "count": by_day.get(cur.isoformat(), 0)})
        cur += timedelta(days=1)
    return days


def api_galleries(store: Store) -> list[dict]:
    rows = store.conn.execute(
        "SELECT gallery_id, COUNT(*) AS posts, MAX(created_at) AS latest FROM posts GROUP BY gallery_id ORDER BY posts DESC").fetchall()
    out = []
    for r in rows:
        period = _latest_period(store, r["gallery_id"])
        out.append({"id": r["gallery_id"], "posts": r["posts"],
                    "latest_post": r["latest"],
                    "measured": period is not None})
    return out


def api_overview(store: Store, gallery_id: str) -> dict:
    period = _latest_period(store, gallery_id)
    if period is None:
        return {"gallery": gallery_id, "measured": False}
    start, end = period
    analyses = store.latest_analyses(gallery_id, start, end)
    posts = store.fetch_posts(gallery_id, start, end)
    run_row = store.conn.execute(
        "SELECT MAX(run_id) AS m FROM analyses WHERE gallery_id=?", (gallery_id,)
    ).fetchone()
    voices = analyses.get("voices", {}).get("voices", [])
    topics = analyses.get("topics", {}).get("topics", [])
    issues = analyses.get("sentiment", {}).get("issues", [])
    entities = analyses.get("entities", {}).get("entities", [])
    return {
        "gallery": gallery_id,
        "measured": True,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "run_id": run_row["m"] if run_row else None,
        "counts": {"posts": len(posts), "topics": len(topics),
                   "issues": len(issues), "entities": len(entities),
                   "voices": len(voices)},
        "activity": _daily_counts(store, gallery_id, start, end),
        "topics": topics,
        "issues": issues,
        "resonant": analyses.get("sentiment", {}).get("resonant", []),
        "entities": entities,
        "voices": voices,
        "top_posts": [{"post_no": p.post_no, "title": p.title,
                       "recommend": p.recommend, "views": p.views}
                      for p in sorted(posts, key=lambda p: p.recommend,
                                      reverse=True)[:10]],
    }


def api_posts(store: Store, gallery_id: str, post_nos: list[int]) -> list[dict]:
    """근거 글 원문 조회 — 호출점마다 정적 리터럴 SQL (I2)."""
    out: list[dict] = []
    for no in post_nos[:50]:
        row = store.conn.execute(
            "SELECT post_no, title, author_hash, created_at, views, recommend, body FROM posts WHERE gallery_id=? AND post_no=?",
            (gallery_id, no)).fetchone()
        if row is not None:
            out.append({"post_no": row["post_no"], "title": row["title"],
                        "author": row["author_hash"], "created_at": row["created_at"],
                        "views": row["views"], "recommend": row["recommend"],
                        "body": row["body"]})
    return out


def api_runs(store: Store) -> list[dict]:
    rows = store.conn.execute(
        "SELECT id, gallery_id, started_at, finished_at, status, stats FROM runs ORDER BY id DESC LIMIT 20").fetchall()
    return [{"id": r["id"], "gallery": r["gallery_id"], "started_at": r["started_at"],
             "finished_at": r["finished_at"], "status": r["status"], "stats": r["stats"]}
            for r in rows]


def api_llm_calls(store: Store, run_id: int | None) -> list[dict]:
    if run_id:
        rows = store.conn.execute(
            "SELECT id, run_id, kind, model, prompt_version, created_at, substr(response_text,1,240) AS excerpt, response_text LIKE '(failed%' AS failed FROM llm_calls WHERE run_id=? ORDER BY id DESC LIMIT 50",
            (run_id,)).fetchall()
    else:
        rows = store.conn.execute(
            "SELECT id, run_id, kind, model, prompt_version, created_at, substr(response_text,1,240) AS excerpt, response_text LIKE '(failed%' AS failed FROM llm_calls ORDER BY id DESC LIMIT 50").fetchall()
    return [{"id": r["id"], "run_id": r["run_id"], "kind": r["kind"],
             "model": r["model"], "prompt_version": r["prompt_version"],
             "created_at": r["created_at"], "excerpt": r["excerpt"],
             "failed": bool(r["failed"])} for r in rows]


def api_report(gallery_id: str) -> dict:
    files = sorted(Path("reports", gallery_id).glob("*.md"), reverse=True)
    if not files:
        return {"found": False}
    latest = files[0]
    return {"found": True, "path": str(latest),
            "markdown": latest.read_text(encoding="utf-8")[:200_000]}


def _valid_gallery(gallery: str) -> bool:
    return bool(gallery) and gallery.replace("_", "").isalnum()


def _json(payload, code: int = 200) -> tuple[int, bytes, str]:
    return code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"


@dataclass
class WebApp:
    """라우팅에 필요한 의존성 묶음 — 순수 함수 테스트용.

    store는 스레드 로컬: http.server가 요청마다 새 스레드를 쓰므로 sqlite 연결을
    스레드별로 만든다 (연결 공유 금지).
    """
    db_path: Path = Path("data/dch.db")
    cfg: Config = field(default_factory=lambda: load_config(None))
    jobs: JobManager = field(default_factory=JobManager)
    _tls: threading.local = field(default_factory=threading.local,
                                  repr=False, compare=False)

    @classmethod
    def create(cls, db_path: Path, cfg: Config | None = None) -> "WebApp":
        return cls(db_path=db_path, cfg=cfg or load_config(None))

    @property
    def store(self) -> Store:
        if not hasattr(self._tls, "store"):
            self._tls.store = Store(self.db_path)
        return self._tls.store


def route(app: WebApp, path: str, query: str) -> tuple[int, bytes, str]:
    """GET 라우팅 (순수 함수 — 테스트는 소켓 없이 여기만 호출)."""
    if path == "/":
        return 200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8"
    if path == "/api/galleries":
        return _json(api_galleries(app.store))
    if path == "/api/overview":
        gallery = (parse_qs(query).get("gallery") or [""])[0]
        if not _valid_gallery(gallery):
            return 400, b"bad gallery", "text/plain; charset=utf-8"
        return _json(api_overview(app.store, gallery))
    if path == "/api/posts":
        q = parse_qs(query)
        gallery = (q.get("gallery") or [""])[0]
        raw_nos = (q.get("nos") or [""])[0]
        if not _valid_gallery(gallery) or not raw_nos.replace(",", "").isdigit():
            return 400, b"bad query", "text/plain; charset=utf-8"
        nos = [int(n) for n in raw_nos.split(",") if n][:50]
        return _json(api_posts(app.store, gallery, nos))
    if path == "/api/status":
        return _json(app.jobs.status())
    if path == "/api/runs":
        return _json(api_runs(app.store))
    if path == "/api/llm-calls":
        raw = (parse_qs(query).get("run_id") or [""])[0]
        run_id = int(raw) if raw.isdigit() else None
        return _json(api_llm_calls(app.store, run_id))
    if path == "/api/report":
        gallery = (parse_qs(query).get("gallery") or [""])[0]
        if not _valid_gallery(gallery):
            return 400, b"bad gallery", "text/plain; charset=utf-8"
        return _json(api_report(gallery))
    return 404, b"not found", "text/plain; charset=utf-8"


def route_post(app: WebApp, path: str, body: dict) -> tuple[int, bytes, str]:
    """POST 라우팅 — 작업 시작(관제판)."""
    if path == "/api/run":
        gallery = str(body.get("gallery", ""))
        if not _valid_gallery(gallery):
            return _json({"error": "bad gallery"}, 400)
        try:
            days = max(1, min(90, int(body.get("days", 7))))
            pages = max(1, min(15, int(body.get("pages", 3))))
        except (TypeError, ValueError):
            return _json({"error": "bad days/pages"}, 400)
        minor = bool(body.get("minor", False))
        try:
            job_id = app.jobs.start(
                "run", gallery,
                lambda emit: run_pipeline(app.db_path, app.cfg, gallery,
                                          days, pages, minor, emit))
        except JobBusyError as exc:
            return _json({"error": str(exc)}, 409)
        return _json({"job_id": job_id}, 202)
    if path == "/api/ask":
        gallery = str(body.get("gallery", ""))
        question = str(body.get("question", "")).strip()
        if not _valid_gallery(gallery):
            return _json({"error": "bad gallery"}, 400)
        if not (1 <= len(question) <= 500):
            return _json({"error": "question 1~500자"}, 400)
        try:
            job_id = app.jobs.start(
                "ask", gallery,
                lambda emit: ask_job(app.db_path, app.cfg, gallery, question, emit))
        except JobBusyError as exc:
            return _json({"error": str(exc)}, 409)
        return _json({"job_id": job_id}, 202)
    return 404, b"not found", "text/plain; charset=utf-8"


class ViewerHandler(BaseHTTPRequestHandler):
    app: WebApp | None = None

    def log_message(self, fmt, *args):  # 콘솔 조용히
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server 규약
        parsed = urlparse(self.path)
        self._send(*route(self.app, parsed.path, parsed.query))

    def do_POST(self):  # noqa: N802 - http.server 규약
        parsed = urlparse(self.path)
        try:
            length = min(int(self.headers.get("Content-Length", 0)), MAX_BODY)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be object")
        except (ValueError, json.JSONDecodeError):
            self._send(400, b"bad json", "text/plain; charset=utf-8")
            return
        self._send(*route_post(self.app, parsed.path, body))


def run_server(db_path: Path, port: int = 8765) -> None:
    _load_env_local()
    app = WebApp.create(db_path)

    class BoundHandler(ViewerHandler):
        @property
        def app(self) -> WebApp:  # 모든 요청 스레드가 같은 앱/작업관리자를 공유
            return app

    server = ThreadingHTTPServer(("127.0.0.1", port), BoundHandler)  # 로컬 전용
    print(f"여론 관측소·관제판 가동: http://127.0.0.1:{port}  (종료: Ctrl+C)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")
