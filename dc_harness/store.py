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
"""


class Store:
    """SQLite 저장소. 모든 쿼리는 정적 리터럴 + 파라미터 바인딩만 사용한다."""

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
