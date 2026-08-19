from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from dc_harness.models import RawPost
from dc_harness.ontology.defn import load_ontology
from dc_harness.ontology.materialize import materialize
from dc_harness.ontology.query import print_rows, query_objects, show_post
from dc_harness.store import Store

RESULTS = {"topics": {"topics": [{"label": "현물 매수", "post_nos": [101],
                                  "keywords": ["매수"], "snippet": "s"}]}}


def seed(tmp_path: Path) -> tuple[Store, RawPost]:
    store = Store(tmp_path / "t.db")
    post = RawPost("crypto", 101, "현물이 답", "b", "a",
                   datetime.now(), 10, 42)
    store.upsert_post(post)
    materialize(store, "crypto", 1, "v1",
                date.today() - timedelta(days=7), date.today(), RESULTS)
    return store, post


def test_query_topic_objects(tmp_path: Path):
    store, _ = seed(tmp_path)
    rows = query_objects(store, load_ontology(None), "Topic", "crypto",
                         date.today() - timedelta(days=7), date.today())
    assert len(rows) == 1 and rows[0]["label"] == "현물 매수"


def test_query_post_raw(tmp_path: Path):
    store, _ = seed(tmp_path)
    rows = query_objects(store, load_ontology(None), "Post", "crypto",
                         date.today() - timedelta(days=1), date.today())
    assert [r["post_no"] for r in rows] == [101]


def test_query_unsupported_object(tmp_path: Path):
    store, _ = seed(tmp_path)
    with pytest.raises(ValueError, match="질의 미지원"):
        query_objects(store, load_ontology(None), "Author", "crypto",
                      date.today(), date.today())


def test_show_post_includes_linked_topics(tmp_path: Path):
    store, _ = seed(tmp_path)
    detail = show_post(store, "crypto", 101)
    assert detail["post"].title == "현물이 답"
    assert detail["topics"] == ["현물 매수"]


def test_print_rows_renders_values():
    out = print_rows([{"label": "현물 매수", "mentions": 5}, {"label": "채굴", "mentions": 1}])
    assert "현물 매수" in out and "채굴" in out and "mentions" in out
