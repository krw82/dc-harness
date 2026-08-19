from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Comment:
    post_no: int
    seq: int
    text: str
    recommend: int = 0
    unrec: int = 0


@dataclass
class RawPost:
    gallery_id: str
    post_no: int
    title: str
    body: str
    author: str
    created_at: datetime | None
    views: int
    recommend: int
    comments: list[Comment] = field(default_factory=list)
