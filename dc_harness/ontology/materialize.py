from __future__ import annotations

import hashlib
import json
from datetime import date

from ..normalize import normalize_label
from ..store import Store


def _hash12(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


def topic_id(gallery_id: str, start: date, end: date, label: str) -> str:
    return _hash12(gallery_id, start.isoformat(), end.isoformat(), normalize_label(label))


def entity_id(name: str) -> str:
    return normalize_label(name)[:40] or "unknown"


def voice_id(kind: str, text: str) -> str:
    return _hash12(kind, normalize_label(text))


def materialize(store: Store, gallery_id: str, run_id: int, prompt_version: str,
                start: date, end: date, results: dict[str, dict]) -> dict[str, int]:
    """병합된 분석 결과를 provenance 있는 파생 객체로 SNAPSHOT 물질화 (I2, I3)."""
    period = {"period_start": start.isoformat(), "period_end": end.isoformat(),
              "gallery_id": gallery_id, "prompt_version": prompt_version}
    counts: dict[str, int] = {}

    topic_rows, junction_rows = [], []
    for t in results.get("topics", {}).get("topics", []):
        tid = topic_id(gallery_id, start, end, t.get("label", ""))
        post_nos = [int(n) for n in t.get("post_nos", []) if str(n).isdigit()]
        topic_rows.append({**period, "topic_id": tid, "label": t.get("label", ""),
                           "snippet": t.get("snippet", ""),
                           "keywords": json.dumps(t.get("keywords", []), ensure_ascii=False),
                           "source_post_nos": json.dumps(post_nos)})
        junction_rows += [{"gallery_id": gallery_id, "post_no": n, "topic_id": tid}
                          for n in post_nos]
    counts["Topic"] = store.snapshot_rows("obj_topics", run_id, topic_rows)
    counts["PostTopic"] = store.snapshot_rows("obj_post_topics", run_id, junction_rows)

    entity_rows = [{**period, "entity_id": entity_id(e.get("name", "")),
                    "display_name": e.get("name", ""), "entity_type": e.get("type", "기타"),
                    "mentions": int(e.get("mentions", 0)),
                    "sentiment": e.get("sentiment", "중립"), "reason": e.get("reason", "")}
                   for e in results.get("entities", {}).get("entities", [])]
    counts["Entity"] = store.snapshot_rows("obj_entities", run_id, entity_rows)

    issue_rows = [{**period, "issue_id": topic_id(gallery_id, start, end,
                                                  i.get("issue", "")),
                   "label": i.get("issue", ""), "pro_count": int(i.get("pro", 0)),
                   "con_count": int(i.get("con", 0)),
                   "neutral_count": int(i.get("neutral", 0)),
                   "quotes": json.dumps(i.get("quotes", []), ensure_ascii=False)}
                  for i in results.get("sentiment", {}).get("issues", [])]
    counts["Issue"] = store.snapshot_rows("obj_issues", run_id, issue_rows)

    voice_rows = [{**period, "voice_id": voice_id(v.get("kind", ""), v.get("text", "")),
                   "kind": v.get("kind", ""), "text": v.get("text", ""),
                   "quote": v.get("quote", ""), "count": int(v.get("count", 1)),
                   "source_post_no": v.get("post_no")}
                  for v in results.get("voices", {}).get("voices", [])]
    counts["Voice"] = store.snapshot_rows("obj_voices", run_id, voice_rows)
    return counts
