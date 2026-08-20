from datetime import datetime

import pytest

from dc_harness.collect.dcinside import BlockedError, DcInsideCollector, ListedPost
from dc_harness.config import CollectConfig


def _listed(n: int) -> ListedPost:
    return ListedPost(post_no=n, title=f"t{n}", author="a",
                      created_at=datetime(2026, 8, 10), views=1, recommend=n)


class FakeCollector(DcInsideCollector):
    """HTTP 없이 collect() 제어 흐름만 검증."""

    def __init__(self, deleted: set[int], blocked: set[int] = frozenset()):
        super().__init__("crypto", CollectConfig(delay_min_seconds=0,
                                                 delay_jitter_seconds=0))
        self.deleted = deleted
        self.blocked = blocked

    def _get(self, url: str) -> str:
        if "no=" in url:
            no = int(url.split("no=")[1])
            if no in self.blocked:
                raise BlockedError("blocked")
            if no in self.deleted:
                raise RuntimeError("404 deleted")
        if "lists" in url:
            return ("<table class='gall_list'><tr class='ub-content'>"
                    "<td class='gall_tit ub-word'><a href='/board/view/?id=crypto&no=1'>t1</a></td>"
                    "<td class='gall_writer'>w</td>"
                    "<td class='gall_date' title='2026-08-10 09:00:00'>d</td>"
                    "<td class='gall_count'>1</td><td class='gall_recommend'>1</td></tr>"
                    "<tr class='ub-content'>"
                    "<td class='gall_tit ub-word'><a href='/board/view/?id=crypto&no=2'>t2</a></td>"
                    "<td class='gall_writer'>w</td>"
                    "<td class='gall_date' title='2026-08-10 10:00:00'>d</td>"
                    "<td class='gall_count'>1</td><td class='gall_recommend'>2</td></tr>"
                    "</table>")
        return ("<div class='view_content_wrap'><span class='nickname'>w</span>"
                "<span class='gall_date' title='2026-08-10 09:00:00'>d</span>"
                "<em>조회 <strong>1</strong></em><em>추천 <strong>9</strong></em>"
                "<h3 class='title_subject'>t</h3>"
                "<div class='write_div'><p>본문</p></div></div>")


def test_collect_skips_deleted_post_and_continues():
    collected = list(FakeCollector(deleted={1}).collect(1, progress=lambda *_: None))
    assert [p.post_no for p in collected] == [2]


def test_collect_still_stops_on_block():
    with pytest.raises(BlockedError):
        list(FakeCollector(deleted=set(), blocked={2}).collect(1, progress=lambda *_: None))


def test_minor_gallery_uses_mgallery_urls():
    seen = []
    list_html = ("<table class='gall_list'><tr class='ub-content'>"
                 "<td class='gall_tit ub-word'><a href='/mgallery/board/view/?id=g&no=1'>t</a></td>"
                 "<td class='gall_writer'>w</td>"
                 "<td class='gall_date' title='2026-08-10 09:00:00'>d</td>"
                 "<td class='gall_count'>1</td><td class='gall_recommend'>1</td></tr>"
                 "</table>")
    post_html = ("<div class='view_content_wrap'><span class='nickname'>w</span>"
                 "<span class='gall_date' title='2026-08-10 09:00:00'>d</span>"
                 "<span class='gall_count'>조회 1</span>"
                 "<span class='gall_reply_num'>추천 1</span>"
                 "<h3 class='title_subject'>t</h3>"
                 "<div class='write_div'><p>본문</p></div></div>")

    class MgallerySpy(DcInsideCollector):
        def _get(self, url: str) -> str:
            seen.append(url)
            assert "mgallery" in url, f"expected mgallery url, got {url}"
            return post_html if "no=" in url else list_html

    posts = list(MgallerySpy("thesingularity",
                             CollectConfig(delay_min_seconds=0, delay_jitter_seconds=0),
                             minor=True).collect(1, progress=lambda *_: None))
    assert len(posts) == 1
    assert any("mgallery/board/lists" in u for u in seen)
    assert any("mgallery/board/view" in u for u in seen)
