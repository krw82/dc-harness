# DC Inside 여론 분석 하네스 (dc-harness) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DC Inside 갤러리의 게시글·댓글·추천수를 수집·저장하고, OpenAI 호환 LLM으로 토픽/여론/트렌드/엔티티/VOC를 분석해 Markdown+JSON 리포트를 내주는 CLI 하네스.

**Architecture:** `collectors → SQLite store → analyzers(LLM map-reduce) → reports` 파이프라인을 하나의 Python 패키지(`dc_harness`)로 구현. 모든 스테이지는 upsert로 멱등하고, 스크래퍼는 HTML fixture 기반 파서 + 파일(JSONL) 인제스트 탈출구를 갖는다.

**Tech Stack:** Python 3.11+, `openai`, `httpx`, `beautifulsoup4`, stdlib `sqlite3`/`argparse`. 테스트 `pytest`.

**Spec:** `docs/superpowers/specs/2026-08-19-dc-inside-opinion-harness-design.md`

> **Phase 2 (온톨로지 계층):** `docs/superpowers/plans/2026-08-19-ontology-layer.md` — 본 계획의 `Analyzer.run`은 Phase 2 연계를 위해 `run_id`를 함께 반환하도록 아래에 반영되어 있다. 나머지 태스크는 무손상.

## Global Constraints

- Python >= 3.11. 런타임 의존은 `openai`, `httpx`, `beautifulsoup4`만 허용.
- API 키는 **환경 변수에서만** 읽는다(기본 `MOTIF_API_KEY`, config의 `api_key_env`로 변경 가능). 소스/테스트/예제에 사용 가능한 키 리터럴 금지.
- 모든 아웃바운드 HTTP 요청 전 `dc_harness.net.guard.validate_http_url` 통과: http/https만, DC 수집은 호스트 allowlist(`gall.dcinside.com`, `m.dcinside.com`, `www.dcinside.com`), 그 외 URL(LLM base_url 등)은 루프백/사설/예약 IP 거부.
- 수집 요청 간 기본 딜레이 `delay_min_seconds=1.5` + 지터 `delay_jitter_seconds=0.5` (429/캡차 감지 시 `BlockedError`로 즉시 정지).
- 모든 쓰기 스테이지는 멱등: posts는 `(gallery_id, post_no)` upsert, comments는 delete+insert.
- 리포트에 개인 식별 정보 미포함. 작성자 닉네임은 `author_hash()`로 해시해 저장.
- 리포트 문구는 한국어, 코드 식별자/커밋 메시지는 영어.
- 각 태스크는 TDD: 실패 테스트 → 구현 → 통과 → 커밋.

---

### Task 1: 프로젝트 스캐폴드 + config 로더

**Files:**
- Create: `pyproject.toml`, `dc_harness/__init__.py`, `dc_harness/config.py`, `config.example.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass dc_harness.config.LlmConfig(base_url: str, model: str, api_key_env: str, temperature: float = 0.3, timeout: float = 60.0)`
  - `@dataclass dc_harness.config.CollectConfig(delay_min_seconds: float = 1.5, delay_jitter_seconds: float = 0.5, max_retries: int = 3, user_agent: str, cookies_env: str = "DC_COOKIES")`
  - `@dataclass dc_harness.config.Config(llm: LlmConfig, collect: CollectConfig, privacy_salt: str = "dch-salt")`
  - `load_config(path: Path | None = None) -> Config` — path가 None이거나 없으면 기본값, 있으면 TOML 병합.
  - `resolve_api_key(cfg: Config) -> str` — `os.environ[cfg.llm.api_key_env]`, 없으면 `KeyError` 메시지에 env 이름 명시.

- [ ] **Step 1: `pyproject.toml` 작성**

```toml
[project]
name = "dc-harness"
version = "0.1.0"
description = "Research harness for DC Inside gallery opinion analysis"
requires-python = ">=3.11"
dependencies = ["openai>=1.40", "httpx>=0.27", "beautifulsoup4>=4.12"]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.5"]

[project.scripts]
dch = "dc_harness.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["dc_harness"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 2: `dc_harness/__init__.py` 작성**

```python
"""dc-harness: DC Inside gallery opinion research harness."""
```

- [ ] **Step 3: 실패 테스트 작성 `tests/test_config.py`**

```python
from pathlib import Path

import pytest

from dc_harness.config import Config, load_config, resolve_api_key


def test_default_config_when_no_file(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.toml")
    assert isinstance(cfg, Config)
    assert cfg.llm.base_url == "https://chat.motiftech.io/openapi/v1"
    assert cfg.llm.model == "motif-12.7b-reasoning"
    assert cfg.llm.api_key_env == "MOTIF_API_KEY"
    assert cfg.collect.delay_min_seconds == 1.5


def test_toml_overrides_defaults(tmp_path: Path):
    f = tmp_path / "config.toml"
    f.write_text(
        '[llm]\nbase_url = "https://example.test/v1"\nmodel = "m1"\n'
        '[collect]\ndelay_min_seconds = 3.0\n'
    )
    cfg = load_config(f)
    assert cfg.llm.base_url == "https://example.test/v1"
    assert cfg.llm.model == "m1"
    assert cfg.collect.delay_min_seconds == 3.0
    assert cfg.llm.api_key_env == "MOTIF_API_KEY"  # 병합: 기본값 유지


def test_resolve_api_key_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOTIF_API_KEY", "test-key-not-real")
    assert resolve_api_key(load_config(None)) == "test-key-not-real"


def test_resolve_api_key_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MOTIF_API_KEY", raising=False)
    with pytest.raises(KeyError, match="MOTIF_API_KEY"):
        resolve_api_key(load_config(None))
```

- [ ] **Step 4: 테스트 실패 확인**

Run: `pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: dc_harness.config`)

- [ ] **Step 5: `dc_harness/config.py` 구현**

```python
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LlmConfig:
    base_url: str = "https://chat.motiftech.io/openapi/v1"
    model: str = "motif-12.7b-reasoning"
    api_key_env: str = "MOTIF_API_KEY"
    temperature: float = 0.3
    timeout: float = 60.0


@dataclass
class CollectConfig:
    delay_min_seconds: float = 1.5
    delay_jitter_seconds: float = 0.5
    max_retries: int = 3
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
    cookies_env: str = "DC_COOKIES"


@dataclass
class Config:
    llm: LlmConfig = field(default_factory=LlmConfig)
    collect: CollectConfig = field(default_factory=CollectConfig)
    privacy_salt: str = "dch-salt"


def load_config(path: Path | None = None) -> Config:
    cfg = Config()
    if path is None or not Path(path).exists():
        return cfg
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    for section, target in (("llm", cfg.llm), ("collect", cfg.collect)):
        for key, value in data.get(section, {}).items():
            if hasattr(target, key):
                setattr(target, key, value)
    cfg.privacy_salt = data.get("privacy_salt", cfg.privacy_salt)
    return cfg


def resolve_api_key(cfg: Config) -> str:
    env = cfg.llm.api_key_env
    try:
        return os.environ[env]
    except KeyError as exc:
        raise KeyError(f"API key not found: set {env} environment variable") from exc
```

- [ ] **Step 6: `config.example.toml` 작성**

```toml
# Copy to config.toml and edit. API key는 항상 환경 변수로 제공(소스에 금지).
[llm]
base_url = "https://chat.motiftech.io/openapi/v1"
model = "motif-12.7b-reasoning"
api_key_env = "MOTIF_API_KEY"

[collect]
delay_min_seconds = 1.5
delay_jitter_seconds = 0.5
# DC_COOKIES env: "name1=val1; name2=val2" 형식으로 제공하면 요청에 포함
```

- [ ] **Step 7: 테스트 통과 확인 후 커밋**

Run: `pytest tests/test_config.py -v` → PASS

```bash
git add pyproject.toml dc_harness/ config.example.toml tests/test_config.py
git commit -m "feat: project scaffold with config loader"
```

---

### Task 2: 데이터 모델 + SQLite 스토어

**Files:**
- Create: `dc_harness/models.py`, `dc_harness/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: 없음 (첫 의존성 없는 레이어)
- Produces:
  - `@dataclass dc_harness.models.Comment(post_no: int, seq: int, text: str, recommend: int = 0, unrec: int = 0)`
  - `@dataclass dc_harness.models.RawPost(gallery_id: str, post_no: int, title: str, body: str, author: str, created_at: datetime | None, views: int, recommend: int, comments: list[Comment] = field(default_factory=list))`
  - `dc_harness.store.Store(db_path: Path)` — 컨텍스트 매니저. 메서드:
    - `upsert_post(post: RawPost) -> None`
    - `replace_comments(gallery_id: str, post_no: int, comments: list[Comment]) -> None`
    - `fetch_posts(gallery_id: str, start: date | None = None, end: date | None = None) -> list[RawPost]`
    - `top_posts(gallery_id: str, start: date | None, end: date | None, limit: int = 10) -> list[RawPost]` — recommend 내림차순
    - `start_run(gallery_id: str) -> int`, `finish_run(run_id: int, status: str, stats: dict) -> None`
    - `save_analysis(run_id: int, kind: str, gallery_id: str, start: date, end: date, result: dict) -> None`
    - `latest_analyses(gallery_id: str, start: date, end: date) -> dict[str, dict]`

- [ ] **Step 1: 실패 테스트 `tests/test_store.py`**

```python
from datetime import date, datetime
from pathlib import Path

from dc_harness.models import Comment, RawPost
from dc_harness.store import Store


def make_post(post_no: int, rec: int = 0, day: str = "2026-08-10") -> RawPost:
    return RawPost(
        gallery_id="crypto", post_no=post_no, title=f"title {post_no}",
        body=f"body {post_no}", author="nick", created_at=datetime.fromisoformat(day + " 12:00:00"),
        views=100, recommend=rec,
        comments=[Comment(post_no=post_no, seq=0, text="comment text", recommend=3)],
    )


def test_upsert_is_idempotent(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.upsert_post(make_post(1, rec=5))
        p = make_post(1, rec=9)  # 재수집: 추천수 갱신
        p.comments = []
        store.upsert_post(p)
        posts = store.fetch_posts("crypto")
        assert len(posts) == 1
        assert posts[0].recommend == 9


def test_replace_comments(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.upsert_post(make_post(1))
        store.replace_comments("crypto", 1, [Comment(1, 0, "a", 1), Comment(1, 1, "b", 2)])
        store.replace_comments("crypto", 1, [Comment(1, 0, "c", 7)])
        posts = store.fetch_posts("crypto")
        assert [c.text for c in posts[0].comments] == ["c"]


def test_fetch_posts_filters_by_period(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.upsert_post(make_post(1, day="2026-08-01"))
        store.upsert_post(make_post(2, day="2026-08-10"))
        got = store.fetch_posts("crypto", start=date(2026, 8, 5), end=date(2026, 8, 15))
        assert [p.post_no for p in got] == [2]


def test_top_posts_orders_by_recommend(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        for no, rec in [(1, 3), (2, 30), (3, 10)]:
            store.upsert_post(make_post(no, rec=rec))
        assert [p.post_no for p in store.top_posts("crypto", None, None)] == [2, 3, 1]


def test_runs_and_analyses_roundtrip(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        run_id = store.start_run("crypto")
        store.save_analysis(run_id, "topics", "crypto", date(2026, 8, 1), date(2026, 8, 7), {"topics": []})
        store.finish_run(run_id, "done", {"posts": 1})
        got = store.latest_analyses("crypto", date(2026, 8, 1), date(2026, 8, 7))
        assert got["topics"] == {"topics": []}
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_store.py -v` → FAIL (`No module named dc_harness.store`)

- [ ] **Step 3: `dc_harness/models.py` 구현**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Comment:
    post_no: int
    seq: int
    text: str
    recommend: int = 0
    unrec: int = 0


@dataclass
class RawPost:
    gallery_id: str
    post_no: int
    title: str
    body: str
    author: str
    created_at: datetime | None
    views: int
    recommend: int
    comments: list[Comment] = field(default_factory=list)
```

- [ ] **Step 4: `dc_harness/store.py` 구현**

```python
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import Comment, RawPost

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts(
  gallery_id TEXT NOT NULL, post_no INTEGER NOT NULL,
  title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  author_hash TEXT NOT NULL DEFAULT '', created_at TEXT,
  views INTEGER NOT NULL DEFAULT 0, recommend INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(gallery_id, post_no));
CREATE TABLE IF NOT EXISTS comments(
  gallery_id TEXT NOT NULL, post_no INTEGER NOT NULL, seq INTEGER NOT NULL,
  text TEXT NOT NULL, recommend INTEGER NOT NULL DEFAULT 0,
  unrec INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(gallery_id, post_no, seq));
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, gallery_id TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL DEFAULT 'running',
  stats TEXT);
