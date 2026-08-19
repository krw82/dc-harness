import json
from datetime import date
from pathlib import Path

import pytest

from dc_harness.store import Store

TOPIC_ROW = {"run_id": 1, "gallery_id": "crypto", "topic_id": "t1",
             "period_start": "2026-08-01", "period_end": "2026-08-07",
             "label": "현물 매수", "snippet": "s", "keywords": json.dumps(["매수"]),
             "source_post_nos": json.dumps([101]), "prompt_version": "v1"}


def test_snapshot_rows_writes_and_replaces(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        assert store.snapshot_rows("obj_topics", 1, [TOPIC_ROW]) == 1
        assert store.snapshot_rows("obj_topics", 1, [dict(TOPIC_ROW, label="변경")]) == 1
        rows = store.fetch_object_rows("obj_topics", 1)
        assert len(rows) == 1 and rows[0]["label"] == "변경"  # SNAPSHOT: 덮어쓰기
        assert rows[0]["run_id"] == 1  # run_id 자동 주입


def test_snapshot_rows_rejects_unknown_table(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        with pytest.raises(ValueError, match="not an object table"):
            store.snapshot_rows("posts", 1, [{}])


def test_snapshot_rows_ignores_unknown_columns(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        assert store.snapshot_rows("obj_topics", 1, [dict(TOPIC_ROW, hacker="x")]) == 1
        rows = store.fetch_object_rows("obj_topics", 1)
        assert "hacker" not in rows[0]


def test_snapshot_delete_happens_even_with_no_rows(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.snapshot_rows("obj_topics", 1, [TOPIC_ROW])
        assert store.snapshot_rows("obj_topics", 1, []) == 0
        assert store.fetch_object_rows("obj_topics", 1) == []


def test_latest_object_run(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.snapshot_rows("obj_topics", 1, [TOPIC_ROW])
        store.snapshot_rows("obj_topics", 2, [dict(TOPIC_ROW, label="r2")])
        got = store.latest_object_run("obj_topics", "crypto",
                                      date(2026, 8, 1), date(2026, 8, 7))
        assert got == 2
        assert store.latest_object_run("obj_topics", "crypto",
                                       date(2030, 1, 1), date(2030, 1, 2)) is None


def test_log_llm_call(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.log_llm_call(1, "topics", "sys", "user", '{"topics": []}', "m", "v1")
        row = store.conn.execute("SELECT * FROM llm_calls").fetchone()
        assert row["kind"] == "topics" and row["model"] == "m"
        assert row["prompt_version"] == "v1"
