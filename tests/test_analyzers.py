from datetime import date, datetime
from pathlib import Path

from dc_harness.analyze.kinds import KINDS, merge_chunk_results
from dc_harness.analyze.runner import Analyzer
from dc_harness.models import Comment, RawPost
from dc_harness.store import Store


def make_post(no: int) -> RawPost:
    return RawPost("crypto", no, f"t{no}", f"body{no}", "a",
                   datetime(2026, 8, 10), 10, no,
                   [Comment(no, 0, "댓글", no)])


class StubLlm:
    """chat_json 호출마다 canned 응답을 반환. 실패 지정 가능."""

    def __init__(self, reply, fail_first: int = 0):
        self.reply, self.fail_first = reply, fail_first
        self.calls = 0

    def chat_json(self, system, user, max_retries=2):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise ValueError("llm chunk failed")
        return self.reply


def test_kinds_registry_has_four_kinds():
    assert set(KINDS) == {"topics", "sentiment", "entities", "voices"}


def test_merge_topics_dedupes_by_label():
    merged = merge_chunk_results("topics", [
        {"topics": [{"label": "비트코인", "post_nos": [1, 2], "keywords": ["현물", "레버"]}]},
        {"topics": [{"label": "비트코인 ", "post_nos": [2, 3], "keywords": ["etf"]}]},
    ])
    assert len(merged["topics"]) == 1
    assert merged["topics"][0]["post_nos"] == [1, 2, 3]
    assert "etf" in merged["topics"][0]["keywords"]


def test_merge_entities_conflicting_sentiment_becomes_mixed():
    merged = merge_chunk_results("entities", [
        {"entities": [{"name": "이더리움", "type": "종목", "mentions": 3,
                       "sentiment": "긍정", "reason": "r"}]},
        {"entities": [{"name": "이더리움", "type": "종목", "mentions": 2,
                       "sentiment": "부정", "reason": "r2"}]},
    ])
    entity = merged["entities"][0]
    assert entity["mentions"] == 5 and entity["sentiment"] == "mixed"


def test_merge_voices_counts_duplicates():
    merged = merge_chunk_results("voices", [
        {"voices": [{"kind": "painpoint", "text": "앱이 느림", "post_no": 1, "quote": "q"}]},
        {"voices": [{"kind": "painpoint", "text": "앱이 느림 ", "post_no": 5, "quote": "q2"},
                    {"kind": "wish", "text": "다크모드", "post_no": 2, "quote": "q3"}]},
    ])
    by_text = {v["text"]: v for v in merged["voices"]}
    assert by_text["앱이 느림"]["count"] == 2
    assert by_text["다크모드"]["count"] == 1


def test_runner_map_reduce_with_stub(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        for no in (1, 2, 3, 4):
            store.upsert_post(make_post(no))
        stub = StubLlm({"topics": [{"label": "전망", "post_nos": [1], "keywords": ["롱"]}]})
        run_id, results, coverage = Analyzer(store, stub).run(
            "crypto", date(2026, 8, 1), date(2026, 8, 31), ["topics"], max_chars=300)
        assert run_id > 0
        assert results["topics"]["topics"][0]["label"] == "전망"
        assert coverage["chunks_total"] == stub.calls
        assert coverage["chunks_failed"] == 0
        saved = store.latest_analyses("crypto", date(2026, 8, 1), date(2026, 8, 31))
        assert "topics" in saved


def test_runner_isolates_permanently_failing_chunk(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        for no in (1, 2, 3, 4, 5, 6):
            store.upsert_post(make_post(no))

        class AlwaysFail:
            model = "stub"

            def chat_json(self, system, user, max_retries=2):
                raise ValueError("server busy")

        stub = AlwaysFail()
        run_id, results, coverage = Analyzer(store, stub).run(
            "crypto", date(2026, 8, 1), date(2026, 8, 31), ["topics"], max_chars=300)
        assert run_id > 0
        assert coverage["chunks_failed"] == coverage["chunks_total"] > 0
        assert results["topics"] == {"topics": []}
        # 청크당 2회(초기+재시도) 시도가 감사 로그에 기록된다
        calls = store.conn.execute("SELECT COUNT(*) c FROM llm_calls").fetchone()["c"]
        assert calls == coverage["chunks_total"] * 2


def test_runner_retry_recovers_transient_failure(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        for no in (1, 2, 3, 4):
            store.upsert_post(make_post(no))
        stub = StubLlm({"topics": [{"label": "전망", "post_nos": [1],
                                    "keywords": [], "snippet": ""}]}, fail_first=1)
        run_id, results, coverage = Analyzer(store, stub).run(
            "crypto", date(2026, 8, 1), date(2026, 8, 31), ["topics"], max_chars=300)
        assert run_id > 0
        assert coverage["chunks_failed"] == 0  # 재시도로 회복
        assert results["topics"]["topics"][0]["label"] == "전망"
