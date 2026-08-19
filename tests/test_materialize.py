import json
from datetime import date
from pathlib import Path

from dc_harness.ontology.materialize import materialize
from dc_harness.store import Store

RESULTS = {
    "topics": {"topics": [
        {"label": "현물 매수", "post_nos": [101, 102], "keywords": ["매수"], "snippet": "s"}]},
    "entities": {"entities": [
        {"name": "이더리움", "type": "종목", "mentions": 5, "sentiment": "부정", "reason": "r"}]},
    "sentiment": {"issues": [
        {"issue": "반감기", "pro": 4, "con": 2, "neutral": 1, "quotes": []}],
        "resonant": []},
    "voices": {"voices": [
        {"kind": "painpoint", "text": "앱이 느림", "post_no": 101, "quote": "느림", "count": 3}]},
}


def test_materialize_writes_all_objects_with_provenance(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        counts = materialize(store, "crypto", 7, "v1",
                             date(2026, 8, 1), date(2026, 8, 7), RESULTS)
        assert counts == {"Topic": 1, "Entity": 1, "Issue": 1, "Voice": 1, "PostTopic": 2}
        rows = store.fetch_object_rows("obj_topics", 7)
        assert rows[0]["label"] == "현물 매수" and rows[0]["run_id"] == 7
        assert rows[0]["prompt_version"] == "v1"
        assert json.loads(rows[0]["source_post_nos"]) == [101, 102]
        junction = store.fetch_object_rows("obj_post_topics", 7)
        assert {r["post_no"] for r in junction} == {101, 102}
        entity = store.fetch_object_rows("obj_entities", 7)
        assert entity[0]["mentions"] == 5 and entity[0]["sentiment"] == "부정"
        issue = store.fetch_object_rows("obj_issues", 7)
        assert (issue[0]["pro_count"], issue[0]["con_count"]) == (4, 2)
        voice = store.fetch_object_rows("obj_voices", 7)
        assert voice[0]["count"] == 3 and voice[0]["source_post_no"] == 101


def test_materialize_snapshot_replaces_same_run(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        materialize(store, "crypto", 7, "v1", date(2026, 8, 1), date(2026, 8, 7), RESULTS)
        smaller = {"topics": RESULTS["topics"]}
        materialize(store, "crypto", 7, "v1", date(2026, 8, 1), date(2026, 8, 7), smaller)
        assert len(store.fetch_object_rows("obj_topics", 7)) == 1
        assert store.fetch_object_rows("obj_voices", 7) == []  # SNAPSHOT: 이전 run 7 분 삭제
