from datetime import date, datetime, timedelta
from pathlib import Path

from dc_harness.models import RawPost
from dc_harness.ontology.ask import ask, ontology_summary
from dc_harness.ontology.defn import load_ontology
from dc_harness.ontology.materialize import materialize
from dc_harness.ontology.tools import build_tools
from dc_harness.store import Store


class ScriptedLlm:
    model = "stub"

    def __init__(self, replies):
        self.replies = list(replies)
        self.users: list[str] = []

    def chat_json(self, system, user, max_retries=2):
        self.users.append(user)
        return self.replies.pop(0)


def seed(tmp_path: Path) -> Store:
    store = Store(tmp_path / "t.db")
    store.upsert_post(RawPost("crypto", 101, "현물이 답", "본문", "a",
                              datetime.now(), 10, 42))
    materialize(store, "crypto", 1, "v1",
                date.today() - timedelta(days=7), date.today(),
                {"topics": {"topics": [{"label": "현물 매수", "post_nos": [101],
                                        "keywords": ["매수"], "snippet": "s"}]}})
    return store


def test_ontology_summary_lists_objects_and_links():
    text = ontology_summary(load_ontology(None))
    assert "Topic" in text and "Discusses" in text and "논의된 토픽이다" in text


def test_tools_are_readonly_and_described(tmp_path: Path):
    store = seed(tmp_path)
    tools = build_tools(store, load_ontology(None), "crypto")
    assert set(tools) == {"queryObjects", "getThread", "stats"}
    assert all("반환" in t.description for t in tools.values())
    rows = tools["queryObjects"].fn({"apiName": "Topic", "days": 7})
    assert rows[0]["label"] == "현물 매수"
    thread = tools["getThread"].fn({"postNo": 101})
    assert thread["title"] == "현물이 답" and thread["topics"] == ["현물 매수"]


def test_ask_runs_tool_then_answers_with_citation(tmp_path: Path):
    store = seed(tmp_path)
    llm = ScriptedLlm([
        {"tool": "queryObjects", "args": {"apiName": "Topic", "days": 7}},
        {"answer": "최근 관심은 현물 매수입니다. 근거: [글#101]"},
    ])
    answer = ask(store, load_ontology(None), llm, "crypto", "요즘 관심사는?")
    assert "현물 매수" in answer and "글#101" in answer
    assert "근거 인용 없음" not in answer
    calls = store.conn.execute("SELECT * FROM llm_calls WHERE kind='ask'").fetchall()
    assert len(calls) == 2  # 감사: 스텝마다 기록


def test_ask_enforces_citation_once(tmp_path: Path):
    store = seed(tmp_path)
    llm = ScriptedLlm([
        {"answer": "인용 없는 답"},
        {"answer": "인용 없는 답 (재시도 후)"},
    ])
    answer = ask(store, load_ontology(None), llm, "crypto", "물어봄")
    assert "근거 인용 없음" in answer
    # 재시도 프롬프트에 인용 요구 문구가 전달됐는지
    assert "근거 인용" in llm.users[-1] or "인용" in llm.users[-1]


def test_ask_absorbs_bare_array_response(tmp_path: Path):
    # 실측: 모델이 [2937658] 처럼 배열을 바로 반환하는 경우
    store = seed(tmp_path)
    llm = ScriptedLlm([
        [2937658],
        {"answer": "최근 관심 주제는 현물 매수입니다. 근거: [글#101]"},
    ])
    answer = ask(store, load_ontology(None), llm, "crypto", "관심사는?")
    assert "현물 매수" in answer and "글#101" in answer
