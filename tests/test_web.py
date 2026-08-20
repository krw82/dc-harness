import json
import threading
import time
from datetime import date, datetime
from pathlib import Path

from dc_harness.models import RawPost
from dc_harness.store import Store
from dc_harness.web import WebApp, api_galleries, api_overview, api_posts, route, route_post
from dc_harness.web_jobs import JobBusyError, JobManager


def seed(tmp_path: Path) -> Path:
    db = tmp_path / "t.db"
    with Store(db) as store:
        store.upsert_post(RawPost("crypto", 101, "현물이 답", "본문", "a",
                                  datetime(2026, 8, 15, 9, 0), 10, 42))
        store.upsert_post(RawPost("empty", 1, "t", "b", "a",
                                  datetime(2026, 8, 15, 9, 0), 1, 0))
        run_id = store.start_run("crypto")
        store.save_analysis(run_id, "topics", "crypto",
                            date(2026, 8, 13), date(2026, 8, 20),
                            {"topics": [{"label": "현물 매수", "post_nos": [101],
                                         "keywords": ["매수"], "snippet": "s"}]})
        store.log_llm_call(run_id, "topics", "sys", "user", '{"ok":1}', "m", "v1")
        store.log_llm_call(run_id, "topics", "sys", "user", "(failed attempt 1) X", "m", "v1")
        store.finish_run(run_id, "done", {"chunks_total": 2, "chunks_failed": 1})
    return db


def make_app(tmp_path: Path) -> WebApp:
    return WebApp.create(seed(tmp_path))


def test_api_overview_shapes(tmp_path: Path):
    with Store(seed(tmp_path)) as store:
        gals = api_galleries(store)
        assert {g["id"] for g in gals} == {"crypto", "empty"}
        measured = {g["id"]: g["measured"] for g in gals}
        assert measured["crypto"] is True and measured["empty"] is False

        o = api_overview(store, "crypto")
        assert o["measured"] and o["run_id"] is not None
        assert o["counts"]["posts"] == 1
        assert o["topics"][0]["label"] == "현물 매수"
        assert len(o["activity"]) == 8  # 08-13 ~ 08-20
        assert o["activity"][2]["count"] == 1
        assert o["top_posts"][0]["recommend"] == 42

        assert api_overview(store, "empty") == {"gallery": "empty", "measured": False}


def test_route_endpoints(tmp_path: Path):
    app = make_app(tmp_path)
    code, body, ctype = route(app, "/", "")
    assert code == 200 and "text/html" in ctype and "여론".encode() in body

    code, body, _ = route(app, "/api/galleries", "")
    assert code == 200
    assert any(g["id"] == "crypto" for g in json.loads(body))

    code, body, _ = route(app, "/api/overview", "gallery=crypto")
    assert code == 200 and json.loads(body)["measured"] is True

    assert route(app, "/api/overview", "gallery=bad;id")[0] == 400
    assert route(app, "/nope", "")[0] == 404


def test_api_posts_returns_originals(tmp_path: Path):
    with Store(seed(tmp_path)) as store:
        posts = api_posts(store, "crypto", [101, 999])
        assert len(posts) == 1                       # 없는 글 번호는 조용히 제외
        p = posts[0]
        assert p["post_no"] == 101 and p["title"] == "현물이 답"
        assert set(p) == {"post_no", "title", "author", "created_at",
                          "views", "recommend", "body"}
        assert p["recommend"] == 42

    app = make_app(tmp_path)
    code, body, ctype = route(app, "/api/posts", "gallery=crypto&nos=101")
    assert code == 200 and "application/json" in ctype
    assert json.loads(body)[0]["title"] == "현물이 답"

    assert route(app, "/api/posts", "gallery=crypto&nos=abc")[0] == 400
    assert route(app, "/api/posts", "nos=101")[0] == 400


def test_route_runs_and_llm_calls(tmp_path: Path):
    app = make_app(tmp_path)
    code, body, _ = route(app, "/api/runs", "")
    runs = json.loads(body)
    assert code == 200 and runs[0]["id"] == 1 and runs[0]["status"] == "done"

    code, body, _ = route(app, "/api/llm-calls", "run_id=1")
    calls = json.loads(body)
    assert code == 200 and len(calls) == 2
    assert calls[0]["failed"] != calls[1]["failed"]  # 성공/실패 구분 표시


def test_route_post_validation(tmp_path: Path):
    app = make_app(tmp_path)
    assert route_post(app, "/api/run", {"gallery": "bad;id"})[0] == 400
    assert route_post(app, "/api/run", {"gallery": "ok", "days": "x"})[0] == 400
    assert route_post(app, "/api/ask", {"gallery": "ok", "question": ""})[0] == 400
    assert route_post(app, "/api/ask", {"gallery": "ok", "question": "가" * 501})[0] == 400
    assert route_post(app, "/api/nope", {})[0] == 404


class BusyJobs:
    def start(self, *a, **k):
        raise JobBusyError("busy")


def test_route_post_busy(tmp_path: Path):
    app = make_app(tmp_path)
    app.jobs = BusyJobs()
    code, body, _ = route_post(app, "/api/run", {"gallery": "crypto"})
    assert code == 409 and "error" in json.loads(body)


def test_job_manager_lifecycle():
    mgr = JobManager()

    def job(emit):
        emit("phase", "수집")
        emit("msg", "시작")
        time.sleep(0.05)
        return "요약"

    jid = mgr.start("run", "crypto", job)
    deadline = time.time() + 2
    while time.time() < deadline:
        snap = mgr.get(jid)
        if snap["status"] == "done":
            break
        time.sleep(0.02)
    assert snap["status"] == "done" and snap["phase"] == "완료"
    assert snap["summary"] == "요약" and any("시작" in e for e in snap["events"])
    st = mgr.status()
    assert st["active"] is None and st["recent"][0]["job_id"] == jid

    # 실행 중이면 새 작업 거부
    started = threading.Event()

    def slow(emit):
        started.set()
        time.sleep(0.3)

    mgr.start("ask", "crypto", slow)
    started.wait(1)
    try:
        mgr.start("run", "crypto", lambda emit: "")
        raised = False
    except JobBusyError:
        raised = True
    assert raised


def test_job_manager_error_captured():
    mgr = JobManager()

    def boom(emit):
        raise ValueError("사고")

    jid = mgr.start("ask", "crypto", boom)
    deadline = time.time() + 2
    while time.time() < deadline:
        snap = mgr.get(jid)
        if snap["status"] != "running":
            break
        time.sleep(0.02)
    assert snap["status"] == "error" and "ValueError" in snap["error"]


def test_web_app_thread_local_stores(tmp_path: Path):
    app = make_app(tmp_path)
    main_store = app.store
    results = {}

    def worker():
        results["store"] = app.store
        code, body, _ = route(app, "/api/galleries", "")
        results["gals"] = json.loads(body)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert results["store"] is not main_store          # 스레드별 별개 연결
    assert any(g["id"] == "crypto" for g in results["gals"])
