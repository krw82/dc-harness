from __future__ import annotations

from ..models import RawPost


def render_post_text(post: RawPost, max_comments: int = 10) -> str:
    comments = sorted(post.comments, key=lambda c: c.recommend, reverse=True)[:max_comments]
    rendered = " | ".join(f"(추천{c.recommend}) {c.text}" for c in comments)
    return (f"[글#{post.post_no}] {post.title} (추천{post.recommend}) "
            f"{post.body}" + (f" :: 댓글: {rendered}" if rendered else ""))


def chunk_posts(posts: list[RawPost], max_chars: int = 12000) -> list[list[RawPost]]:
    chunks: list[list[RawPost]] = []
    current: list[RawPost] = []
    used = 0
    for post in posts:
        size = len(render_post_text(post))
        if current and used + size > max_chars:
            chunks.append(current)
            current, used = [], 0
        current.append(post)
        used += size
    if current:
        chunks.append(current)
    return chunks
