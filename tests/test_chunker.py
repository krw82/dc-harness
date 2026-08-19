from datetime import datetime

from dc_harness.llm.chunker import chunk_posts, render_post_text
from dc_harness.models import Comment, RawPost


def post(no: int, body: str = "x" * 200) -> RawPost:
    return RawPost("crypto", no, f"t{no}", body, "a", datetime(2026, 8, 10), 1, 2,
                   [Comment(no, 0, "c0", 5), Comment(no, 1, "c1")])


def test_render_post_text_includes_ref_and_top_comments():
    text = render_post_text(post(1), max_comments=1)
    assert "[글#1]" in text and "t1" in text and "c0" in text and "c1" not in text


def test_chunk_posts_respects_budget():
    posts = [post(i) for i in range(1, 6)]  # 각 ~220자
    chunks = chunk_posts(posts, max_chars=500)
    assert len(chunks) >= 2
    assert sum(len(c) for c in chunks) == 5
    for chunk in chunks:
        assert sum(len(render_post_text(p)) for p in chunk) <= 500 + 250  # 한 글 초과 허용


def test_oversized_single_post_still_included():
    big = post(9, body="y" * 3000)
    chunks = chunk_posts([big], max_chars=500)
    assert len(chunks) == 1 and chunks[0] == [big]
