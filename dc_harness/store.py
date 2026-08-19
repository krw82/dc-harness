from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import Comment, RawPost

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts(
  gallery_id TEXT NOT NULL, post_no INTEGER NOT NULL,
  title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  author_hash TEXT NOT NULL DEFAULT '', created_at TEXT,
  views INTEGER NOT NULL DEFAULT 0, recommend INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(gallery_id, post_no));
CREATE TABLE IF NOT EXISTS comments(
  gallery_id TEXT NOT NULL, post_no INTEGER NOT NULL, seq INTEGER NOT NULL,
  text TEXT NOT NULL, recommend INTEGER NOT NULL DEFAULT 0,
  unrec INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(gallery_id, post_no, seq));
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, gallery_id TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL DEFAULT 'running',
  stats TEXT);
CREATE TABLE IF NOT EXISTS analyses(
  run_id INTEGER NOT NULL, kind TEXT NOT NULL, gallery_id TEXT NOT NULL,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL, result TEXT NOT NULL,
  PRIMARY KEY(run_id, kind));
CREATE TABLE IF NOT EXISTS llm_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, kind TEXT NOT NULL,
  system_text TEXT NOT NULL, user_text TEXT NOT NULL, response_text TEXT NOT NULL,
  model TEXT NOT NULL, prompt_version TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS obj_topics(
  run_id INTEGER NOT NULL, gallery_id TEXT NOT NULL, topic_id TEXT NOT NULL,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL, label TEXT NOT NULL,
  snippet TEXT NOT NULL DEFAULT '', keywords TEXT NOT NULL DEFAULT '[]',
  source_post_nos TEXT NOT NULL DEFAULT '[]', prompt_version TEXT NOT NULL,
  PRIMARY KEY(run_id, topic_id));
CREATE TABLE IF NOT EXISTS obj_entities(
  run_id INTEGER NOT NULL, gallery_id TEXT NOT NULL, entity_id TEXT NOT NULL,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL, display_name TEXT NOT NULL,
  entity_type TEXT NOT NULL DEFAULT '기타', mentions INTEGER NOT NULL DEFAULT 0,
  sentiment TEXT NOT NULL DEFAULT '중립', reason TEXT NOT NULL DEFAULT '',
  prompt_version TEXT NOT NULL, PRIMARY KEY(run_id, entity_id));
CREATE TABLE IF NOT EXISTS obj_issues(
  run_id INTEGER NOT NULL, gallery_id TEXT NOT NULL, issue_id TEXT NOT NULL,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL, label TEXT NOT NULL,
  pro_count INTEGER NOT NULL DEFAULT 0, con_count INTEGER NOT NULL DEFAULT 0,
  neutral_count INTEGER NOT NULL DEFAULT 0, quotes TEXT NOT NULL DEFAULT '[]',
  prompt_version TEXT NOT NULL, PRIMARY KEY(run_id, issue_id));
CREATE TABLE IF NOT EXISTS obj_voices(
  run_id INTEGER NOT NULL, gallery_id TEXT NOT NULL, voice_id TEXT NOT NULL,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL, kind TEXT NOT NULL,
  text TEXT NOT NULL, quote TEXT NOT NULL DEFAULT '', count INTEGER NOT NULL DEFAULT 1,
  source_post_no INTEGER, prompt_version TEXT NOT NULL,
  PRIMARY KEY(run_id, voice_id));
CREATE TABLE IF NOT EXISTS obj_post_topics(
  run_id INTEGER NOT NULL, gallery_id TEXT NOT NULL, post_no INTEGER NOT NULL,
  topic_id TEXT NOT NULL, PRIMARY KEY(run_id, gallery_id, post_no, topic_id));
