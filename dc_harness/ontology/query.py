from __future__ import annotations

from datetime import date

from ..models import RawPost
from ..store import Store
from .defn import OntologyDef


def query_objects(store: Store, defn: OntologyDef, api_name: str, gallery_id: str,
                  start: date, end: date, limit: int = 20) -> list[dict]:
    obj = defn.object_(api_name)
    if obj is None:
        raise ValueError(f"unknown object type: {api_name}")
    if not obj.table:
        raise ValueError(f"{api_name}은(는) 질의 미지원: 링크로 탐색하세요")
    if obj.layer == "derived":
        run_id = store.latest_object_run(obj.table, gallery_id, start, end)
        if run_id is None:
            return []
        return store.fetch_object_rows(obj.table, run_id, limit)
    if api_name == "Post":
        posts = store.fetch_posts(gallery_id, start, end)
        return [{"post_no": p.post_no, "title": p.title, "recommend": p.recommend,
                 "views": p.views, "author_hash": p.author,
                 "created_at": p.created_at.isoformat(sep=" ") if p.created_at else None}
                for p in sorted(posts, key=lambda p: p.post_no, reverse=True)[:limit]]
    raise ValueError(f"{api_name}은(는) 질의 미지원: 링크로 탐색하세요")


def show_post(store: Store, gallery_id: str, post_no: int) -> dict:
    posts = [p for p in store.fetch_posts(gallery_id) if p.post_no == post_no]
    if not posts:
        raise ValueError(f"post not found: {gallery_id}/{post_no}")
    post: RawPost = posts[0]
    row = store.conn.execute(
        "SELECT t.label FROM obj_post_topics j JOIN obj_topics t ON j.topic_id=t.topic_id AND j.run_id=t.run_id WHERE j.gallery_id=? AND j.post_no=? AND t.run_id=(SELECT MAX(run_id) FROM obj_topics)",
        (gallery_id, post_no)).fetchall()
    return {"post": post, "topics": [r["label"] for r in row]}


def print_rows(rows: list[dict]) -> str:
    if not rows:
        return "(결과 없음)"
    columns = list(rows[0].keys())
    widths = {c: max(len(str(c)), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    lines = [" | ".join(str(c).ljust(widths[c]) for c in columns)]
    lines.append("-+-".join("-" * widths[c] for c in columns))
    for r in rows:
        lines.append(" | ".join(str(r.get(c, ""))[:60].ljust(widths[c]) for c in columns))
    return "\n".join(lines)
