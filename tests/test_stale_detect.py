from datetime import datetime, timedelta

from dc_harness.collect.dcinside import ListedPost, stale_list_warning


def _post(days_ago: float) -> ListedPost:
    return ListedPost(1, "t", "a", datetime.now() - timedelta(days=days_ago), 0, 0)


def test_mostly_old_posts_warns():
    listed = [_post(5000)] * 9 + [_post(0)]
    assert "DC_COOKIES" in stale_list_warning(listed)


def test_recent_posts_no_warning():
    listed = [_post(0)] * 8 + [_post(3)] * 2
    assert stale_list_warning(listed) is None


def test_undated_posts_ignored():
    listed = [_post(0), ListedPost(2, "t", "a", None, 0, 0)]
    assert stale_list_warning(listed) is None
