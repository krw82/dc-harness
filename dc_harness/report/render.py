from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..models import RawPost

_KIND_TITLES = {"topics": "토픽", "sentiment": "여론", "entities": "엔티티 여론",
                "voices": "VOC (불만·바람·아이디어)", "trends": "트렌드"}


def _section_topics(data: dict) -> list[str]:
    lines = ["| 토픽 | 키워드 | 근거 글 |", "|---|---|---|"]
    for t in data.get("topics", []):
        lines.append(f"| {t.get('label', '')} | {', '.join(t.get('keywords', []))} "
                     f"| {', '.join(f'#{n}' for n in t.get('post_nos', [])[:5])} |")
    return lines


def _section_sentiment(data: dict) -> list[str]:
    lines = []
    for issue in data.get("issues", []):
        total = max(issue.get("pro", 0) + issue.get("con", 0) + issue.get("neutral", 0), 1)
        lines.append(f"- **{issue.get('issue', '')}** — 찬성 {issue.get('pro', 0)} / "
                     f"반대 {issue.get('con', 0)} / 중립 {issue.get('neutral', 0)} "
                     f"(총 {total}발언)")
        for quote in issue.get("quotes", [])[:3]:
            lines.append(f"  - ({quote.get('stance', '?')}, 글#{quote.get('post_no')}) "
                         f"{quote.get('text', '')}")
    if data.get("resonant"):
        lines.append("")
        lines.append("**공감을 얻은 반응 (추천수 기반):**")
        for r in data["resonant"]:
            lines.append(f"- (글#{r.get('post_no')}) {r.get('text', '')} — {r.get('why', '')}")
    return lines


def _section_entities(data: dict) -> list[str]:
    lines = ["| 대상 | 유형 | 언급 | 여론 | 이유 |", "|---|---|---|---|---|"]
    for e in data.get("entities", []):
        lines.append(f"| {e.get('name', '')} | {e.get('type', '')} | {e.get('mentions', 0)} "
                     f"| {e.get('sentiment', '')} | {e.get('reason', '')} |")
    return lines


def _section_voices(data: dict) -> list[str]:
    lines = []
    kind_labels = {"painpoint": "불만", "wish": "바람", "idea": "아이디어"}
    for v in data.get("voices", []):
        lines.append(f"- [{kind_labels.get(v.get('kind'), v.get('kind'))}] "
                     f"{v.get('text', '')} (×{v.get('count', 1)}, "
                     f"글#{v.get('post_no')}) — \"{v.get('quote', '')}\"")
    return lines


def _section_trends(data: dict) -> list[str]:
    lines = []
    for item in data.get("rising", []):
        lines.append(f"- 🔺 {item.get('label', '')}: {item.get('reason', '')}")
    for item in data.get("falling", []):
        lines.append(f"- 🔻 {item.get('label', '')}: {item.get('reason', '')}")
    for shift in data.get("shifts", []):
        lines.append(f"- 🔁 {shift.get('label', '')}: {shift.get('from')} → {shift.get('to')}")
    if data.get("summary"):
        lines.append("")
        lines.append(f"> {data['summary']}")
    return lines


_RENDERERS = {"topics": _section_topics, "sentiment": _section_sentiment,
              "entities": _section_entities, "voices": _section_voices,
              "trends": _section_trends}


def render_report(gallery_id: str, start: date, end: date, analyses: dict[str, dict],
                  top: list[RawPost], coverage: dict) -> tuple[str, dict]:
    md = [f"# DC Inside `{gallery_id}` 갤러리 여론 리포트",
          f"기간: {start} ~ {end}", ""]
    if "topics" in analyses:
        first = analyses["topics"].get("topics", [])
        md += ["## 요약", ""]
        md += [f"- 상위 토픽: {', '.join(t.get('label', '') for t in first[:5]) or '없음'}", ""]
    for kind, title in _KIND_TITLES.items():
        if kind not in analyses:
            continue
        md.append(f"## {title}")
        md.append("")
        md += _RENDERERS[kind](analyses[kind]) or ["(데이터 없음)"]
        md.append("")
    if top:
        md += ["## 인기 게시글", "", "| 추천 | 제목 | 글 번호 |", "|---|---|---|"]
        for post in top:
            md.append(f"| {post.recommend} | {post.title} | #{post.post_no} |")
        md.append("")
    md += ["## 커버리지", ""]
    if coverage:
        for key in ("posts_included", "posts_total", "chunks_total", "chunks_failed"):
            md.append(f"- {key}: {coverage.get(key, 0)}")
        if coverage.get("chunks_failed"):
            md.append("- 주의: 일부 LLM 청크가 실패해 결과가 부분적일 수 있음")
    payload = {"gallery_id": gallery_id,
               "period": {"start": start.isoformat(), "end": end.isoformat()},
               "analyses": analyses,
               "top_posts": [{"post_no": p.post_no, "title": p.title,
                              "recommend": p.recommend} for p in top],
               "coverage": coverage}
    return "\n".join(md), payload


def save_report(out_dir: Path, gallery_id: str, start: date, end: date,
                markdown: str, payload: dict) -> Path:
    target_dir = Path(out_dir) / gallery_id
    target_dir.mkdir(parents=True, exist_ok=True)
    base = target_dir / f"{start.isoformat()}~{end.isoformat()}"
    base.with_suffix(".md").write_text(markdown + "\n", encoding="utf-8")
    base.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return base.with_suffix(".md")
