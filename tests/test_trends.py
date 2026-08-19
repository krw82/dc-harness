import json

from dc_harness.analyze.trends import TrendAnalyzer

PREV = {"topics": {"topics": [{"label": "레버리지", "post_nos": [1],
                               "keywords": ["롱"], "snippet": ""}]}}
CUR = {"topics": {"topics": [{"label": "현물", "post_nos": [2],
                              "keywords": ["매수"], "snippet": ""}]}}


class StubLlm:
    def __init__(self):
        self.seen_user = ""

    def chat_json(self, system, user, max_retries=2):
        self.seen_user = user
        return {"rising": [{"label": "현물", "reason": "신규 언급 급증"}],
                "falling": [{"label": "레버리지", "reason": "언급 감소"}],
                "shifts": [{"label": "이더리움", "from": "긍정", "to": "부정"}],
                "summary": "현물 관심이 레버리지를 대체"}


def test_diff_returns_llm_result_and_includes_both_periods():
    stub = StubLlm()
    result = TrendAnalyzer(stub).diff("crypto", PREV, CUR, "지난주", "이번주")
    assert result["rising"][0]["label"] == "현물"
    assert "지난주" in stub.seen_user and "이번주" in stub.seen_user
    assert json.dumps(PREV["topics"], ensure_ascii=False) in stub.seen_user
