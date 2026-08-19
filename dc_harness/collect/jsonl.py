from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..models import Comment, RawPost


class JsonlCollector:
    def __init__(self, path: Path):
        self.path = Path(path)

    def read_posts(self) -> list[RawPost]:
        posts: list[RawPost] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            created = None
            if d.get("created_at"):
                try:
                    created = datetime.fromisoformat(str(d["created_at"]))
                except ValueError:
                    created = None
            posts.append(RawPost(
                gallery_id=str(d["gallery_id"]), post_no=int(d["post_no"]),
                title=str(d.get("title", "")), body=str(d.get("body", "")),
                author=str(d.get("author", "")), created_at=created,
                views=int(d.get("views", 0)), recommend=int(d.get("recommend", 0)),
                comments=[Comment(int(d["post_no"]), int(c.get("seq", i)),
                                  str(c.get("text", "")), int(c.get("recommend", 0)),
                                  int(c.get("unrec", 0)))
                          for i, c in enumerate(d.get("comments", []))],
            ))
        return posts
