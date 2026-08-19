from datetime import datetime
from pathlib import Path

from dc_harness.collect.jsonl import JsonlCollector

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ingest.jsonl"


def test_read_posts_parses_fixture():
    posts = JsonlCollector(FIXTURE).read_posts()
    assert len(posts) == 2
    first = posts[0]
    assert first.gallery_id == "crypto" and first.post_no == 101
    assert first.created_at == datetime(2026, 8, 10, 9, 0, 0)
    assert [c.text for c in first.comments] == ["나는 확신", "무조건 롱"]


def test_invalid_created_at_becomes_none(tmp_path: Path):
    f = tmp_path / "bad.jsonl"
    f.write_text('{"gallery_id":"g","post_no":1,"title":"t","body":"b","author":"a",'
                 '"created_at":"not-a-date","views":0,"recommend":0,"comments":[]}\n')
    posts = JsonlCollector(f).read_posts()
    assert posts[0].created_at is None