"""


# --- 파생 객체(온톨로지) 계층: 테이블별 함수, execute 호출점은 정적 리터럴만 사용 (I2). ---

def _snapshot_obj_topics(conn: sqlite3.Connection, run_id: int, rows: list[dict]) -> int:
    conn.execute("DELETE FROM obj_topics WHERE run_id=?", (run_id,))
    for r in rows:
        conn.execute(
            "INSERT INTO obj_topics(run_id, gallery_id, topic_id, period_start, period_end, label, snippet, keywords, source_post_nos, prompt_version) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (run_id, r.get("gallery_id"), r.get("topic_id"), r.get("period_start"),
             r.get("period_end"), r.get("label"), r.get("snippet"), r.get("keywords"),
             r.get("source_post_nos"), r.get("prompt_version")))
    return len(rows)


def _snapshot_obj_entities(conn: sqlite3.Connection, run_id: int, rows: list[dict]) -> int:
    conn.execute("DELETE FROM obj_entities WHERE run_id=?", (run_id,))
    for r in rows:
        conn.execute(
            "INSERT INTO obj_entities(run_id, gallery_id, entity_id, period_start, period_end, display_name, entity_type, mentions, sentiment, reason, prompt_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, r.get("gallery_id"), r.get("entity_id"), r.get("period_start"),
             r.get("period_end"), r.get("display_name"), r.get("entity_type"),
             r.get("mentions"), r.get("sentiment"), r.get("reason"),
             r.get("prompt_version")))
    return len(rows)


def _snapshot_obj_issues(conn: sqlite3.Connection, run_id: int, rows: list[dict]) -> int:
    conn.execute("DELETE FROM obj_issues WHERE run_id=?", (run_id,))
    for r in rows:
        conn.execute(
            "INSERT INTO obj_issues(run_id, gallery_id, issue_id, period_start, period_end, label, pro_count, con_count, neutral_count, quotes, prompt_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, r.get("gallery_id"), r.get("issue_id"), r.get("period_start"),
             r.get("period_end"), r.get("label"), r.get("pro_count"),
             r.get("con_count"), r.get("neutral_count"), r.get("quotes"),
             r.get("prompt_version")))
    return len(rows)


def _snapshot_obj_voices(conn: sqlite3.Connection, run_id: int, rows: list[dict]) -> int:
    conn.execute("DELETE FROM obj_voices WHERE run_id=?", (run_id,))
    for r in rows:
        conn.execute(
            "INSERT INTO obj_voices(run_id, gallery_id, voice_id, period_start, period_end, kind, text, quote, count, source_post_no, prompt_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, r.get("gallery_id"), r.get("voice_id"), r.get("period_start"),
             r.get("period_end"), r.get("kind"), r.get("text"), r.get("quote"),
             r.get("count"), r.get("source_post_no"), r.get("prompt_version")))
    return len(rows)


def _snapshot_obj_post_topics(conn: sqlite3.Connection, run_id: int,
                              rows: list[dict]) -> int:
    conn.execute("DELETE FROM obj_post_topics WHERE run_id=?", (run_id,))
    for r in rows:
        conn.execute(
            "INSERT INTO obj_post_topics(run_id, gallery_id, post_no, topic_id) VALUES(?,?,?,?)",
            (run_id, r.get("gallery_id"), r.get("post_no"), r.get("topic_id")))
    return len(rows)


_SNAPSHOTTERS = {
    "obj_topics": _snapshot_obj_topics,
    "obj_entities": _snapshot_obj_entities,
    "obj_issues": _snapshot_obj_issues,
    "obj_voices": _snapshot_obj_voices,
    "obj_post_topics": _snapshot_obj_post_topics,
}


def _latest_run_obj_topics(conn: sqlite3.Connection, gallery_id: str,
                           start: date, end: date) -> int | None:
    row = conn.execute(
        "SELECT MAX(run_id) AS m FROM obj_topics WHERE gallery_id=? AND period_start=? AND period_end=?",
        (gallery_id, start.isoformat(), end.isoformat())).fetchone()
    return row["m"] if row and row["m"] is not None else None


def _latest_run_obj_entities(conn: sqlite3.Connection, gallery_id: str,
                             start: date, end: date) -> int | None:
    row = conn.execute(
        "SELECT MAX(run_id) AS m FROM obj_entities WHERE gallery_id=? AND period_start=? AND period_end=?",
        (gallery_id, start.isoformat(), end.isoformat())).fetchone()
    return row["m"] if row and row["m"] is not None else None


def _latest_run_obj_issues(conn: sqlite3.Connection, gallery_id: str,
                           start: date, end: date) -> int | None:
    row = conn.execute(
        "SELECT MAX(run_id) AS m FROM obj_issues WHERE gallery_id=? AND period_start=? AND period_end=?",
        (gallery_id, start.isoformat(), end.isoformat())).fetchone()
    return row["m"] if row and row["m"] is not None else None


def _latest_run_obj_voices(conn: sqlite3.Connection, gallery_id: str,
                           start: date, end: date) -> int | None:
    row = conn.execute(
        "SELECT MAX(run_id) AS m FROM obj_voices WHERE gallery_id=? AND period_start=? AND period_end=?",
        (gallery_id, start.isoformat(), end.isoformat())).fetchone()
    return row["m"] if row and row["m"] is not None else None


_LATEST_RUNNERS = {
    "obj_topics": _latest_run_obj_topics,
    "obj_entities": _latest_run_obj_entities,
    "obj_issues": _latest_run_obj_issues,
    "obj_voices": _latest_run_obj_voices,
}


def _fetch_obj_topics(conn: sqlite3.Connection, run_id: int, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM obj_topics WHERE run_id=? LIMIT ?", (run_id, limit)).fetchall()
    return [dict(r) for r in rows]


def _fetch_obj_entities(conn: sqlite3.Connection, run_id: int, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM obj_entities WHERE run_id=? LIMIT ?", (run_id, limit)).fetchall()
    return [dict(r) for r in rows]


def _fetch_obj_issues(conn: sqlite3.Connection, run_id: int, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM obj_issues WHERE run_id=? LIMIT ?", (run_id, limit)).fetchall()
    return [dict(r) for r in rows]


def _fetch_obj_voices(conn: sqlite3.Connection, run_id: int, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM obj_voices WHERE run_id=? LIMIT ?", (run_id, limit)).fetchall()
    return [dict(r) for r in rows]


def _fetch_obj_post_topics(conn: sqlite3.Connection, run_id: int, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM obj_post_topics WHERE run_id=? LIMIT ?", (run_id, limit)).fetchall()
    return [dict(r) for r in rows]


_FETCHERS = {
    "obj_topics": _fetch_obj_topics,
    "obj_entities": _fetch_obj_entities,
    "obj_issues": _fetch_obj_issues,
    "obj_voices": _fetch_obj_voices,
    "obj_post_topics": _fetch_obj_post_topics,
}


class Store:
    """SQLite 저장소. 모든 쿼리는 execute 호출점의 정적 리터럴 + 파라미터 바인딩."""

    OBJECT_TABLES = frozenset(_SNAPSHOTTERS)

    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.conn.close()

    def upsert_post(self, post: RawPost) -> None:
        self.conn.execute(
            "INSERT INTO posts(gallery_id, post_no, title, body, author_hash, created_at, views, recommend) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(gallery_id, post_no) DO UPDATE SET title=excluded.title, body=excluded.body, author_hash=excluded.author_hash, created_at=excluded.created_at, views=excluded.views, recommend=excluded.recommend",
            (post.gallery_id, post.post_no, post.title, post.body, post.author,
             post.created_at.isoformat(sep=" ") if post.created_at else None,
             post.views, post.recommend),
        )
        self.conn.commit()

    def replace_comments(self, gallery_id: str, post_no: int, comments: list[Comment]) -> None:
        self.conn.execute(
            "DELETE FROM comments WHERE gallery_id=? AND post_no=?",
            (gallery_id, post_no),
        )
        self.conn.executemany(
            "INSERT INTO comments(gallery_id, post_no, seq, text, recommend, unrec) VALUES(?,?,?,?,?,?)",
            [(gallery_id, post_no, c.seq, c.text, c.recommend, c.unrec) for c in comments],
        )
        self.conn.commit()

    @staticmethod
    def _to_post(row: sqlite3.Row, comments: list[Comment]) -> RawPost:
        created = datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
        return RawPost(
            gallery_id=row["gallery_id"], post_no=row["post_no"], title=row["title"],
            body=row["body"], author=row["author_hash"], created_at=created,
            views=row["views"], recommend=row["recommend"], comments=comments,
        )

    def _rows_to_posts(self, rows: list[sqlite3.Row]) -> list[RawPost]:
        result: list[RawPost] = []
        for row in rows:
            crows = self.conn.execute(
                "SELECT * FROM comments WHERE gallery_id=? AND post_no=? ORDER BY seq",
                (row["gallery_id"], row["post_no"]),
            ).fetchall()
            comments = [Comment(r["post_no"], r["seq"], r["text"], r["recommend"], r["unrec"])
                        for r in crows]
            result.append(self._to_post(row, comments))
        return result

    def fetch_posts(self, gallery_id: str, start: date | None = None,
                    end: date | None = None) -> list[RawPost]:
        start_iso = start.isoformat() if start is not None else None
        end_iso = end.isoformat() if end is not None else None
        rows = self.conn.execute(
            "SELECT * FROM posts WHERE gallery_id=? AND (? IS NULL OR date(created_at)>=?) AND (? IS NULL OR date(created_at)<=?) ORDER BY post_no",
            (gallery_id, start_iso, start_iso, end_iso, end_iso),
        ).fetchall()
        return self._rows_to_posts(rows)

    def top_posts(self, gallery_id: str, start: date | None, end: date | None,
                  limit: int = 10) -> list[RawPost]:
        posts = self.fetch_posts(gallery_id, start, end)
        return sorted(posts, key=lambda p: p.recommend, reverse=True)[:limit]

    def start_run(self, gallery_id: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs(gallery_id, started_at) VALUES(?,?)",
            (gallery_id, datetime.now().isoformat(sep=" ")),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, stats: dict) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, status=?, stats=? WHERE id=?",
            (datetime.now().isoformat(sep=" "), status,
             json.dumps(stats, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    def save_analysis(self, run_id: int, kind: str, gallery_id: str,
                      start: date, end: date, result: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO analyses(run_id, kind, gallery_id, period_start, period_end, result) VALUES(?,?,?,?,?,?)",
            (run_id, kind, gallery_id, start.isoformat(), end.isoformat(),
             json.dumps(result, ensure_ascii=False)),
        )
        self.conn.commit()

    def latest_analyses(self, gallery_id: str, start: date, end: date) -> dict[str, dict]:
        rows = self.conn.execute(
            "SELECT a.kind, a.result FROM analyses a JOIN runs r ON a.run_id=r.id WHERE a.gallery_id=? AND a.period_start=? AND a.period_end=? AND r.id=(SELECT MAX(a2.run_id) FROM analyses a2 WHERE a2.kind=a.kind AND a2.gallery_id=a.gallery_id AND a2.period_start=a.period_start AND a2.period_end=a.period_end)",
            (gallery_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        return {row["kind"]: json.loads(row["result"]) for row in rows}

    def log_llm_call(self, run_id: int | None, kind: str, system: str, user: str,
                     response: str, model: str, prompt_version: str) -> None:
        self.conn.execute(
            "INSERT INTO llm_calls(run_id, kind, system_text, user_text, response_text, model, prompt_version) VALUES(?,?,?,?,?,?,?)",
            (run_id, kind, system, user, response, model, prompt_version))
        self.conn.commit()

    def snapshot_rows(self, table: str, run_id: int, rows: list[dict]) -> int:
        """run 단위 SNAPSHOT: 해당 run 기존 행 삭제 후 재작성 (I2)."""
        fn = _SNAPSHOTTERS.get(table)
        if fn is None:
            raise ValueError(f"not an object table: {table}")
        written = fn(self.conn, run_id, rows)
        self.conn.commit()
        return written

    def latest_object_run(self, table: str, gallery_id: str,
                          start: date, end: date) -> int | None:
        fn = _LATEST_RUNNERS.get(table)
        if fn is None:
            raise ValueError(f"not an object table: {table}")
        return fn(self.conn, gallery_id, start, end)

    def fetch_object_rows(self, table: str, run_id: int, limit: int = 50) -> list[dict]:
        fn = _FETCHERS.get(table)
        if fn is None:
            raise ValueError(f"not an object table: {table}")
        return fn(self.conn, run_id, limit)
