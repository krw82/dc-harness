from datetime import date, datetime
from pathlib import Path

from dc_harness.models import Comment, RawPost
from dc_harness.store import Store


def make_post(post_no: int, rec: int = 0, day: str = "2026-08-10") -> RawPost:
    return RawPost(
        gallery_id="crypto", post_no=post_no, title=f"title {post_no}",
        body=f"body {post_no}", author="nick",
        created_at=datetime.fromisoformat(day + " 12:00:00"),
        views=100, recommend=rec,
        comments=[Comment(post_no=post_no, seq=0, text="comment text", recommend=3)],
    )


def test_upsert_is_idempotent(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.upsert_post(make_post(1, rec=5))
        p = make_post(1, rec=9)  # 재수집: 추천수 갱신
        p.comments = []
        store.upsert_post(p)
        posts = store.fetch_posts("crypto")
        assert len(posts) == 1
        assert posts[0].recommend == 9


def test_replace_comments(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.upsert_post(make_post(1))
        store.replace_comments("crypto", 1, [Comment(1, 0, "a", 1), Comment(1, 1, "b", 2)])
        store.replace_comments("crypto", 1, [Comment(1, 0, "c", 7)])
        posts = store.fetch_posts("crypto")
        assert [c.text for c in posts[0].comments] == ["c"]


def test_fetch_posts_filters_by_period(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.upsert_post(make_post(1, day="2026-08-01"))
        store.upsert_post(make_post(2, day="2026-08-10"))
        got = store.fetch_posts("crypto", start=date(2026, 8, 5), end=date(2026, 8, 15))
        assert [p.post_no for p in got] == [2]


def test_top_posts_orders_by_recommend(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        for no, rec in [(1, 3), (2, 30), (3, 10)]:
            store.upsert_post(make_post(no, rec=rec))
        assert [p.post_no for p in store.top_posts("crypto", None, None)] == [2, 3, 1]


def test_runs_and_analyses_roundtrip(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        run_id = store.start_run("crypto")
        store.save_analysis(run_id, "topics", "crypto",
                            date(2026, 8, 1), date(2026, 8, 7), {"topics": []})
        store.finish_run(run_id, "done", {"posts": 1})
        got = store.latest_analyses("crypto", date(2026, 8, 1), date(2026, 8, 7))
        assert got["topics"] == {"topics": []}
