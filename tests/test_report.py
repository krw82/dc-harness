from datetime import date, datetime
from pathlib import Path

from dc_harness.models import RawPost
from dc_harness.report.render import render_report, save_report

ANALYSES = {
    "topics": {"topics": [{"label": "현물 매수", "post_nos": [101],
                           "keywords": ["매수", "저가"], "snippet": "지금이 기회"}]},
    "sentiment": {"issues": [{"issue": "반감기", "pro": 4, "con": 2, "neutral": 1,
                              "quotes": []}],
                  "resonant": [{"post_no": 101, "text": "현물이 답", "why": "손실 공포"}]},
    "entities": {"entities": [{"name": "이더리움", "type": "종목", "mentions": 9,
                               "sentiment": "부정", "reason": "수수료 불만"}]},
    "voices": {"voices": [{"kind": "painpoint", "text": "앱이 느림", "post_no": 1,
                           "quote": "앱이 너무 느림", "count": 3}]},
    "trends": {"rising": [{"label": "현물", "reason": "급증"}], "falling": [],
               "shifts": [], "summary": "현물로 이동"},
}
TOP = [RawPost("crypto", 101, "현물이 답이다", "본문", "a", datetime(2026, 8, 10), 300, 45)]


def test_render_report_sections():
    md, payload = render_report("crypto", date(2026, 8, 1), date(2026, 8, 7),
                                ANALYSES, TOP, {"chunks_total": 4, "chunks_failed": 1,
                                                "posts_included": 30, "posts_total": 30})
    for header in ("## 요약", "## 토픽", "## 여론", "## 엔티티 여론",
                   "## VOC (불만·바람·아이디어)", "## 트렌드", "## 인기 게시글", "## 커버리지"):
        assert header in md
    assert "현물 매수" in md and "이더리움" in md and "앱이 느림" in md
    assert payload["analyses"] == ANALYSES
    assert "chunks_failed: 1" in md


def test_render_report_skips_missing_sections():
    md, _ = render_report("crypto", date(2026, 8, 1), date(2026, 8, 7),
                          {"topics": ANALYSES["topics"]}, [], {})
    assert "## 토픽" in md and "## 여론" not in md


def test_save_report_writes_md_and_json(tmp_path: Path):
    md, payload = render_report("crypto", date(2026, 8, 1), date(2026, 8, 7),
                                ANALYSES, TOP, {})
    out = save_report(tmp_path, "crypto", date(2026, 8, 1), date(2026, 8, 7), md, payload)
    assert out.exists() and out.with_suffix(".json").exists()
    assert out.parent.name == "crypto"
