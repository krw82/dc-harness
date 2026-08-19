from datetime import datetime, timedelta

from dc_harness.collect.dcinside import ListedPost, archive_range, stale_list_warning


def _post(days_ago: float) -> ListedPost:
    return ListedPost(1, "t", "a", datetime.now() - timedelta(days=days_ago), 0, 0)


def test_mostly_old_posts_notifies():
    listed = [_post(5000)] * 9 + [_post(0)]
    assert "아카이브" in stale_list_warning(listed)


def test_recent_posts_no_warning():
    listed = [_post(0)] * 8 + [_post(3)] * 2
    assert stale_list_warning(listed) is None


def test_undated_posts_ignored():
    listed = [_post(0), ListedPost(2, "t", "a", None, 0, 0)]
    assert stale_list_warning(listed) is None


def test_archive_range_from_title():
    assert archive_range("<title>200702~201109 주식 갤러리 - 디시인사이드</title>") \
        == "200702~201109"
    assert archive_range("<title>프로그래밍 갤러리 - 디시인사이드</title>") is None
