from datetime import date, datetime
from pathlib import Path

from dc_harness.analyze.kinds import PROMPT_VERSION
from dc_harness.analyze.runner import Analyzer
from dc_harness.models import RawPost
from dc_harness.store import Store


class StubLlm:
    model = "stub-model"

    def chat_json(self, system, user, max_retries=2):
        return {"topics": [{"label": "전망", "post_nos": [1], "keywords": [], "snippet": ""}]}


def make_post(no: int) -> RawPost:
    return RawPost("crypto", no, f"t{no}", "b", "a", datetime(2026, 8, 10), 1, 1)


def test_run_returns_run_id_and_audits_calls(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.upsert_post(make_post(1))
        run_id, results, coverage = Analyzer(store, StubLlm()).run(
            "crypto", date(2026, 8, 1), date(2026, 8, 31), ["topics"], max_chars=500)
        assert run_id > 0
        assert results["topics"]["topics"][0]["label"] == "전망"
        assert coverage["chunks_failed"] == 0
        calls = store.conn.execute("SELECT * FROM llm_calls").fetchall()
        assert len(calls) == 1
        assert calls[0]["kind"] == "topics" and calls[0]["model"] == "stub-model"
        assert calls[0]["prompt_version"] == PROMPT_VERSION
        assert calls[0]["run_id"] == run_id


def test_run_empty_store_returns_minus_one(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        run_id, results, coverage = Analyzer(store, StubLlm()).run(
            "crypto", date(2026, 8, 1), date(2026, 8, 31), ["topics"])
        assert run_id == -1 and results == {} and coverage["posts_total"] == 0
