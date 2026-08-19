from __future__ import annotations

import random
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import CollectConfig
from ..models import Comment, RawPost
from ..net.guard import DC_HOSTS, UnsafeUrlError, validate_http_url
from ..normalize import clean_text

LIST_URL = "https://gall.dcinside.com/board/lists/?id={gallery_id}&page={page}"
POST_URL = "https://gall.dcinside.com/board/view/?id={gallery_id}&no={post_no}"
COMMENT_URL = "https://gall.dcinside.com/board/comment/"

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
# 차단 인터스티셜은 작은 페이지에만 판정 — 정상 게시글 페이지(수백 KB)에는
# 댓글 폼의 kcaptcha 히든 인풋이 항상 있으므로 bare "captcha"는 오탐.
BLOCK_MARKERS = ("자동 접근", "보안을 위해")
_BLOCK_PAGE_MAX_CHARS = 20000
_ESNO_RE = re.compile(r'name="e_s_n_o"[^>]*value="([^"]+)"')


class BlockedError(RuntimeError):
    """DC 차단/캡차 페이지 감지."""


@dataclass
class ListedPost:
    post_no: int
    title: str
    author: str
    created_at: datetime | None
    views: int
    recommend: int


@dataclass
class PostDetail:
    title: str
    body: str
    author: str
    created_at: datetime | None
    views: int
    recommend: int
    comments: list[Comment]


def _int(text: str | None) -> int:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else 0


def _parse_date(tag) -> datetime | None:
    if tag is None:
        return None
    m = _DATE_RE.search(tag.get("title", "") or "")
    if not m:
        return None
    return datetime.strptime(m.group(0), "%Y-%m-%d %H:%M:%S")


def parse_list_page(html: str) -> list[ListedPost]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[ListedPost] = []
    for tr in soup.select("tr.ub-content"):
        link = tr.select_one(".gall_tit a")
        if link is None or not link.get("href"):
            continue
        qs = parse_qs(urlparse(link["href"]).query)
        if "no" not in qs or not qs["no"][0].isdigit():
            continue
        writer = tr.select_one(".gall_writer")
        count = tr.select_one(".gall_count")
        rec = tr.select_one(".gall_recommend")
        items.append(ListedPost(
            post_no=int(qs["no"][0]),
            title=clean_text(link.get_text()),
            author=clean_text(writer.get_text()) if writer else "",
            created_at=_parse_date(tr.select_one(".gall_date")),
            views=_int(count.get_text()) if count else 0,
            recommend=_int(rec.get_text()) if rec else 0,
        ))
    return items


def _stat_value(tag) -> int:
    """'조회 172067' 형태 스팬에서 숫자 추출 (실제 뷰 페이지 통계 마크업)."""
    if tag is None:
        return 0
    return _int(re.sub(r"^[가-힣]+\s*", "", tag.get_text()))


def parse_post_page(html: str, post_no: int) -> PostDetail:
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one(".title_subject")
    body_tag = soup.select_one(".write_div") or soup.select_one(".view_content_wrap")
    comments: list[Comment] = []
    for seq, li in enumerate(soup.select("ul.comment_ul li.ub-content")):
        rec_tag = li.select_one(".cmt_info strong")
        usertxt = li.select_one(".usertxt")
        comments.append(Comment(
            post_no=post_no, seq=seq,
            text=clean_text(usertxt.get_text()) if usertxt else "",
            recommend=_int(rec_tag.get_text()) if rec_tag else 0,
        ))
    strongs = [s.get_text() for s in soup.select("em strong")]
    nickname = soup.select_one(".nickname")
    # 실측 마크업: <span class="gall_count">조회 N</span> / <span class="gall_reply_num">추천 N</span>
    views = _int(strongs[0] if len(strongs) > 0 else "") \
        or _stat_value(soup.select_one(".gall_count"))
    recommend = _int(strongs[1] if len(strongs) > 1 else "") \
        or _stat_value(soup.select_one(".gall_reply_num"))
    return PostDetail(
        title=clean_text(title_tag.get_text()) if title_tag else "",
        body=clean_text(body_tag.get_text()) if body_tag else "",
        author=clean_text(nickname.get_text()) if nickname else "",
        created_at=_parse_date(soup.select_one(".gall_date")),
        views=views,
        recommend=recommend,
        comments=comments,
    )


