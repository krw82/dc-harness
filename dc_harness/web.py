"""초경량 로컬 웹 뷰어 — 1인용, 읽기 전용. stdlib http.server만 사용.

실행: .venv/bin/dch web   →  http://127.0.0.1:8765
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .store import Store

WEB_DIR = Path(__file__).parent / "web"


def _latest_period(store: Store, gallery_id: str) -> tuple[date, date] | None:
    row = store.conn.execute(
        "SELECT period_start, period_end FROM analyses WHERE gallery_id=? ORDER BY run_id DESC, period_end DESC LIMIT 1",
        (gallery_id,)).fetchone()
    if row is None:
        return None
    return (date.fromisoformat(row["period_start"]),
            date.fromisoformat(row["period_end"]))


def _daily_counts(store: Store, gallery_id: str, start: date, end: date) -> list[dict]:
    rows = store.conn.execute(
        "SELECT date(created_at) AS d, COUNT(*) AS c FROM posts WHERE gallery_id=? AND created_at IS NOT NULL AND date(created_at)>=? AND date(created_at)<=? GROUP BY date(created_at) ORDER BY d",
        (gallery_id, start.isoformat(), end.isoformat())).fetchall()
    by_day = {r["d"]: r["c"] for r in rows}
    days = []
    cur = start
    while cur <= end:
        days.append({"date": cur.isoformat(), "count": by_day.get(cur.isoformat(), 0)})
        cur += timedelta(days=1)
    return days


def api_galleries(store: Store) -> list[dict]:
    rows = store.conn.execute(
        "SELECT gallery_id, COUNT(*) AS posts, MAX(created_at) AS latest FROM posts GROUP BY gallery_id ORDER BY posts DESC").fetchall()
    out = []
    for r in rows:
        period = _latest_period(store, r["gallery_id"])
        out.append({"id": r["gallery_id"], "posts": r["posts"],
                    "latest_post": r["latest"],
                    "measured": period is not None})
    return out


def api_overview(store: Store, gallery_id: str) -> dict:
    period = _latest_period(store, gallery_id)
    if period is None:
        return {"gallery": gallery_id, "measured": False}
    start, end = period
    analyses = store.latest_analyses(gallery_id, start, end)
    posts = store.fetch_posts(gallery_id, start, end)
    run_row = store.conn.execute(
        "SELECT MAX(run_id) AS m FROM analyses WHERE gallery_id=?", (gallery_id,)
    ).fetchone()
    voices = analyses.get("voices", {}).get("voices", [])
    topics = analyses.get("topics", {}).get("topics", [])
    issues = analyses.get("sentiment", {}).get("issues", [])
    entities = analyses.get("entities", {}).get("entities", [])
    return {
        "gallery": gallery_id,
        "measured": True,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "run_id": run_row["m"] if run_row else None,
        "counts": {"posts": len(posts), "topics": len(topics),
                   "issues": len(issues), "entities": len(entities),
                   "voices": len(voices)},
        "activity": _daily_counts(store, gallery_id, start, end),
        "topics": topics,
        "issues": issues,
        "resonant": analyses.get("sentiment", {}).get("resonant", []),
        "entities": entities,
        "voices": voices,
        "top_posts": [{"post_no": p.post_no, "title": p.title,
                       "recommend": p.recommend, "views": p.views}
                      for p in sorted(posts, key=lambda p: p.recommend,
                                      reverse=True)[:10]],
    }


def route(store: Store, path: str, query: str) -> tuple[int, bytes, str]:
    """요청 라우팅 (순수 함수 — 테스트는 소켓 없이 여기만 호출)."""
    if path == "/":
        return 200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8"
    if path == "/api/galleries":
        body = json.dumps(api_galleries(store), ensure_ascii=False).encode("utf-8")
        return 200, body, "application/json; charset=utf-8"
    if path == "/api/overview":
        gallery = (parse_qs(query).get("gallery") or [""])[0]
        if not gallery or not gallery.replace("_", "").isalnum():
            return 400, b"bad gallery", "text/plain; charset=utf-8"
        body = json.dumps(api_overview(store, gallery),
                          ensure_ascii=False).encode("utf-8")
        return 200, body, "application/json; charset=utf-8"
    return 404, b"not found", "text/plain; charset=utf-8"


class ViewerHandler(BaseHTTPRequestHandler):
    store: Store | None = None

    def log_message(self, fmt, *args):  # 콘솔 조용히
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server 규약
        parsed = urlparse(self.path)
        self._send(*route(self.store, parsed.path, parsed.query))


def run_server(db_path: Path, port: int = 8765) -> None:
    handler = type("BoundHandler", (ViewerHandler,), {"store": Store(db_path)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)  # 로컬 전용
    print(f"여론 관측소 가동: http://127.0.0.1:{port}  (종료: Ctrl+C)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")
