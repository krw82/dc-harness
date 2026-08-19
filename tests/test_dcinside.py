from datetime import datetime
from pathlib import Path

from dc_harness.collect.dcinside import parse_list_page, parse_post_page

FIX = Path(__file__).parent / "fixtures" / "dc"


def test_parse_list_page():
    items = parse_list_page((FIX / "list_page.html").read_text(encoding="utf-8"))
    assert [i.post_no for i in items] == [101, 102]
    assert items[0].title == "[국내] 비트코인 전망"
    assert items[0].author == "양추가"
    assert items[0].created_at == datetime(2026, 8, 10, 9, 0, 0)
    assert items[0].views == 300 and items[0].recommend == 45


def test_parse_list_page_ignores_notices_without_no():
    html = '<tr class="ub-content"><td class="gall_tit ub-word">'
    html += '<a href="/board/view/?id=crypto">공지</a></td></tr>'
    assert parse_list_page(html) == []


def test_parse_post_page():
    detail = parse_post_page((FIX / "post_page.html").read_text(encoding="utf-8"), 101)
    assert detail.title == "[국내] 비트코인 전망"
    assert "커핑 시즌" in detail.body and "롱" in detail.body
    assert detail.views == 300 and detail.recommend == 45
    assert [(c.text, c.recommend) for c in detail.comments] == [("나는 확신", 12), ("무조건 롱", 5)]
