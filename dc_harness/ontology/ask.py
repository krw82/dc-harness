from __future__ import annotations

import json
import re

from ..llm.client import LlmClient
from ..store import Store
from .defn import OntologyDef
from .tools import build_tools

_CITATION = re.compile(r"글#\d+")


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
        + '\n\n규칙: 도구가 필요하면 {"tool": 이름, "args": {...}} JSON만 출력한다.'
        ' 도구 결과를 보고 충분하면 {"answer": "..."} JSON으로 최종 답변한다.'
        " 답변은 한국어, 모든 주장에 [글#번호] 인용을 포함한다."
        " 원본 데이터 전체를 요구하지 말고 도구 결과만 사용한다."
    )
    transcript = f"질문: {question}"
    answer = ""
    retried = False
    for _step in range(max_steps):
        result = llm.chat_json(system, transcript)
        store.log_llm_call(run_id, "ask", system, transcript,
                           json.dumps(result, ensure_ascii=False),
                           getattr(llm, "model", "unknown"), "ask-v1")
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
        answer += "\n(근거 인용 없음 — 도구 결과를 직접 확인 권장)"
    return answer or "(최대 스텝 초과 — 질문을 좁혀서 다시)"