def fetch_comments(client, gallery_id: str, post_no: int, e_s_n_o: str,
                   cmt_page: int = 1) -> list[Comment]:
    """댓글 AJAX 조회. JS 생성 쿠키가 없으면 DC가 거부('정상적인 접근이 아닙니다')하는데,
    이때는 빈 리스트로 우아히 저하한다(게시글 수집은 유지). 쿠키는 DC_COOKIES env로 제공."""
    try:
        resp = client.post(
            COMMENT_URL,
            headers={"X-Requested-With": "XMLHttpRequest",
                     "Referer": POST_URL.format(gallery_id=gallery_id, post_no=post_no)},
            data={"id": gallery_id, "no": str(post_no), "cmt_gno": "0",
                  "cmt_comment": "0", "cmt_page": str(cmt_page),
                  "e_s_n_o": e_s_n_o, "_GALLTYPE_": "G"})
        if resp.status_code != 200 or len(resp.text) < 30:
            return []
        data = resp.json()
        raw = data.get("comments") or {}
        items = list(raw.values()) if isinstance(raw, dict) else list(raw)
        result: list[Comment] = []
        for seq, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            text = clean_text(str(item.get("memo") or item.get("comment") or ""))
            if not text:
                continue
            result.append(Comment(post_no=post_no, seq=seq, text=text,
                                  recommend=_int(str(item.get("recommend", "") or ""))))
        return result
    except Exception:
        return []


class DcInsideCollector:
    def __init__(self, gallery_id: str, cfg: CollectConfig, cookies: str | None = None,
                 client: httpx.Client | None = None):
        self.gallery_id = gallery_id
        self.cfg = cfg
        headers = {"User-Agent": cfg.user_agent}
        if cookies:
            headers["Cookie"] = cookies
        self.client = client or httpx.Client(headers=headers, timeout=30.0,
                                             follow_redirects=True)

    def _polite_sleep(self) -> None:
        time.sleep(self.cfg.delay_min_seconds
                   + random.uniform(0, self.cfg.delay_jitter_seconds))

    def _get(self, url: str) -> str:
        validate_http_url(url, DC_HOSTS)  # http/https + DC allowlist (사설 IP 불가)
        last_exc: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            try:
                resp = self.client.get(url)
                marker_hit = (len(resp.text) < _BLOCK_PAGE_MAX_CHARS
                              and any(m in resp.text for m in BLOCK_MARKERS))
                if resp.status_code in (403, 429) or marker_hit:
                    raise BlockedError(
                        f"blocked by dcinside: {url} (status={resp.status_code})")
                resp.raise_for_status()
                self._polite_sleep()
                return resp.text
            except BlockedError:
                raise
            except (httpx.HTTPError, UnsafeUrlError) as exc:
                last_exc = exc
                time.sleep(2 ** attempt)
        raise RuntimeError(f"failed after retries: {url}: {last_exc}")

    def collect(self, pages: int, progress=print) -> Iterator[RawPost]:
        for page in range(1, pages + 1):
            html = self._get(LIST_URL.format(gallery_id=self.gallery_id, page=page))
            listed = parse_list_page(html)
            progress(f"page {page}: {len(listed)} posts")
            for item in listed:
                try:
                    post_html = self._get(
                        POST_URL.format(gallery_id=self.gallery_id, post_no=item.post_no))
                except BlockedError:
                    raise  # 차단은 즉시 정지
                except RuntimeError as exc:
                    # 삭제된 글(404) 등: 해당 글만 건너뛰고 계속
                    progress(f"skip post {item.post_no}: {exc}")
                    continue
                detail = parse_post_page(post_html, item.post_no)
                esno = _ESNO_RE.search(post_html)
                if esno:
                    self._polite_sleep()
                    detail.comments = (
                        fetch_comments(self.client, self.gallery_id,
                                       item.post_no, esno.group(1))
                        or detail.comments)
                yield RawPost(
                    gallery_id=self.gallery_id, post_no=item.post_no,
                    title=detail.title or item.title, body=detail.body,
                    author=detail.author or item.author,
                    created_at=detail.created_at or item.created_at,
                    views=detail.views or item.views,
                    recommend=detail.recommend or item.recommend,
                    comments=detail.comments,
                )
