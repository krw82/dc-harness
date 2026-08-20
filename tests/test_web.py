import json
from datetime import date, datetime
from pathlib import Path

from dc_harness.models import RawPost
from dc_harness.store import Store
from dc_harness.web import api_galleries, api_overview, route


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
        store.finish_run(run_id, "done", {})
    return db


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
    with Store(seed(tmp_path)) as store:
        code, body, ctype = route(store, "/", "")
        assert code == 200 and "text/html" in ctype and "여론".encode() in body

        code, body, ctype = route(store, "/api/galleries", "")
        assert code == 200
        assert any(g["id"] == "crypto" for g in json.loads(body))

        code, body, _ = route(store, "/api/overview", "gallery=crypto")
        assert code == 200 and json.loads(body)["measured"] is True

        assert route(store, "/api/overview", "gallery=bad;id")[0] == 400
        assert route(store, "/nope", "")[0] == 404
