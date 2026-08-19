from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from ..store import Store
from .defn import OntologyDef
from .query import query_objects, show_post


@dataclass
class ToolDef:
    name: str
    description: str
    fn: Callable[[dict], object]


def _period(days: int) -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=max(days, 1)), today


def build_tools(store: Store, defn: OntologyDef, gallery_id: str) -> dict[str, ToolDef]:
    def query_objects_tool(args: dict):
        api = str(args.get("apiName", "Topic"))
        start, end = _period(int(args.get("days", 7)))
        return query_objects(store, defn, api, gallery_id, start, end,
                             limit=int(args.get("limit", 10)))

    def get_thread_tool(args: dict):
        detail = show_post(store, gallery_id, int(args["postNo"]))
        return {"postNo": detail["post"].post_no, "title": detail["post"].title,
                "body": detail["post"].body,
                "recommend": detail["post"].recommend,
                "topics": detail["topics"],
                "comments": [{"recommend": c.recommend, "text": c.text}
                             for c in detail["post"].comments[:10]]}

    def stats_tool(args: dict):
        api = str(args.get("apiName", "Topic"))
        start, end = _period(int(args.get("days", 7)))
        rows = query_objects(store, defn, api, gallery_id, start, end, limit=100)
        if api == "Issue":
            return {"count": len(rows),
                    "pro_total": sum(int(r.get("pro_count", 0)) for r in rows),
                    "con_total": sum(int(r.get("con_count", 0)) for r in rows)}
        if api == "Entity":
            return {"count": len(rows), "top_by_mentions": [
                {"name": r["display_name"], "mentions": r["mentions"]} for r in rows[:5]]}
        if api == "Voice":
            kinds: dict[str, int] = {}
            for r in rows:
                kinds[r["kind"]] = kinds.get(r["kind"], 0) + int(r.get("count", 1))
            return {"count": len(rows), "by_kind": kinds}
        return {"count": len(rows)}

    return {
        "queryObjects": ToolDef(
            "queryObjects",
            "apiName(Topic|Entity|Issue|Voice|Post)와 days·limit를 받아 해당 기간"
            " 최신 분석 객체 목록을 JSON 배열로 반환한다", query_objects_tool),
        "getThread": ToolDef(
            "getThread", "postNo를 받아 게시글 제목·본문·댓글·연결 토픽을 JSON로 반환한다",
            get_thread_tool),
        "stats": ToolDef(
            "stats", "apiName과 days를 받아 개수·주요 집계를 JSON로 반환한다", stats_tool),
    }