CREATE TABLE IF NOT EXISTS analyses(
  run_id INTEGER NOT NULL, kind TEXT NOT NULL, gallery_id TEXT NOT NULL,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL, result TEXT NOT NULL,
  PRIMARY KEY(run_id, kind));
"""


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.conn.close()

    def upsert_post(self, post: RawPost) -> None:
        self.conn.execute(
            "INSERT INTO posts(gallery_id, post_no, title, body, author_hash, created_at,"
            " views, recommend) VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(gallery_id, post_no) DO UPDATE SET"
            " title=excluded.title, body=excluded.body, author_hash=excluded.author_hash,"
            " created_at=excluded.created_at, views=excluded.views, recommend=excluded.recommend",
            (post.gallery_id, post.post_no, post.title, post.body, post.author,
             post.created_at.isoformat(sep=" ") if post.created_at else None,
             post.views, post.recommend),
        )
        self.conn.commit()

    def replace_comments(self, gallery_id: str, post_no: int, comments: list[Comment]) -> None:
        self.conn.execute(
            "DELETE FROM comments WHERE gallery_id=? AND post_no=?", (gallery_id, post_no))
        self.conn.executemany(
            "INSERT INTO comments(gallery_id, post_no, seq, text, recommend, unrec)"
            " VALUES(?,?,?,?,?,?)",
            [(gallery_id, post_no, c.seq, c.text, c.recommend, c.unrec) for c in comments],
        )
        self.conn.commit()

    @staticmethod
    def _to_post(row: sqlite3.Row, comments: list[Comment]) -> RawPost:
        created = datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
        return RawPost(
            gallery_id=row["gallery_id"], post_no=row["post_no"], title=row["title"],
            body=row["body"], author=row["author_hash"], created_at=created,
            views=row["views"], recommend=row["recommend"], comments=comments,
        )

    def _rows_to_posts(self, rows: list[sqlite3.Row]) -> list[RawPost]:
        result: list[RawPost] = []
        for row in rows:
            crows = self.conn.execute(
                "SELECT * FROM comments WHERE gallery_id=? AND post_no=? ORDER BY seq",
                (row["gallery_id"], row["post_no"]),
            ).fetchall()
            comments = [Comment(r["post_no"], r["seq"], r["text"], r["recommend"], r["unrec"])
                        for r in crows]
            result.append(self._to_post(row, comments))
        return result

    def fetch_posts(self, gallery_id: str, start: date | None = None,
                    end: date | None = None) -> list[RawPost]:
        sql, params = "SELECT * FROM posts WHERE gallery_id=?", [gallery_id]
        if start is not None:
            sql += " AND date(created_at)>=?"
            params.append(start.isoformat())
        if end is not None:
            sql += " AND date(created_at)<=?"
            params.append(end.isoformat())
        sql += " ORDER BY post_no"
        return self._rows_to_posts(self.conn.execute(sql, params).fetchall())

    def top_posts(self, gallery_id: str, start: date | None, end: date | None,
                  limit: int = 10) -> list[RawPost]:
        posts = self.fetch_posts(gallery_id, start, end)
        return sorted(posts, key=lambda p: p.recommend, reverse=True)[:limit]

    def start_run(self, gallery_id: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs(gallery_id, started_at) VALUES(?,?)",
            (gallery_id, datetime.now().isoformat(sep=" ")),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, stats: dict) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, status=?, stats=? WHERE id=?",
            (datetime.now().isoformat(sep=" "), status, json.dumps(stats, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    def save_analysis(self, run_id: int, kind: str, gallery_id: str,
                      start: date, end: date, result: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO analyses(run_id, kind, gallery_id, period_start,"
            " period_end, result) VALUES(?,?,?,?,?,?)",
            (run_id, kind, gallery_id, start.isoformat(), end.isoformat(),
             json.dumps(result, ensure_ascii=False)),
        )
        self.conn.commit()

    def latest_analyses(self, gallery_id: str, start: date, end: date) -> dict[str, dict]:
        rows = self.conn.execute(
            "SELECT a.kind, a.result FROM analyses a JOIN runs r ON a.run_id=r.id"
            " WHERE a.gallery_id=? AND a.period_start=? AND a.period_end=?"
            " AND r.id=(SELECT MAX(a2.run_id) FROM analyses a2 WHERE a2.kind=a.kind"
            "  AND a2.gallery_id=a.gallery_id AND a2.period_start=a.period_start"
            "  AND a2.period_end=a.period_end)",
            (gallery_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        return {row["kind"]: json.loads(row["result"]) for row in rows}
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `pytest tests/test_store.py -v` → PASS

```bash
git add dc_harness/models.py dc_harness/store.py tests/test_store.py
git commit -m "feat: data models and idempotent sqlite store"
```

---

### Task 3: 정규화 + 작성자 해시

**Files:**
- Create: `dc_harness/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `Config.privacy_salt`
- Produces:
  - `clean_text(html: str) -> str` — 태그 제거, 엔티티 복원, 공백 정리
  - `author_hash(nick: str, salt: str) -> str` — sha256 12자리
  - `normalize_label(s: str) -> str` — 대소문자·공백 무시 비교용 키 (한글 그대로 유지, 제어문자 제거)

- [ ] **Step 1: 실패 테스트 `tests/test_normalize.py`**

```python
from dc_harness.normalize import author_hash, clean_text, normalize_label


def test_clean_text_strips_tags_and_entities():
    assert clean_text("<p>가격 &amp; 전망</p>\n\n  뿌우  ") == "가격 & 전망 뿌우"


def test_clean_text_removes_dc_noise():
    assert "??" not in clean_text("본문??\u200b제로폭")  # 제로폭/비표시 제거
    assert clean_text("<b>제목</b>") == "제목"


def test_author_hash_stable_and_salted():
    a = author_hash("닉네임", "salt1")
    b = author_hash("닉네임", "salt2")
    assert a != b and len(a) == 12


def test_normalize_label_for_dedupe():
    assert normalize_label("  Bitcoin ") == normalize_label("bitcoin")
    assert normalize_label("비트코인") == "비트코인"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_normalize.py -v` → FAIL

- [ ] **Step 3: `dc_harness/normalize.py` 구현**

```python
from __future__ import annotations

import hashlib
import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    text = _TAG_RE.sub(" ", html.unescape(raw or ""))
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return _WS_RE.sub(" ", text).strip()


def author_hash(nick: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}\x00{nick}".encode("utf-8")).hexdigest()[:12]


def normalize_label(s: str) -> str:
    return re.sub(r"[\s\u200b]+", "", (s or "")).casefold()
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/test_normalize.py -v` → PASS

```bash
git add dc_harness/normalize.py tests/test_normalize.py
git commit -m "feat: text normalization and author hashing"
```

---

### Task 4: 네트워크 가드 (SSRF/allowlist)

**Files:**
- Create: `dc_harness/net/__init__.py`, `dc_harness/net/guard.py`
- Test: `tests/test_net_guard.py`

**Interfaces:**
- Produces:
  - `DC_HOSTS = frozenset({"gall.dcinside.com", "m.dcinside.com", "www.dcinside.com"})`
  - `class UnsafeUrlError(ValueError)`
  - `validate_http_url(url: str, allowed_hosts: frozenset[str] | None = None) -> str` — http/https만, allowed_hosts 있으면 그 중 하나여야 함, 없으면 resolve해서 루프백/사설/예약 IP 거부. 검증된 URL 반환.
  - `host_is_public(host: str) -> bool`

- [ ] **Step 1: 실패 테스트 `tests/test_net_guard.py`**

```python
import pytest

from dc_harness.net.guard import DC_HOSTS, UnsafeUrlError, host_is_public, validate_http_url


def test_allows_dc_hosts():
    assert validate_http_url("https://gall.dcinside.com/board/lists/?id=crypto", DC_HOSTS)


def test_rejects_non_allowlisted_host_for_dc():
    with pytest.raises(UnsafeUrlError):
        validate_http_url("https://evil.example.com/lists?id=crypto", DC_HOSTS)


@pytest.mark.parametrize("scheme", ["file", "ftp", "javascript"])
def test_rejects_non_http_schemes(scheme: str):
    with pytest.raises(UnsafeUrlError):
        validate_http_url(f"{scheme}://gall.dcinside.com/x", DC_HOSTS)


def test_rejects_private_or_loopback_when_no_allowlist():
    with pytest.raises(UnsafeUrlError):
        validate_http_url("http://127.0.0.1:8080/api")
    with pytest.raises(UnsafeUrlError):
        validate_http_url("http://192.168.1.5/api")


def test_host_is_public():
    assert host_is_public("example.com") is True
    assert host_is_public("127.0.0.1") is False
    assert host_is_public("10.0.0.1") is False
```

주의: `host_is_public("example.com")`은 실제 DNS 조회를 하므로 테스트는 오프라인에서도 통과해야 한다 — 도메인이 아니라 IP 리터럴만 조회하고, 도메인은 조회 실패 시 **fail-open하지 않고** 통과시키지 않는다. 대신: 도메인은 allowlist/설정된 base_url로만 호출되므로 `host_is_public`의 DNS 조회는 LLM base_url 검증에만 쓰며, 조회 실패 시 `UnsafeUrlError`를 낸다. 테스트의 `example.com` 케이스는 DNS가 있어야 하므로 아래처럼 IP 리터럴 중심으로 바꿔 쓴다:

```python
def test_host_is_public_ip_literals():
    assert host_is_public("93.184.216.34") is True
    assert host_is_public("127.0.0.1") is False
    assert host_is_public("10.0.0.1") is False
    assert host_is_public("169.254.1.1") is False
```

(`host_is_public("example.com")` 단언은 최종 테스트에서 제외)

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_net_guard.py -v` → FAIL

- [ ] **Step 3: `dc_harness/net/guard.py` 구현**

```python
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

DC_HOSTS = frozenset({"gall.dcinside.com", "m.dcinside.com", "www.dcinside.com"})


class UnsafeUrlError(ValueError):
    pass


def host_is_public(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
        return not (addr.is_private or addr.is_loopback or addr.is_reserved
                    or addr.is_link_local or addr.is_multicast or addr.is_unspecified)
    except ValueError:
        pass  # 도메인 이름: DNS 조회로 검증
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise UnsafeUrlError(f"cannot resolve host: {host}") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if addr.is_private or addr.is_loopback or addr.is_reserved \
                or addr.is_link_local or addr.is_multicast or addr.is_unspecified:
            return False
    return True


def validate_http_url(url: str, allowed_hosts: frozenset[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"scheme not allowed: {parsed.scheme!r} in {url}")
    host = parsed.hostname or ""
    if not host:
        raise UnsafeUrlError(f"missing host: {url}")
    if allowed_hosts is not None:
        if host not in allowed_hosts:
            raise UnsafeUrlError(f"host not in allowlist: {host}")
    elif not host_is_public(host):
        raise UnsafeUrlError(f"host is not public: {host}")
    return url
```

`dc_harness/net/__init__.py`는 빈 파일.

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/test_net_guard.py -v` → PASS

```bash
git add dc_harness/net/ tests/test_net_guard.py
git commit -m "feat: url guard with dc host allowlist and private-address rejection"
```

---

### Task 5: JSONL 인제스트 콜렉터

**Files:**
- Create: `dc_harness/collect/__init__.py`, `dc_harness/collect/jsonl.py`
- Test: `tests/test_jsonl_collector.py`, fixture `tests/fixtures/sample_ingest.jsonl`

**Interfaces:**
- Consumes: `RawPost`, `Comment`
- Produces: `class JsonlCollector(path: Path)` with `read_posts() -> list[RawPost]` — JSONL 각 줄은 `{"gallery_id","post_no","title","body","author","created_at"(ISO),"views","recommend","comments":[{"seq","text","recommend","unrec"}]}`. `created_at` 파싱 실패 시 `None`.

- [ ] **Step 1: fixture `tests/fixtures/sample_ingest.jsonl` 작성**

```jsonl
{"gallery_id":"crypto","post_no":101,"title":"비트코인 전망","body":"커핑 시즌 어떻게 보심","author":"양추가","created_at":"2026-08-10T09:00:00","views":300,"recommend":45,"comments":[{"seq":0,"text":"나는 확신","recommend":12},{"seq":1,"text":"무조건 롱","recommend":5}]}
{"gallery_id":"crypto","post_no":102,"title":"채굴 단가","body":"전기세 아끼는 법","author":"마이너","created_at":"2026-08-11T10:00:00","views":80,"recommend":3,"comments":[]}
```

- [ ] **Step 2: 실패 테스트 `tests/test_jsonl_collector.py`**

```python
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
```

- [ ] **Step 3: 실패 확인 후 `dc_harness/collect/jsonl.py` 구현**

Run: `pytest tests/test_jsonl_collector.py -v` → FAIL 후:

```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..models import Comment, RawPost


class JsonlCollector:
    def __init__(self, path: Path):
        self.path = Path(path)

    def read_posts(self) -> list[RawPost]:
        posts: list[RawPost] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            created = None
            if d.get("created_at"):
                try:
                    created = datetime.fromisoformat(str(d["created_at"]))
                except ValueError:
                    created = None
            posts.append(RawPost(
                gallery_id=str(d["gallery_id"]), post_no=int(d["post_no"]),
                title=str(d.get("title", "")), body=str(d.get("body", "")),
                author=str(d.get("author", "")), created_at=created,
                views=int(d.get("views", 0)), recommend=int(d.get("recommend", 0)),
                comments=[Comment(int(d["post_no"]), int(c.get("seq", i)),
                                  str(c.get("text", "")), int(c.get("recommend", 0)),
                                  int(c.get("unrec", 0)))
                          for i, c in enumerate(d.get("comments", []))],
            ))
        return posts
```

`dc_harness/collect/__init__.py`는 빈 파일.

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/test_jsonl_collector.py -v` → PASS

```bash
git add dc_harness/collect/ tests/test_jsonl_collector.py tests/fixtures/sample_ingest.jsonl
git commit -m "feat: jsonl ingest collector"
```

---

### Task 6: DC Inside 스크래퍼 (fixture 기반 파서 + 예의적 fetcher)

**Files:**
- Create: `dc_harness/collect/dcinside.py`
- Test: `tests/test_dcinside.py`, fixtures `tests/fixtures/dc/list_page.html`, `tests/fixtures/dc/post_page.html`

**Interfaces:**
- Consumes: `CollectConfig`, `DC_HOSTS`, `validate_http_url`, `clean_text`, `RawPost`, `Comment`, `Store`
- Produces (모두 순수 함수—테스트는 HTML만으로 가능):
  - `@dataclass ListedPost(post_no: int, title: str, author: str, created_at: datetime | None, views: int, recommend: int)`
  - `parse_list_page(html: str) -> list[ListedPost]`
  - `@dataclass PostDetail(title: str, body: str, author: str, created_at: datetime | None, views: int, recommend: int, comments: list[Comment])`
  - `parse_post_page(html: str, post_no: int) -> PostDetail`
  - `class BlockedError(RuntimeError)`
  - `class DcInsideCollector(gallery_id: str, cfg: CollectConfig, cookies: str | None = None)`: `collect(pages: int, progress=print) -> Iterator[RawPost]`
- **fixture는 계약(contract)의 source of truth**: 아래 합성 HTML은 파서 계약을 정의한다. 실제 페이지 구조가 다르면 README의 절차(`scripts/refresh_fixtures.sh`)로 live HTML로 fixture를 교체하고 파서를 fixture에 맞춘다. 테스트는 항상 fixture 파일만 본다.

- [ ] **Step 1: fixture `tests/fixtures/dc/list_page.html` 작성 (합성, 파서 계약 정의용)**

```html
<html><body>
<table class="gall_list"><tbody>
<tr class="ub-content">
  <td class="gall_writer">양추가</td>
  <td class="gall_tit ub-word"><a href="/board/view/?id=crypto&no=101">[국내] 비트코인 전망</a></td>
  <td class="gall_date" title="2026-08-10 09:00:00">08.10</td>
  <td class="gall_count">300</td>
  <td class="gall_recommend">45</td>
</tr>
<tr class="ub-content">
  <td class="gall_writer">마이너</td>
  <td class="gall_tit ub-word"><a href="/board/view/?id=crypto&no=102">채굴 단가</a></td>
  <td class="gall_date" title="2026-08-11 10:00:00">08.11</td>
  <td class="gall_count">80</td>
  <td class="gall_recommend">3</td>
</tr>
</tbody></table>
</body></html>
```

- [ ] **Step 2: fixture `tests/fixtures/dc/post_page.html` 작성**

```html
<html><body>
<div class="view_content_wrap">
  <span class="nickname">양추가</span>
  <span class="gall_date" title="2026-08-10 09:00:00">08.10</span>
  <em>조회 <strong>300</strong></em>
  <em>추천 <strong>45</strong></em>
  <h3 class="title_subject">[국내] 비트코인 전망</h3>
  <div class="write_div"><p>커핑 시즌 어떻게 보심? <b>롱</b>인가</p></div>
</div>
<ul class="comment_ul li乌鲁 list_wrap">
  <li class="ub-content"><div class="cmt_info"><strong>추천 12</strong></div>
    <div class="usertxt">나는 확신</div></li>
  <li class="ub-content"><div class="cmt_info"><strong>추천 5</strong></div>
    <div class="usertxt">무조건 롱</div></li>
</ul>
</body></html>
```

- [ ] **Step 3: 실패 테스트 `tests/test_dcinside.py`**

```python
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
```

- [ ] **Step 4: 실패 확인**

Run: `pytest tests/test_dcinside.py -v` → FAIL

- [ ] **Step 5: `dc_harness/collect/dcinside.py` 구현**

```python
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

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
BLOCK_MARKERS = ("captcha", "자동 접근", "보안을 위해")


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
        items.append(ListedPost(
            post_no=int(qs["no"][0]),
            title=clean_text(link.get_text()),
            author=clean_text(tr.select_one(".gall_writer").get_text()
                              if tr.select_one(".gall_writer") else ""),
            created_at=_parse_date(tr.select_one(".gall_date")),
            views=_int(tr.select_one(".gall_count").get_text()
                       if tr.select_one(".gall_count") else ""),
            recommend=_int(tr.select_one(".gall_recommend").get_text()
                           if tr.select_one(".gall_recommend") else ""),
        ))
    return items


def parse_post_page(html: str, post_no: int) -> PostDetail:
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one(".title_subject")
    body_tag = soup.select_one(".write_div") or soup.select_one(".view_content_wrap")
    comments: list[Comment] = []
    for seq, li in enumerate(soup.select("ul.comment_ul li.ub-content")):
        rec_tag = li.select_one(".cmt_info strong")
        comments.append(Comment(
            post_no=post_no, seq=seq,
            text=clean_text(li.select_one(".usertxt").get_text()
                            if li.select_one(".usertxt") else ""),
            recommend=_int(rec_tag.get_text() if rec_tag else ""),
        ))
    strongs = [s.get_text() for s in soup.select("em strong")]
    return PostDetail(
        title=clean_text(title_tag.get_text() if title_tag else ""),
        body=clean_text(body_tag.get_text() if body_tag else ""),
        author=clean_text(soup.select_one(".nickname").get_text()
                          if soup.select_one(".nickname") else ""),
        created_at=_parse_date(soup.select_one(".gall_date")),
        views=_int(strongs[0] if len(strongs) > 0 else ""),
        recommend=_int(strongs[1] if len(strongs) > 1 else ""),
        comments=comments,
    )


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

    def _get(self, url: str) -> str:
        validate_http_url(url, DC_HOSTS)  # http/https + DC allowlist (private IP 불가)
        last_exc: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            try:
                resp = self.client.get(url)
                if resp.status_code in (403, 429) or any(
                        m in resp.text for m in BLOCK_MARKERS):
                    raise BlockedError(f"blocked by dcinside: {url} (status={resp.status_code})")
                resp.raise_for_status()
                time.sleep(self.cfg.delay_min_seconds
                           + random.uniform(0, self.cfg.delay_jitter_seconds))
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
                post_html = self._get(
                    POST_URL.format(gallery_id=self.gallery_id, post_no=item.post_no))
                detail = parse_post_page(post_html, item.post_no)
                yield RawPost(
                    gallery_id=self.gallery_id, post_no=item.post_no,
                    title=detail.title or item.title, body=detail.body,
                    author=detail.author or item.author,
                    created_at=detail.created_at or item.created_at,
                    views=detail.views or item.views,
                    recommend=detail.recommend or item.recommend,
                    comments=detail.comments,
                )
```

- [ ] **Step 6: 통과 확인 + 커밋**

Run: `pytest tests/test_dcinside.py -v` → PASS

```bash
git add dc_harness/collect/dcinside.py tests/test_dcinside.py tests/fixtures/dc/
git commit -m "feat: dcinside collector with fixture-driven parsers and polite fetcher"
```

---

### Task 7: LLM 클라이언트 (think-strip, JSON 추출, 재시도)

**Files:**
- Create: `dc_harness/llm/__init__.py`, `dc_harness/llm/client.py`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `LlmConfig`, `resolve_api_key`, `validate_http_url` (base_url 공개 호스트 검증)
- Produces:
  - `strip_think(text: str) -> str` — `<think>...</think>` 제거
  - `extract_json(text: str) -> dict | list` — 첫 번째 JSON 블록 파싱, 실패 시 `LlmJsonError`
  - `class LlmJsonError(ValueError)`
  - `class LlmClient(base_url: str, model: str, api_key: str, temperature: float = 0.3, timeout: float = 60.0, inner: object | None = None)` — `inner`은 테스트 주입용 OpenAI 호환 클라이언트(`inner.chat.completions.create(model, messages, temperature, stream=False)` → `.choices[0].message.content`). `chat_json(system: str, user: str, max_retries: int = 2) -> dict | list`

- [ ] **Step 1: 실패 테스트 `tests/test_llm_client.py`**

```python
import pytest

from dc_harness.llm.client import LlmClient, LlmJsonError, extract_json, strip_think


def test_strip_think():
    assert strip_think("<think>reasoning...</think>{\"a\": 1}") == '{"a": 1}'
    assert strip_think("no tags") == "no tags"


def test_extract_json_from_codefence():
    assert extract_json('말씀드리면:\n```json\n{"topics": []}\n```\n끝') == {"topics": []}


def test_extract_json_invalid_raises():
    with pytest.raises(LlmJsonError):
        extract_json("json이 아님")


class FakeCompletions:
    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.replies.pop(0)
        class Msg:  # noqa: D401 - test stub
            pass
        msg, choice = Msg(), Msg()
        msg.content = content
        choice.message = msg
        wrapper = Msg()
        wrapper.choices = [choice]
        return wrapper


class FakeInner:
    def __init__(self, replies: list[str]):
        self.chat = Msg = type("M", (), {})
        self.chat.completions = FakeCompletions(replies)


def make_client(replies: list[str]) -> LlmClient:
    return LlmClient("https://chat.motiftech.io/openapi/v1", "m", "fake-key",
                     inner=FakeInner(replies))


def test_chat_json_success_first_try():
    client = make_client(['```json\n{"ok": true}\n```'])
    assert client.chat_json("sys", "user") == {"ok": True}


def test_chat_json_retries_on_bad_json_then_repair():
    client = make_client(["이건 json 아님", '{"fixed": 1}'])
    assert client.chat_json("sys", "user", max_retries=1) == {"fixed": 1}
    assert "JSON" in client.inner.chat.completions.calls[-1]["messages"][-1]["content"]


def test_chat_json_gives_up_after_retries():
    client = make_client(["bad", "bad", "bad"])
    with pytest.raises(LlmJsonError):
        client.chat_json("sys", "user", max_retries=2)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_llm_client.py -v` → FAIL

- [ ] **Step 3: `dc_harness/llm/client.py` 구현**

```python
from __future__ import annotations

import json
import re

from ..net.guard import UnsafeUrlError, validate_http_url

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_RE = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


class LlmJsonError(ValueError):
    pass


def strip_think(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def extract_json(text: str) -> dict | list:
    cleaned = strip_think(text).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    match = _JSON_RE.search(cleaned)
    if not match:
        raise LlmJsonError("no json object found in response")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LlmJsonError(f"invalid json: {exc}") from exc


class LlmClient:
    def __init__(self, base_url: str, model: str, api_key: str,
                 temperature: float = 0.3, timeout: float = 60.0, inner=None):
        try:
            validate_http_url(base_url)
        except UnsafeUrlError as exc:
            raise ValueError(f"unsafe llm base_url: {base_url}") from exc
        self.model, self.temperature = model, temperature
        if inner is None:
            from openai import OpenAI
            inner = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.inner = inner

    def chat_json(self, system: str, user: str, max_retries: int = 2) -> dict | list:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        last_error: LlmJsonError | None = None
        for attempt in range(max_retries + 1):
            response = self.inner.chat.completions.create(
                model=self.model, messages=messages, temperature=self.temperature,
                stream=False)
            content = response.choices[0].message.content or ""
            try:
                return extract_json(content)
            except LlmJsonError as exc:
                last_error = exc
                messages = messages[:2] + [
                    {"role": "assistant", "content": content[:2000]},
                    {"role": "user", "content":
                     "지금 응답은 유효한 JSON이 아니었다. 설명 없이 요청된 JSON 객체만 출력해라."},
                ]
        raise last_error  # type: ignore[misc]
```

`dc_harness/llm/__init__.py`는 빈 파일.

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/test_llm_client.py -v` → PASS

```bash
git add dc_harness/llm/ tests/test_llm_client.py
git commit -m "feat: llm client with think-stripping, json extraction and repair retry"
```

---

### Task 8: 청커 + 게시글 렌더링

**Files:**
- Create: `dc_harness/llm/chunker.py`
- Test: `tests/test_chunker.py`

**Interfaces:**
- Consumes: `RawPost`
- Produces:
  - `render_post_text(post: RawPost, max_comments: int = 10) -> str` — `[글#101] 제목 (추천45) 본문 :: 댓글: (추천12) 나는 확신 | ...`
  - `chunk_posts(posts: list[RawPost], max_chars: int = 12000) -> list[list[RawPost]]`

- [ ] **Step 1: 실패 테스트 `tests/test_chunker.py`**

```python
from datetime import datetime

from dc_harness.llm.chunker import chunk_posts, render_post_text
from dc_harness.models import Comment, RawPost


def post(no: int, body: str = "x" * 200) -> RawPost:
    return RawPost("crypto", no, f"t{no}", body, "a", datetime(2026, 8, 10), 1, 2,
                   [Comment(no, 0, "c0", 5), Comment(no, 1, "c1")])


def test_render_post_text_includes_ref_and_top_comments():
    text = render_post_text(post(1), max_comments=1)
    assert "[글#1]" in text and "t1" in text and "c0" in text and "c1" not in text


def test_chunk_posts_respects_budget():
    posts = [post(i) for i in range(1, 6)]  # 각 ~220자
    chunks = chunk_posts(posts, max_chars=500)
    assert len(chunks) >= 2
    assert sum(len(c) for c in chunks) == 5
    for chunk in chunks:
        assert sum(len(render_post_text(p)) for p in chunk) <= 500 + 250  # 한 글 초과 허용


def test_oversized_single_post_still_included():
    big = post(9, body="y" * 3000)
    chunks = chunk_posts([big], max_chars=500)
    assert len(chunks) == 1 and chunks[0] == [big]
```

- [ ] **Step 2: 실패 확인 → 구현 `dc_harness/llm/chunker.py`**

Run: `pytest tests/test_chunker.py -v` → FAIL 후:

```python
from __future__ import annotations

from ..models import RawPost


def render_post_text(post: RawPost, max_comments: int = 10) -> str:
    comments = sorted(post.comments, key=lambda c: c.recommend, reverse=True)[:max_comments]
    rendered = " | ".join(f"(추천{c.recommend}) {c.text}" for c in comments)
    return (f"[글#{post.post_no}] {post.title} (추천{post.recommend}) "
            f"{post.body}" + (f" :: 댓글: {rendered}" if rendered else ""))


def chunk_posts(posts: list[RawPost], max_chars: int = 12000) -> list[list[RawPost]]:
    chunks: list[list[RawPost]] = []
    current: list[RawPost] = []
    used = 0
    for post in posts:
        size = len(render_post_text(post))
        if current and used + size > max_chars:
            chunks.append(current)
            current, used = [], 0
        current.append(post)
        used += size
    if current:
        chunks.append(current)
    return chunks
```

- [ ] **Step 3: 통과 확인 + 커밋**

Run: `pytest tests/test_chunker.py -v` → PASS

```bash
git add dc_harness/llm/chunker.py tests/test_chunker.py
git commit -m "feat: post rendering and char-budget chunker"
```

---

### Task 9: 분석 엔진 — kinds 레지스트리 + map-reduce 러너

**Files:**
- Create: `dc_harness/analyze/__init__.py`, `dc_harness/analyze/kinds.py`, `dc_harness/analyze/runner.py`
- Test: `tests/test_analyzers.py`

**Interfaces:**
- Consumes: `LlmClient.chat_json(system, user, max_retries=...)`, `chunk_posts`, `render_post_text`, `Store`, `normalize_label`
- Produces:
  - `@dataclass AnalysisKind(name: str, system: str, instruction: str, schema_hint: str)`
  - `KINDS: dict[str, AnalysisKind]` — `"topics" | "sentiment" | "entities" | "voices"` (trends는 Task 10)
  - `merge_chunk_results(kind: str, results: list[dict]) -> dict` — kind별 집계
  - `class Analyzer(store: Store, llm: LlmClient)`: `run(gallery_id: str, start: date, end: date, kinds: list[str], max_chars: int = 12000) -> tuple[int, dict[str, dict], dict]` — 반환: `(run_id, kind→결과, coverage)` (run_id는 Phase 2 materialize가 사용). 내부에서 `start_run`/`save_analysis`/`finish_run` 수행. 청크 실패는 격리되어 coverage에 반영.

- [ ] **Step 1: 실패 테스트 `tests/test_analyzers.py`**

```python
from datetime import date, datetime

import pytest

from dc_harness.analyze.kinds import KINDS, merge_chunk_results
from dc_harness.analyze.runner import Analyzer
from dc_harness.models import Comment, RawPost
from dc_harness.store import Store


def make_post(no: int) -> RawPost:
    return RawPost("crypto", no, f"t{no}", f"body{no}", "a",
                   datetime(2026, 8, 10), 10, no,
                   [Comment(no, 0, "댓글", no)])


class StubLlm:
    """chat_json 호출마다 canned 응답을 반환. 실패 지정 가능."""

    def __init__(self, reply, fail_first: int = 0):
        self.reply, self.fail_first = reply, fail_first
        self.calls = 0

    def chat_json(self, system, user, max_retries=2):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise ValueError("llm chunk failed")
        return self.reply


def test_kinds_registry_has_four_kinds():
    assert set(KINDS) == {"topics", "sentiment", "entities", "voices"}


def test_merge_topics_dedupes_by_label():
    merged = merge_chunk_results("topics", [
        {"topics": [{"label": "비트코인", "post_nos": [1, 2], "keywords": ["현물", "레버"]}]},
        {"topics": [{"label": "비트코인 ", "post_nos": [2, 3], "keywords": ["etf"]}]},
    ])
    assert len(merged["topics"]) == 1
    assert merged["topics"][0]["post_nos"] == [1, 2, 3]
    assert "etf" in merged["topics"][0]["keywords"]


def test_merge_entities_conflicting_sentiment_becomes_mixed():
    merged = merge_chunk_results("entities", [
        {"entities": [{"name": "이더리움", "type": "종목", "mentions": 3,
                       "sentiment": "긍정", "reason": "r"}]},
        {"entities": [{"name": "이더리움", "type": "종목", "mentions": 2,
                       "sentiment": "부정", "reason": "r2"}]},
    ])
    entity = merged["entities"][0]
    assert entity["mentions"] == 5 and entity["sentiment"] == "mixed"


def test_merge_voices_counts_duplicates():
    merged = merge_chunk_results("voices", [
        {"voices": [{"kind": "painpoint", "text": "앱이 느림", "post_no": 1, "quote": "q"}]},
        {"voices": [{"kind": "painpoint", "text": "앱이 느림 ", "post_no": 5, "quote": "q2"},
                     {"kind": "wish", "text": "다크모드", "post_no": 2, "quote": "q3"}]},
    ])
    by_text = {v["text"]: v for v in merged["voices"]}
    assert by_text["앱이 느림"]["count"] == 2
    assert by_text["다크모드"]["count"] == 1


def test_runner_map_reduce_with_stub(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        for no in (1, 2, 3, 4):
            store.upsert_post(make_post(no))
        stub = StubLlm({"topics": [{"label": "전망", "post_nos": [1], "keywords": ["롱"]}]})
        run_id, results, coverage = Analyzer(store, stub).run(
            "crypto", date(2026, 8, 1), date(2026, 8, 31), ["topics"], max_chars=300)
        assert results["topics"]["topics"][0]["label"] == "전망"
        assert coverage["chunks_total"] == stub.calls
        assert coverage["chunks_failed"] == 0
        saved = store.latest_analyses("crypto", date(2026, 8, 1), date(2026, 8, 31))
        assert "topics" in saved


def test_runner_isolates_chunk_failure(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        for no in (1, 2, 3, 4, 5, 6):
            store.upsert_post(make_post(no))
        stub = StubLlm({"topics": []}, fail_first=1)  # 첫 청크 실패, 이후 성공
        run_id, results, coverage = Analyzer(store, stub).run(
            "crypto", date(2026, 8, 1), date(2026, 8, 31), ["topics"], max_chars=300)
        assert coverage["chunks_failed"] == 1
        assert results["topics"] == {"topics": []}
```

`from pathlib import Path` 임포트 누락 주의: 테스트 파일 상단에 `from pathlib import Path` 추가.

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_analyzers.py -v` → FAIL

- [ ] **Step 3: `dc_harness/analyze/kinds.py` 구현 (프롬프트 포함)**

```python
from __future__ import annotations

from dataclasses import dataclass

from ..normalize import normalize_label

_SYSTEM = (
    "너는 한국 커뮤니티(DC Inside) 데이터를 분석하는 연구 보조자다. "
    "입력은 게시글/댓글 모음이다. 오직 요청된 JSON 객체만 출력하고 다른 설명은 하지 마라. "
    "욕설·비속어는 분석 대상일 뿐 출력에 그대로 반복하지 마라."
)


@dataclass
class AnalysisKind:
    name: str
    system: str
    instruction: str
    schema_hint: str


KINDS: dict[str, AnalysisKind] = {
    "topics": AnalysisKind(
        name="topics", system=_SYSTEM,
        instruction="이 게시글/댓글 모음에서 논의되는 상위 토픽(주제)을 추출하라. "
                    "토픽 3~7개, 각 토픽마다 근거가 된 글 번호(post_no)와 반복 키워드를 포함하라.",
        schema_hint='{"topics": [{"label": "토픽명", "post_nos": [101], '
                    '"keywords": ["k1", "k2"], "snippet": "대표 문장 한 줄"}]}',
    ),
    "sentiment": AnalysisKind(
        name="sentiment", system=_SYSTEM,
        instruction="주요 이슈별 여론을 분석하라. 각 이슈의 찬성(pro)/반대(con)/중립(neutral) "
                    "발언 수와 대표 인용(최대 3개)을 포함하라. 추천수가 높은 글/댓글은 "
                    "공감을 얻은 반응이므로 resonant 배열에 따로 정리하라.",
        schema_hint='{"issues": [{"issue": "이슈명", "pro": 3, "con": 1, "neutral": 0, '
                    '"quotes": [{"post_no": 101, "stance": "pro", "text": "..."}]}], '
                    '"resonant": [{"post_no": 101, "text": "...", "why": "왜 공감을 얻었는지"]}]}',
    ),
    "entities": AnalysisKind(
        name="entities", system=_SYSTEM,
        instruction="언급된 인물/종목/제품/브랜드/서비스(entity)를 추출하고 각각에 대한 "
                    "여론(sentiment: 긍정/부정/mixed/중립)과 이유를 정리하라.",
        schema_hint='{"entities": [{"name": "이름", "type": "인물|종목|제품|브랜드|기타", '
                    '"mentions": 5, "sentiment": "긍정", "reason": "..."}]}',
    ),
    "voices": AnalysisKind(
        name="voices", system=_SYSTEM,
        instruction="불만(painpoint), 바람(wish: '~있으면 좋겠다'), 아이디어(idea)를 추출하라. "
                    "각 항목은 원문 인용과 글 번호를 포함하고, 사용자 표현을 축약하지 마라.",
        schema_hint='{"voices": [{"kind": "painpoint|wish|idea", "text": "요약 한 줄", '
                    '"post_no": 101, "quote": "원문 인용"}]}',
    ),
}


def _cap(items: list, limit: int) -> list:
    return items[:limit]


def merge_chunk_results(kind: str, results: list[dict]) -> dict:
    if kind == "topics":
        by_label: dict[str, dict] = {}
        for res in results:
            for topic in res.get("topics", []):
                key = normalize_label(topic.get("label", ""))
                if key in by_label:
                    merged = by_label[key]
                    merged["post_nos"] = list(dict.fromkeys(
                        merged["post_nos"] + topic.get("post_nos", [])))
                    merged["keywords"] = list(dict.fromkeys(
                        merged["keywords"] + topic.get("keywords", [])))[:8]
                else:
                    by_label[key] = {
                        "label": topic.get("label", ""), "post_nos": topic.get("post_nos", []),
                        "keywords": topic.get("keywords", [])[:8],
                        "snippet": topic.get("snippet", ""),
                    }
        return {"topics": _cap(list(by_label.values()), 10)}

    if kind == "sentiment":
        by_issue: dict[str, dict] = {}
        resonant: list[dict] = []
        for res in results:
            resonant.extend(res.get("resonant", []))
            for issue in res.get("issues", []):
                key = normalize_label(issue.get("issue", ""))
                if key in by_issue:
                    m = by_issue[key]
                    for field in ("pro", "con", "neutral"):
                        m[field] += issue.get(field, 0)
                    m["quotes"] = _cap(m["quotes"] + issue.get("quotes", []), 5)
                else:
                    by_issue[key] = {
                        "issue": issue.get("issue", ""),
                        "pro": issue.get("pro", 0), "con": issue.get("con", 0),
                        "neutral": issue.get("neutral", 0),
                        "quotes": _cap(issue.get("quotes", []), 5),
                    }
        return {"issues": _cap(list(by_issue.values()), 12), "resonant": _cap(resonant, 10)}

    if kind == "entities":
        by_name: dict[str, dict] = {}
        for res in results:
            for entity in res.get("entities", []):
                key = normalize_label(entity.get("name", ""))
                if key in by_name:
                    m = by_name[key]
                    m["mentions"] += entity.get("mentions", 0)
                    if m["sentiment"] != entity.get("sentiment", "중립"):
                        m["sentiment"] = "mixed"
                    m["reason"] += " / " + entity.get("reason", "")
                else:
                    by_name[key] = dict(entity)
        return {"entities": _cap(
            sorted(by_name.values(), key=lambda e: e["mentions"], reverse=True), 15)}

    if kind == "voices":
        by_text: dict[str, dict] = {}
        for res in results:
            for voice in res.get("voices", []):
                key = (voice.get("kind", ""), normalize_label(voice.get("text", "")))
                if key in by_text:
                    by_text[key]["count"] += 1
                else:
                    item = dict(voice)
                    item["count"] = 1
                    by_text[key] = item
        ordered = sorted(by_text.values(), key=lambda v: v["count"], reverse=True)
        return {"voices": _cap(ordered, 20)}

    raise ValueError(f"unknown kind: {kind}")
```

- [ ] **Step 4: `dc_harness/analyze/runner.py` 구현**

```python
from __future__ import annotations

from datetime import date

from ..llm.chunker import chunk_posts, render_post_text
from ..llm.client import LlmClient
from ..store import Store
from .kinds import KINDS, AnalysisKind, merge_chunk_results


class Analyzer:
    def __init__(self, store: Store, llm: LlmClient):
        self.store, self.llm = store, llm

    def _map(self, kind: AnalysisKind, chunks) -> tuple[list[dict], int]:
        results: list[dict] = []
        failed = 0
        for chunk in chunks:
            corpus = "\n\n".join(render_post_text(p) for p in chunk)
            user = (f"{kind.instruction}\n\n출력 스키마(JSON):\n{kind.schema_hint}\n\n"
                    f"=== 데이터 ===\n{corpus}")
            try:
                results.append(self.llm.chat_json(kind.system, user))
            except Exception:
                failed += 1
        return results, failed

    def run(self, gallery_id: str, start: date, end: date, kinds: list[str],
            max_chars: int = 12000) -> tuple[int, dict[str, dict], dict]:
        posts = self.store.fetch_posts(gallery_id, start, end)
        if not posts:
            return -1, {}, {"chunks_total": 0, "chunks_failed": 0,
                        "posts_included": 0, "posts_total": 0}
        chunks = chunk_posts(posts, max_chars=max_chars)
        run_id = self.start_run_guarded(gallery_id)
        results: dict[str, dict] = {}
        total_failed = 0
        for name in kinds:
            kind = KINDS[name]
            chunk_results, failed = self._map(kind, chunks)
            total_failed += failed
            results[name] = merge_chunk_results(name, chunk_results)
            self.store.save_analysis(run_id, name, gallery_id, start, end, results[name])
        coverage = {
            "chunks_total": len(chunks) * len(kinds),
            "chunks_failed": total_failed,
            "posts_included": len(posts),
            "posts_total": self.store.fetch_posts(gallery_id).__len__(),
        }
        self.store.finish_run(run_id, "done", coverage)
        return run_id, results, coverage

    def start_run_guarded(self, gallery_id: str) -> int:
        return self.store.start_run(gallery_id)
```

`dc_harness/analyze/__init__.py`는 빈 파일.

- [ ] **Step 5: 통과 확인 + 커밋**

Run: `pytest tests/test_analyzers.py -v` → PASS

```bash
git add dc_harness/analyze/ tests/test_analyzers.py
git commit -m "feat: analysis kinds registry and map-reduce runner with failure isolation"
```

---

### Task 10: 트렌드 분석 (기간 비교)

**Files:**
- Create: `dc_harness/analyze/trends.py`
- Test: `tests/test_trends.py`

**Interfaces:**
- Consumes: `Analyzer`, `LlmClient.chat_json`, `KINDS`의 `_SYSTEM` 문구(`kinds.py`에서 `SYSTEM_PROMPT = _SYSTEM`으로 export 추가)
- Produces: `class TrendAnalyzer(llm: LlmClient)`: `diff(gallery_id: str, prev: dict, cur: dict, prev_label: str, cur_label: str) -> dict` — 두 기간의 topics+sentiment+entities 결과 JSON을 받아 `{"rising": [], "falling": [], "shifts": [], "summary": str}` 반환.

- [ ] **Step 1: `kinds.py`에 export 추가 (Modify)**

`dc_harness/analyze/kinds.py` 상단의 `_SYSTEM` 아래에 한 줄 추가:

```python
SYSTEM_PROMPT = _SYSTEM
```

- [ ] **Step 2: 실패 테스트 `tests/test_trends.py`**

```python
import json

from dc_harness.analyze.trends import TrendAnalyzer

PREV = {"topics": {"topics": [{"label": "레버리지", "post_nos": [1], "keywords": ["롱"], "snippet": ""}]}}
CUR = {"topics": {"topics": [{"label": "현물", "post_nos": [2], "keywords": ["매수"], "snippet": ""}]}}


class StubLlm:
    def __init__(self):
        self.seen_user = ""

    def chat_json(self, system, user, max_retries=2):
        self.seen_user = user
        return {"rising": [{"label": "현물", "reason": "신규 언급 급증"}],
                "falling": [{"label": "레버리지", "reason": "언급 감소"}],
                "shifts": [{"label": "이더리움", "from": "긍정", "to": "부정"}],
                "summary": "현물 관심이 레버리지를 대체"}


def test_diff_returns_llm_result_and_includes_both_periods():
    stub = StubLlm()
    result = TrendAnalyzer(stub).diff("crypto", PREV, CUR, "지난주", "이번주")
    assert result["rising"][0]["label"] == "현물"
    assert "지난주" in stub.seen_user and "이번주" in stub.seen_user
    assert json.dumps(PREV["topics"], ensure_ascii=False) in stub.seen_user
```

- [ ] **Step 3: 실패 확인 → `dc_harness/analyze/trends.py` 구현**

```python
from __future__ import annotations

import json

from ..llm.client import LlmClient
from .kinds import SYSTEM_PROMPT


class TrendAnalyzer:
    INSTRUCTION = (
        "두 기간의 분석 결과 JSON이 주어진다. 이번 기간에 새로 떠오르거나 언급이 늘어난 "
        "주제(rising), 식었거나 사라진 주제(falling), 여론이 바뀐 대상(shifts)을 찾고 "
        "세 문장 이내로 요약(summary)하라."
    )
    SCHEMA = ('{"rising": [{"label": "...", "reason": "..."}], '
              '"falling": [{"label": "...", "reason": "..."}], '
              '"shifts": [{"label": "...", "from": "...", "to": "..."}], '
              '"summary": "..."}')

    def __init__(self, llm: LlmClient):
        self.llm = llm

    def diff(self, gallery_id: str, prev: dict, cur: dict,
             prev_label: str, cur_label: str) -> dict:
        user = (f"{self.INSTRUCTION}\n\n출력 스키마(JSON):\n{self.SCHEMA}\n\n"
                f"=== {prev_label} 분석 결과 ===\n{json.dumps(prev, ensure_ascii=False)}\n\n"
                f"=== {cur_label} 분석 결과 ===\n{json.dumps(cur, ensure_ascii=False)}")
        return self.llm.chat_json(SYSTEM_PROMPT, user)
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/test_trends.py -v` → PASS

```bash
git add dc_harness/analyze/trends.py dc_harness/analyze/kinds.py tests/test_trends.py
git commit -m "feat: two-period trend diff analyzer"
```

---

### Task 11: 리포트 렌더러 (Markdown + JSON)

**Files:**
- Create: `dc_harness/report/__init__.py`, `dc_harness/report/render.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: 분석 결과 dict, `RawPost`, coverage dict
- Produces:
  - `render_report(gallery_id: str, start: date, end: date, analyses: dict[str, dict], top: list[RawPost], coverage: dict) -> tuple[str, dict]` — (markdown, json_payload)
  - `save_report(out_dir: Path, gallery_id: str, start: date, end: date, markdown: str, payload: dict) -> Path` — `out_dir/<gallery_id>/<start>~<end>.md`(+`.json`) 저장, md 경로 반환.

- [ ] **Step 1: 실패 테스트 `tests/test_report.py`**

```python
from datetime import date, datetime
from pathlib import Path

from dc_harness.models import RawPost
from dc_harness.report.render import render_report, save_report

ANALYSES = {
    "topics": {"topics": [{"label": "현물 매수", "post_nos": [101],
                           "keywords": ["매수", "저가"], "snippet": "지금이 기회"}]},
    "sentiment": {"issues": [{"issue": "반감기", "pro": 4, "con": 2, "neutral": 1, "quotes": []}],
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
```

- [ ] **Step 2: 실패 확인 → `dc_harness/report/render.py` 구현**

```python
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
        lines.append(f"| {t['label']} | {', '.join(t.get('keywords', []))} "
                     f"| {', '.join(f'#{n}' for n in t.get('post_nos', [])[:5])} |")
    return lines


def _section_sentiment(data: dict) -> list[str]:
    lines = []
    for issue in data.get("issues", []):
        total = max(issue.get("pro", 0) + issue.get("con", 0) + issue.get("neutral", 0), 1)
        lines.append(f"- **{issue['issue']}** — 찬성 {issue.get('pro', 0)} / "
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
        lines.append(f"| {e['name']} | {e.get('type', '')} | {e.get('mentions', 0)} "
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
        lines.append(f"- 🔺 {item.get('label')}: {item.get('reason', '')}")
    for item in data.get("falling", []):
        lines.append(f"- 🔻 {item.get('label')}: {item.get('reason', '')}")
    for shift in data.get("shifts", []):
        lines.append(f"- 🔁 {shift.get('label')}: {shift.get('from')} → {shift.get('to')}")
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
        md += [f"- 상위 토픽: {', '.join(t['label'] for t in first[:5]) or '없음'}", ""]
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
    payload = {"gallery_id": gallery_id, "period": {"start": start.isoformat(),
               "end": end.isoformat()}, "analyses": analyses,
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
```

`dc_harness/report/__init__.py`는 빈 파일.

주의: `base.with_suffix(".md")`는 파일명에 `~`가 있어 안전하나 `2026-08-01~2026-08-07`에 점이 없으므로 정상 동작한다.

- [ ] **Step 3: 통과 확인 + 커밋**

Run: `pytest tests/test_report.py -v` → PASS

```bash
git add dc_harness/report/ tests/test_report.py
git commit -m "feat: markdown/json report renderer"
```

---

### Task 12: CLI (collect / ingest / analyze / report / run)

**Files:**
- Create: `dc_harness/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 모든 이전 태스크의 공개 인터페이스
- Produces: `main(argv: list[str] | None = None, *, llm_factory=None) -> int` — llm_factory는 테스트 주입용 `Callable[[Config], LlmClient]}`. 서브커맨드:
  - `dch collect --gallery ID --pages N [--db PATH] [--config PATH]`
  - `dch ingest --gallery ID --file dump.jsonl [--db PATH]`
  - `dch analyze --gallery ID --days N [--kinds topics,sentiment,entities,voices] [--db PATH]`
  - `dch report --gallery ID --days N [--out reports] [--db PATH]`
  - `dch run --gallery ID --days N --pages N` (collect→analyze(당기+직전 기간)→report)
- 동작 규칙: `--days N` 기간 = `[today-N, today]`, 직전 기간 = `[today-2N, today-N]`(trends용, 직전 데이터 있을 때만). collect/ingest는 `BlockedError`를 잡아 지금까지 수집분 저장 후 exit code 2로 종료.

- [ ] **Step 1: 실패 테스트 `tests/test_cli.py` (종단: ingest→analyze→report, 스텁 LLM)**

```python
import json
from datetime import date, timedelta
from pathlib import Path

from dc_harness.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ingest.jsonl"
TODAY = date.today()


class StubLlm:
    def __init__(self, cfg):
        pass

    def chat_json(self, system, user, max_retries=2):
        return {"topics": [{"label": "전망", "post_nos": [101],
                            "keywords": ["매수"], "snippet": "s"}],
                "sentiment": {"issues": [], "resonant": []},
                "entities": {"entities": []},
                "voices": {"voices": []}}


def _shift_fixture_dates(tmp_path: Path) -> Path:
    posts = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        d["created_at"] = f"{TODAY.isoformat()}T09:00:00"
        posts.append(json.dumps(d, ensure_ascii=False))
    f = tmp_path / "today.jsonl"
    f.write_text("\n".join(posts) + "\n", encoding="utf-8")
    return f


def test_end_to_end_ingest_analyze_report(tmp_path: Path, monkeypatch, capsys):
    db = tmp_path / "dch.db"
    fixture = _shift_fixture_dates(tmp_path)
    assert main(["ingest", "--gallery", "crypto", "--file", str(fixture),
                 "--db", str(db)]) == 0
    rc = main(["analyze", "--gallery", "crypto", "--days", "7", "--db", str(db),
               "--kinds", "topics"], llm_factory=StubLlm)
    assert rc == 0
    rc = main(["report", "--gallery", "crypto", "--days", "7",
               "--out", str(tmp_path / "reports"), "--db", str(db)], llm_factory=StubLlm)
    assert rc == 0
    reports = list((tmp_path / "reports" / "crypto").glob("*.md"))
    assert reports and "전망" in reports[0].read_text(encoding="utf-8")


def test_run_pipeline_with_stub(tmp_path: Path, monkeypatch):
    fixture = _shift_fixture_dates(tmp_path)
    db = tmp_path / "dch.db"

    def fake_collect(args):
        rc = main(["ingest", "--gallery", "crypto", "--file", str(fixture),
                   "--db", str(db)])
        assert rc == 0

    # collect 단계를 ingest로 대체하는 대신, run을 파일 기반으로: pages 없이는 수집 생략
    rc = main(["run", "--gallery", "crypto", "--days", "7",
               "--db", str(db), "--file", str(fixture),
               "--out", str(tmp_path / "reports")], llm_factory=StubLlm)
    assert rc == 0
    assert list((tmp_path / "reports" / "crypto").glob("*.md"))


def test_collect_missing_pages_ok(tmp_path: Path):
    # collect는 실네트워크를 쓰므로 CI에서는 페이지 0으로 스킵만 확인
    assert main(["collect", "--gallery", "crypto", "--pages", "0",
                 "--db", str(tmp_path / "dch.db")]) == 0
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_cli.py -v` → FAIL

- [ ] **Step 3: `dc_harness/cli.py` 구현**

```python
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from .analyze.runner import Analyzer
from .analyze.trends import TrendAnalyzer
from .collect.dcinside import BlockedError, DcInsideCollector
from .collect.jsonl import JsonlCollector
from .config import Config, load_config, resolve_api_key
from .llm.client import LlmClient
from .normalize import author_hash
from .report.render import render_report, save_report
from .store import Store

DEFAULT_KINDS = "topics,sentiment,entities,voices"


def _period(days: int) -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=days), today


def _make_llm(cfg: Config) -> LlmClient:
    return LlmClient(cfg.llm.base_url, cfg.llm.model, resolve_api_key(cfg),
                     temperature=cfg.llm.temperature, timeout=cfg.llm.timeout)


def _cmd_collect(args, cfg: Config) -> int:
    if args.pages <= 0:
        print("pages=0: nothing to collect")
        return 0
    cookies = None
    import os
    if os.environ.get(cfg.collect.cookies_env):
        cookies = os.environ[cfg.collect.cookies_env]
    collector = DcInsideCollector(args.gallery, cfg.collect, cookies=cookies)
    collected = 0
    with Store(Path(args.db)) as store:
        try:
            for post in collector.collect(args.pages):
                post.author = author_hash(post.author, cfg.privacy_salt)
                store.upsert_post(post)
                store.replace_comments(post.gallery_id, post.post_no, post.comments)
                collected += 1
        except BlockedError as exc:
            print(f"차단 감지, 여기까지 저장({collected}건): {exc}", file=sys.stderr)
            return 2
    print(f"collected {collected} posts into {args.db}")
    return 0


def _cmd_ingest(args, cfg: Config) -> int:
    posts = JsonlCollector(Path(args.file)).read_posts()
    with Store(Path(args.db)) as store:
        for post in posts:
            post.author = author_hash(post.author, cfg.privacy_salt)
            store.upsert_post(post)
            store.replace_comments(post.gallery_id, post.post_no, post.comments)
    print(f"ingested {len(posts)} posts into {args.db}")
    return 0


def _analyze_period(store: Store, analyzer: Analyzer, trender: TrendAnalyzer | None,
                    gallery: str, start: date, end: date, kinds: list[str]) -> dict[str, dict]:
    run_id, results, coverage = analyzer.run(gallery, start, end, kinds)
    results = dict(results)
    if trender is not None and len(results) >= 2:
        prev_start, prev_end = start - (end - start), start - timedelta(days=1)
        prev = store.latest_analyses(gallery, prev_start, prev_end)
        if prev:
            results["trends"] = trender.diff(
                gallery, prev, {k: v for k, v in results.items() if k != "trends"},
                f"{prev_start}~{prev_end}", f"{start}~{end}")
            import json
            results["trends"] = results["trends"] if isinstance(results["trends"], dict) \
                else json.loads(json.dumps(results["trends"]))
    return results


def _cmd_analyze(args, cfg: Config, llm_factory=None) -> int:
    start, end = _period(args.days)
    with Store(Path(args.db)) as store:
        analyzer = Analyzer(store, (llm_factory or _make_llm)(cfg))
        trender = TrendAnalyzer((llm_factory or _make_llm)(cfg))
        results = _analyze_period(store, analyzer, trender, args.gallery,
                                  start, end, args.kinds.split(","))
        print(f"analyzed {len(results)} kinds: {', '.join(results)}")
    return 0


def _cmd_report(args, cfg: Config, llm_factory=None) -> int:
    start, end = _period(args.days)
    with Store(Path(args.db)) as store:
        analyses = store.latest_analyses(args.gallery, start, end)
        if not analyses:
            print("분석 결과가 없습니다. 먼저 `dch analyze`를 실행하세요.", file=sys.stderr)
            return 1
        top = store.top_posts(args.gallery, start, end)
        md, payload = render_report(args.gallery, start, end, analyses, top, {})
        out = save_report(Path(args.out), args.gallery, start, end, md, payload)
    print(f"report saved: {out}")
    return 0


def _cmd_run(args, cfg: Config, llm_factory=None) -> int:
    if getattr(args, "file", None):
        _cmd_ingest(args, cfg)
    elif args.pages > 0:
        rc = _cmd_collect(args, cfg)
        if rc != 0:
            return rc
    return _cmd_analyze(args, cfg, llm_factory) or _cmd_report(args, cfg, llm_factory)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dch", description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="DC Inside 갤러리 수집")
    p_collect.add_argument("--gallery", required=True)
    p_collect.add_argument("--pages", type=int, default=3)
    p_collect.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_collect.set_defaults(func=_cmd_collect)

    p_ingest = sub.add_parser("ingest", help="JSONL 파일 적재")
    p_ingest.add_argument("--gallery", required=True)
    p_ingest.add_argument("--file", type=Path, required=True)
    p_ingest.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_ingest.set_defaults(func=_cmd_ingest)

    def add_analyze_common(p):
        p.add_argument("--gallery", required=True)
        p.add_argument("--days", type=int, default=7)
        p.add_argument("--db", type=Path, default=Path("data/dch.db"))

    p_analyze = sub.add_parser("analyze", help="LLM 분석 실행")
    add_analyze_common(p_analyze)
    p_analyze.add_argument("--kinds", default=DEFAULT_KINDS)
    p_analyze.set_defaults(func=_cmd_analyze)

    p_report = sub.add_parser("report", help="리포트 생성")
    add_analyze_common(p_report)
    p_report.add_argument("--out", type=Path, default=Path("reports"))
    p_report.set_defaults(func=_cmd_report)

    p_run = sub.add_parser("run", help="수집→분석→리포트 전체 파이프라인")
    add_analyze_common(p_run)
    p_run.add_argument("--pages", type=int, default=3)
    p_run.add_argument("--file", type=Path, default=None,
                       help="지정하면 수집 대신 JSONL 파일을 적재")
    p_run.add_argument("--kinds", default=DEFAULT_KINDS)
    p_run.add_argument("--out", type=Path, default=Path("reports"))
    p_run.set_defaults(func=_cmd_run)
    return parser


def main(argv: list[str] | None = None, *, llm_factory: Callable[[Config], LlmClient] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    func = args.func
    import inspect
    if "llm_factory" in inspect.signature(func).parameters:
        return func(args, cfg, llm_factory=llm_factory)
    return func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/test_cli.py -v` → PASS (필요시 `dch --help`도 수동 확인)

```bash
git add dc_harness/cli.py tests/test_cli.py
git commit -m "feat: cli wiring for collect/ingest/analyze/report/run"
```

---

### Task 13: README + fixture 리프레시 스크립트 + 전체 검증

**Files:**
- Create: `README.md`, `scripts/refresh_fixtures.sh`, `Makefile`
- Test: 전체 `pytest`

**Interfaces:**
- Consumes: 없음 (문서화·운용 스크립트)

- [ ] **Step 1: `README.md` 작성** — 다음 내용을 포함한다:

```markdown
# dc-harness

DC Inside 갤러리별 관심사·여론·트렌드·니즈(VOC)를 분석하는 연구용 하네스.

## 설치
    pip install -e ".[dev]"

## 사용
    export MOTIF_API_KEY=...        # LLM API 키 (필수, 소스에 금지)
    export DC_COOKIES="name1=v1; name2=v2"   # 선택: DC 차단 시 브라우저 쿠키

    dch run --gallery crypto --days 7 --pages 3   # 수집→분석→리포트
    dch ingest --gallery crypto --file dump.jsonl # 파일 기반 대체 수집
    dch report --gallery crypto --days 7          # 리포트 재생성

## 결과
`reports/<gallery>/<start>~<end>.md` (+ 동일 `.json`). 섹션: 요약/토픽/여론/엔티티/VOC/트렌드/인기 게시글/커버리지.

## fixture 리프레시 (스크래퍼 드리프트 대응)
실제 페이지 구조가 바뀌어 파서가 깨지면:
    bash scripts/refresh_fixtures.sh crypto
로 live HTML을 `tests/fixtures/dc/`에 저장하고, 파서를 그 fixture에 맞춰 수정한 뒤 커밋한다. (필요시 DC_COOKIES 사용)

## 연구 윤리
공개 데이터만, 예의적 rate-limit(기본 1.5초+지터), 작성자는 해시 저장, 리포트에 개인정보 미포함. 연구 목적 외 사용 금지.
```

- [ ] **Step 2: `scripts/refresh_fixtures.sh` 작성**

```bash
#!/usr/bin/env bash
# Usage: bash scripts/refresh_fixtures.sh <gallery_id>
# Saves live DC pages as parser fixtures. Uses DC_COOKIES if set.
set -euo pipefail
GALLERY="${1:?usage: refresh_fixtures.sh <gallery_id>}"
OUT="$(dirname "$0")/../tests/fixtures/dc"
mkdir -p "$OUT"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
CURL_OPTS=(-sS -A "$UA")
if [[ -n "${DC_COOKIES:-}" ]]; then CURL_OPTS+=(-H "Cookie: $DC_COOKIES"); fi
curl "${CURL_OPTS[@]}" "https://gall.dcinside.com/board/lists/?id=${GALLERY}&page=1" -o "$OUT/list_page.html"
NO=$(grep -o 'no=[0-9]\+' "$OUT/list_page.html" | head -1 | cut -d= -f2)
if [[ -n "$NO" ]]; then
  curl "${CURL_OPTS[@]}" "https://gall.dcinside.com/board/view/?id=${GALLERY}&no=${NO}" -o "$OUT/post_page.html"
fi
echo "fixtures refreshed in $OUT"
```

- [ ] **Step 3: `Makefile` 작성**

```make
.PHONY: test lint smoke
test:
	pytest -v
lint:
	ruff check dc_harness tests
smoke:  # 실제 API 키 필요. 소규모 라이브 검증
	MOTIF_API_KEY=$${MOTIF_API_KEY:?set MOTIF_API_KEY} dch run --gallery $${GALLERY:-crypto} --days 3 --pages 1
```

- [ ] **Step 4: 전체 검증**

Run: `pytest -v && ruff check dc_harness tests`
Expected: 전부 PASS / lint 경고 0

- [ ] **Step 5: 커밋**

```bash
git add README.md scripts/refresh_fixtures.sh Makefile
git commit -m "docs: readme, fixture refresh procedure and dev targets"
```

---

## Self-Review 결과

1. **Spec 커버리지**: 수집(내장 스크래퍼 Task 6 + JSONL Task 5), 스토어(Task 2), 정규화(Task 3), 보안 가드(Task 4), LLM 클라이언트(Task 7), 청킹(Task 8), 5종 분석(topics/sentiment/entities/voices Task 9, trends Task 10), 리포트(Task 11), CLI(Task 12), 문서·운용(Task 13). Spec의 모든 요구사항 대응 완료.
2. **플레이스홀더 스캔**: "TBD/나중에 구현" 없음. 모든 코드 스텝에 실제 코드 포함.
3. **타입 일관성**: `RawPost(gallery_id, post_no, title, body, author, created_at, views, recommend, comments)` 전 태스크 동일. `Store` 메서드 시그니처 Task 2 정의와 Task 9/12 사용 일치. `LlmClient.chat_json(system, user, max_retries=2)` Task 7 정의와 Task 9/10 스텁 일치. `render_report/save_report` Task 11 정의와 Task 12 사용 일치.
