from __future__ import annotations

import json

from ..llm.client import LlmClient
from .kinds import SYSTEM_PROMPT


class TrendAnalyzer:
    INSTRUCTION = (
        "두 기간의 분석 결과 JSON이 주어진다. 이번 기간에 새로 떠오르거나 언급이 늘어난 "
        "주제(rising), 식었거나 사라진 주제(falling), 여론이 바뀐 대상(shifts)을 찾고 "
        "세 문장 이내로 요약(summary)하라."
    )
    SCHEMA = ('{"rising": [{"label": "...", "reason": "..."}], '
              '"falling": [{"label": "...", "reason": "..."}], '
              '"shifts": [{"label": "...", "from": "...", "to": "..."}], '
              '"summary": "..."}')

    def __init__(self, llm: LlmClient):
        self.llm = llm

    def diff(self, gallery_id: str, prev: dict, cur: dict,
             prev_label: str, cur_label: str) -> dict:
        user = (f"{self.INSTRUCTION}\n\n출력 스키마(JSON):\n{self.SCHEMA}\n\n"
                f"=== {prev_label} 분석 결과 ===\n{json.dumps(prev, ensure_ascii=False)}\n\n"
                f"=== {cur_label} 분석 결과 ===\n{json.dumps(cur, ensure_ascii=False)}")
        return self.llm.chat_json(SYSTEM_PROMPT, user)
