from datetime import datetime

from dc_harness.collect.dcinside import fetch_comments, parse_post_page

# 실제 DC 뷰 페이지 구조 발췌 (2026-08-19 /board/view 확인분)
REAL_VIEW = """
<html><body>
<span class="nickname in-game-tel" title="우주방어">우주방어(IP차단)</span>
<span class="gall_date" title="2008-11-06 18:20:03">08.11.06</span>
<div class="fr">
  <span class="gall_scrap"><button class="sp_scrap viewscrap">스크랩</button></span>
  <span class="gall_count">조회 172067</span>
  <span class="gall_reply_num">추천 15</span>
</div>
<h3 class="title_subject">주식 갤러리 용어 길라잡이</h3>
<div class="write_div"><p>본문 내용</p></div>
</body></html>
"""


def test_parse_post_page_real_markup_stats():
    detail = parse_post_page(REAL_VIEW, 1)
    assert detail.title == "주식 갤러리 용어 길라잡이"
    assert detail.author.startswith("우주방어")
    assert detail.created_at == datetime(2008, 11, 6, 18, 20, 3)
    assert detail.views == 172067 and detail.recommend == 15
    assert "본문 내용" in detail.body


class _FakeResp:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text

    def json(self):
        import json
        return json.loads(self.text)


class _FakeClient:
    def __init__(self, resp: _FakeResp):
        self.resp = resp
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.resp


def test_fetch_comments_parses_json():
    payload = ('{"total_cnt": 2, "comments": {'
               '"0": {"name": "가", "memo": "첫 댓글", "recommend": "12"},'
               '"1": {"name": "나", "memo": "둘", "recommend": 3}}}')
    client = _FakeClient(_FakeResp(200, payload))
    comments = fetch_comments(client, "stock", 101, "esno", 1)
    assert [(c.text, c.recommend) for c in comments] == [("첫 댓글", 12), ("둘", 3)]


def test_fetch_comments_denied_returns_empty():
    client = _FakeClient(_FakeResp(200, "정상적인 접근이 아닙니다."))
    assert fetch_comments(client, "stock", 101, "esno", 1) == []


def test_fetch_comments_http_error_returns_empty():
    client = _FakeClient(_FakeResp(404, "nope"))
    assert fetch_comments(client, "stock", 101, "esno", 1) == []
