from __future__ import annotations

from dataclasses import dataclass

from ..normalize import normalize_label

# 프롬프트 문구를 바꾸면 반드시 상향 (llm_calls/obj_* lineage의 키).
PROMPT_VERSION = "v1"

_SYSTEM = (
    "너는 한국 커뮤니티(DC Inside) 데이터를 분석하는 연구 보조자다. "
    "입력은 게시글/댓글 모음이다. 오직 요청된 JSON 객체만 출력하고 다른 설명은 하지 마라. "
    "욕설·비속어는 분석 대상일 뿐 출력에 그대로 반복하지 마라."
)

SYSTEM_PROMPT = _SYSTEM


@dataclass
class AnalysisKind:
    name: str
    system: str
    instruction: str
    schema_hint: str


KINDS: dict[str, AnalysisKind] = {
    "topics": AnalysisKind(
        name="topics", system=_SYSTEM,
        instruction="이 게시글/댓글 모음에서 논의되는 상위 토픽(주제)을 추출하라. "
                    "토픽 3~7개, 각 토픽마다 근거가 된 글 번호(post_no)와 반복 키워드를 포함하라.",
        schema_hint='{"topics": [{"label": "토픽명", "post_nos": [101], '
                    '"keywords": ["k1", "k2"], "snippet": "대표 문장 한 줄"}]}',
    ),
    "sentiment": AnalysisKind(
        name="sentiment", system=_SYSTEM,
        instruction="주요 이슈별 여론을 분석하라. 각 이슈의 찬성(pro)/반대(con)/중립(neutral) "
                    "발언 수와 대표 인용(최대 3개)을 포함하라. 추천수가 높은 글/댓글은 "
                    "공감을 얻은 반응이므로 resonant 배열에 따로 정리하라.",
        schema_hint='{"issues": [{"issue": "이슈명", "pro": 3, "con": 1, "neutral": 0, '
                    '"quotes": [{"post_no": 101, "stance": "pro", "text": "..."}]}], '
                    '"resonant": [{"post_no": 101, "text": "...", "why": "왜 공감을 얻었는지"}]}',
    ),
    "entities": AnalysisKind(
        name="entities", system=_SYSTEM,
        instruction="언급된 인물/종목/제품/브랜드/서비스(entity)를 추출하고 각각에 대한 "
                    "여론(sentiment: 긍정/부정/mixed/중립)과 이유를 정리하라.",
        schema_hint='{"entities": [{"name": "이름", "type": "인물|종목|제품|브랜드|기타", '
                    '"mentions": 5, "sentiment": "긍정", "reason": "..."}]}',
    ),
    "voices": AnalysisKind(
        name="voices", system=_SYSTEM,
        instruction="불만(painpoint), 바람(wish: \'~있으면 좋겠다\'), 아이디어(idea)를 추출하라. "
                    "각 항목은 원문 인용과 글 번호를 포함하고, 사용자 표현을 축약하지 마라.",
        schema_hint='{"voices": [{"kind": "painpoint|wish|idea", "text": "요약 한 줄", '
                    '"post_no": 101, "quote": "원문 인용"}]}',
    ),
}


def _cap(items: list, limit: int) -> list:
    return items[:limit]


_ARRAY_KEY_HINTS = (
    ("topics", {"label", "post_nos", "keywords"}),
    ("issues", {"issue", "pro", "con", "neutral", "stance"}),
    ("entities", {"name", "mentions", "sentiment"}),
    ("voices", {"kind", "quote", "painpoint", "wish"}),
)


def normalize_chunk_result(result: dict | list) -> dict:
    """모델이 {"topics": [...]} 대신 배열이나 다른 모양으로 반환해도 표준 dict로 정규화."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        keys: set[str] = set()
        for item in result:
            if isinstance(item, dict):
                keys |= set(item.keys())
        for array_key, hint in _ARRAY_KEY_HINTS:
            if keys & hint:
                return {array_key: [i for i in result if isinstance(i, dict)]}
        return {}
    return {}


def merge_chunk_results(kind: str, results: list[dict]) -> dict:
    results = [normalize_chunk_result(res) for res in results]
    if kind == "topics":
        by_label: dict[str, dict] = {}
        for res in results:
            for topic in res.get("topics", []):
                key = normalize_label(topic.get("label", ""))
                if key in by_label:
                    merged = by_label[key]
                    merged["post_nos"] = list(dict.fromkeys(
                        merged["post_nos"] + topic.get("post_nos", [])))
                    merged["keywords"] = list(dict.fromkeys(
                        merged["keywords"] + topic.get("keywords", [])))[:8]
                else:
                    by_label[key] = {
                        "label": topic.get("label", ""), "post_nos": topic.get("post_nos", []),
                        "keywords": topic.get("keywords", [])[:8],
                        "snippet": topic.get("snippet", ""),
                    }
        return {"topics": _cap(list(by_label.values()), 10)}

    if kind == "sentiment":
        by_issue: dict[str, dict] = {}
        resonant: list[dict] = []
        for res in results:
            resonant.extend(res.get("resonant", []))
            for issue in res.get("issues", []):
                key = normalize_label(issue.get("issue", ""))
                if key in by_issue:
                    m = by_issue[key]
                    for field in ("pro", "con", "neutral"):
                        m[field] += issue.get(field, 0)
                    m["quotes"] = _cap(m["quotes"] + issue.get("quotes", []), 5)
                else:
                    by_issue[key] = {
                        "issue": issue.get("issue", ""),
                        "pro": issue.get("pro", 0), "con": issue.get("con", 0),
                        "neutral": issue.get("neutral", 0),
                        "quotes": _cap(issue.get("quotes", []), 5),
                    }
        return {"issues": _cap(list(by_issue.values()), 12), "resonant": _cap(resonant, 10)}

    if kind == "entities":
        by_name: dict[str, dict] = {}
        for res in results:
            for entity in res.get("entities", []):
                key = normalize_label(entity.get("name", ""))
                if key in by_name:
                    m = by_name[key]
                    m["mentions"] += entity.get("mentions", 0)
                    if m["sentiment"] != entity.get("sentiment", "중립"):
                        m["sentiment"] = "mixed"
                    m["reason"] += " / " + entity.get("reason", "")
                else:
                    by_name[key] = dict(entity)
        return {"entities": _cap(
            sorted(by_name.values(), key=lambda e: e["mentions"], reverse=True), 15)}

    if kind == "voices":
        by_text: dict[tuple[str, str], dict] = {}
        for res in results:
            for voice in res.get("voices", []):
                key = (voice.get("kind", ""), normalize_label(voice.get("text", "")))
                if key in by_text:
                    by_text[key]["count"] += 1
                else:
                    item = dict(voice)
                    item["count"] = 1
                    by_text[key] = item
        ordered = sorted(by_text.values(), key=lambda v: v["count"], reverse=True)
        return {"voices": _cap(ordered, 20)}

    raise ValueError(f"unknown kind: {kind}")
