from __future__ import annotations

import json
import re

from ..llm.client import LlmClient
from ..store import Store
from .defn import OntologyDef
from .tools import build_tools

_CITATION = re.compile(r"글#\d+")
_NUMERIC_ONLY = re.compile(r"^[\d\s,]+$")


def enrich_numeric_answer(store: Store, gallery_id: str, answer: str) -> str:
    """모델이 글 번호만 나열로 답한 경우(12.7B 실측 패턴), 온톨로지에서 토픽 라벨을
    조회해 인용 포함 문장으로 합성한다."""
    if not _NUMERIC_ONLY.match(answer.strip()) or not answer.strip():
        return answer
    post_nos = [int(n) for n in re.findall(r"\d+", answer)][:8]
    parts = []
    for no in post_nos:
        row = store.conn.execute(
            "SELECT t.label FROM obj_post_topics j JOIN obj_topics t ON j.topic_id=t.topic_id AND j.run_id=t.run_id WHERE j.gallery_id=? AND j.post_no=? AND t.run_id=(SELECT MAX(run_id) FROM obj_topics)",
            (gallery_id, no)).fetchone()
        if row:
            parts.append(f"{row['label']} [글#{no}]")
    if not parts:
        return answer + "\n(해당 글과 연결된 토픽 없음 — krw-ontology-dc show로 직접 확인 권장)"
    return "질문과 관련된 주제: " + ", ".join(parts)


def ontology_summary(defn: OntologyDef) -> str:
    lines = ["=== 온톨로지 객체 ==="]
    for o in defn.objects:
        lines.append(f"- {o.apiName} ({o.displayName}): {o.description}"
                     f" [pk={','.join(o.pk)}, layer={o.layer}]")
    lines.append("=== 링크 ===")
    for link in defn.links:
        lines.append(f"- {link.fromObject} --{link.apiName}({link.displayName}, "
                     f"{link.cardinality})--> {link.toObject}"
                     + (f" via {link.via}" if link.via else ""))
    return "\n".join(lines)


def ask(store: Store, defn: OntologyDef, llm: LlmClient, gallery_id: str,
        question: str, max_steps: int = 6) -> str:
    """읽기 전용 도구 루프로 온톨로지를 질의한다. 인용 없는 답은 1회 재요청 후 표기."""
    tools = build_tools(store, defn, gallery_id)
    run_id = store.start_run(gallery_id)
    system = (
        ontology_summary(defn)
        + "\n\n=== 사용 가능 도구 ===\n"
        + "\n".join(f"- {t.name}: {t.description}" for t in tools.values())
        + '\n\n=== 출력 형식 (반드시 정확히 지킬 것) ===\n'
        '도구 호출: {"tool": "queryObjects", "args": {"apiName": "Topic", "days": 7}}\n'
        '최종 답변: {"answer": "한국어 문장으로 설명. 근거 글 번호를 [글#101] 형태로 반드시 포함."}\n'
        "예시: {\"answer\": \"최근 관심 주제는 현물 매수와 채굴 단가입니다. 근거: [글#101], [글#102]\"}\n"
        "금지: 숫자만 나열, 배열 출력, JSON 외 텍스트. 답은 반드시 위 두 형식 중 하나다."
    )
    transcript = f"질문: {question}"
    answer = ""
    retried = False
    for _step in range(max_steps):
        result = llm.chat_json(system, transcript)
        if isinstance(result, list):
            # 모델이 {"answer": ...} 대신 배열을 바로 반환하는 경우(실측) — 답 후보로 흡수
            result = {"answer": ", ".join(str(x) for x in result)}
        store.log_llm_call(run_id, "ask", system, transcript,
                           json.dumps(result, ensure_ascii=False),
                           getattr(llm, "model", "unknown"), "ask-v2")
        if "tool" in result:
            tool = tools.get(result["tool"])
            if tool is None:
                output = {"error": f"unknown tool: {result['tool']}"}
            else:
                try:
                    output = tool.fn(result.get("args", {}))
                except Exception as exc:  # 도구 실패는 루프 중단 아님
                    output = {"error": str(exc)}
            transcript += (f"\n\n[도구 결과: {result['tool']}]\n"
                           + json.dumps(output, ensure_ascii=False, default=str)[:4000])
            continue
        answer = str(result.get("answer", ""))
        if _CITATION.search(answer) or retried:
            break
        retried = True
        transcript += ("\n\n[시스템] 답변에 [글#번호] 형태의 근거 인용이 없다. "
                       "도구로 근거를 확인한 뒤 인용을 포함해 다시 답하라.")
    store.finish_run(run_id, "done", {"question": question})
    if answer and not _CITATION.search(answer):
        if _NUMERIC_ONLY.match(answer.strip()):
            answer = enrich_numeric_answer(store, gallery_id, answer)
        if not _CITATION.search(answer):
            answer += "\n(근거 인용 없음 — 도구 결과를 직접 확인 권장)"
    return answer or "(최대 스텝 초과 — 질문을 좁혀서 다시)"
