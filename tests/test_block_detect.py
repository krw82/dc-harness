import pytest

from dc_harness.collect.dcinside import BLOCK_MARKERS, BlockedError, DcInsideCollector
from dc_harness.config import CollectConfig


class FakeResp:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeHttpClient:
    def __init__(self, resp: FakeResp):
        self.resp = resp

    def get(self, url: str) -> FakeResp:
        return self.resp


def make_collector(resp: FakeResp) -> DcInsideCollector:
    cfg = CollectConfig(delay_min_seconds=0, delay_jitter_seconds=0)
    return DcInsideCollector("stock", cfg, client=FakeHttpClient(resp))


REAL_POST_SNIPPET = ('<input type="hidden" id="kcaptcha_use" name="kcaptcha_use" value="N">'
                     + "보안을 위해 2단계 인증을 설정하세요 " * 2000)  # 큰 페이지 + 마커 문구


def test_normal_post_page_with_kcaptcha_not_blocked():
    html = '<html><input id="kcaptcha_use" value="N"></html>' + "x" * 300000
    collector = make_collector(FakeResp(200, html))
    assert collector._get("https://gall.dcinside.com/board/view/?id=stock&no=1") == html


def test_large_page_with_marker_phrase_not_blocked():
    # 본문에 "보안을 위해" 문구가 있어도 정상 대형 페이지는 차단 아님
    collector = make_collector(FakeResp(200, REAL_POST_SNIPPET))
    assert len(collector._get("https://gall.dcinside.com/board/view/?id=stock&no=1")) > 0


def test_small_interstitial_with_marker_blocked():
    html = "<html>보안을 위해 자동 접근이 제한되었습니다</html>"
    collector = make_collector(FakeResp(200, html))
    with pytest.raises(BlockedError):
        collector._get("https://gall.dcinside.com/board/view/?id=stock&no=1")


@pytest.mark.parametrize("status", [403, 429])
def test_status_codes_always_block(status: int):
    collector = make_collector(FakeResp(status, "<html>whatever</html>"))
    with pytest.raises(BlockedError):
        collector._get("https://gall.dcinside.com/board/view/?id=stock&no=1")


def test_block_markers_do_not_include_bare_captcha():
    assert "captcha" not in BLOCK_MARKERS
