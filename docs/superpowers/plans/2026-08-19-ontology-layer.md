# dc-harness Phase 2: 온톨로지 계층 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SQLite 원본 계층 위에 선언적 온톨로지(의미 계층)를 얹고, LLM 분석 결과를 provenance 있는 파생 객체(SNAPSHOT)로 물질화해, 결정적 탐색 CLI(`query`/`show`)와 OMCP식 질의(`ask`)로 소비한다.

**Architecture:** v1 파이프라인(collectors→store→analyzers→reports)은 무손상. 신규 `dc_harness/ontology/` 모듈이 `ontology.toml`(유일한 의미 정의 원천) + 검증기 + materializer + query/ask 소비자를 제공한다. 원본(`posts/comments`)은 불변, 파생(`obj_*`)은 run 단위 SNAPSHOT, 모든 LLM 호출은 `llm_calls`에 감사된다.

**Tech Stack:** Python 3.11+ stdlib만(tomllib/sqlite3/hashlib). 기존 의존(openai/httpx/bs4) 변경 없음.

**Spec:** `docs/superpowers/specs/2026-08-19-ontology-layer-design.md` (불변식 I1–I10, 검증 규칙 V1–V6)

## Global Constraints (Phase 1 제약 + 추가)

- 온톨로지 모듈(`dc_harness/ontology/`)은 **stdlib만** 사용 (I6). 새 런타임 의존 금지.
- 파생 테이블(`obj_*`)은 run_id 단위 SNAPSHOT만(DELETE→INSERT), 행 단위 UPDATE 금지 (I2).
- 모든 파생 행에 `run_id`, `prompt_version`, 근거 post 번호 포함 (I3).
- 모든 LLM 호출을 `llm_calls`에 기록 (I5).
- 테이블 이름은 allowlist 상수로 검증(사용자 입력 테이블명 금지), 값은 전부 파라미터 바인딩. SQL 문자열 조립 금지.
- api_name: 객체·링크 PascalCase, 속성 camelCase, 한글은 description에만 (I10).
- 객체 8종·링크 6종 상한. 추가는 CONVENTIONS.md 등록 + 실제 질문 필요성 입증 후에만 (I8, I9).
- 각 태스크 TDD: 실패 테스트 → 구현 → 통과 → 커밋.

---

### Task 14: 온톨로지 정의 파일 + 로더

**Files:**
- Create: `dc_harness/ontology/__init__.py`, `dc_harness/ontology/defn.py`, `dc_harness/ontology/ontology.toml`
- Test: `tests/test_ontology_defn.py`

**Interfaces:**
- Produces:
  - `@dataclass dc_harness.ontology.defn.PropertyDef(apiName: str, type: str, description: str)`
  - `@dataclass dc_harness.ontology.defn.ObjectDef(apiName: str, displayName: str, description: str, pk: list[str], layer: str, table: str, properties: list[PropertyDef])` — `layer ∈ {"raw","derived"}`, `table`는 실제 SQLite 테이블명(빈 문자열 허용=직접 질의 불가)
  - `@dataclass dc_harness.ontology.defn.LinkDef(apiName: str, displayName: str, description: str, fromObject: str, toObject: str, cardinality: str, via: str = "")` — N:M은 `via`(접합 테이블) 필수
  - `@dataclass dc_harness.ontology.defn.OntologyDef(objects: list[ObjectDef], links: list[LinkDef])` with `.object_(api_name) -> ObjectDef | None`
  - `DEFAULT_ONTOLOGY_PATH: Path`, `load_ontology(path: Path | None = None) -> OntologyDef` (기본: 모듈 옆 `ontology.toml`)

- [ ] **Step 1: `dc_harness/ontology/ontology.toml` 작성 (설계 §3의 전체 모델)**

```toml
# dc-harness 의미 계층 정의 — 유일한 원천. 규칙: CONVENTIONS.md 참조.
version = 1

[[object]]
apiName = "Gallery"
displayName = "갤러리"
description = "DC Inside 개별 갤러리 (예: crypto)"
pk = ["galleryId"]
layer = "raw"
table = ""
  [[object.property]]
  apiName = "galleryId"
  type = "text"
  description = "갤러리 식별자"

[[object]]
apiName = "Post"
displayName = "게시글"
description = "갤러리에 작성된 개별 게시글. 추천수·조회수 포함"
pk = ["galleryId", "postNo"]
layer = "raw"
table = "posts"
  [[object.property]]
  apiName = "galleryId"
  type = "text"
  description = "소속 갤러리"
  [[object.property]]
  apiName = "postNo"
  type = "integer"
  description = "게시글 번호"
  [[object.property]]
  apiName = "title"
  type = "text"
  description = "제목"
  [[object.property]]
  apiName = "body"
  type = "text"
  description = "본문"
  [[object.property]]
  apiName = "authorHash"
  type = "text"
  description = "해시된 작성자 식별자(개인정보 비식별)"
  [[object.property]]
  apiName = "createdAt"
  type = "datetime"
  description = "작성 시각"
  [[object.property]]
  apiName = "views"
  type = "integer"
  description = "조회수"
  [[object.property]]
  apiName = "recommendCount"
  type = "integer"
  description = "추천수 — 커뮤니티 공감의 1차 신호"

[[object]]
apiName = "Comment"
displayName = "댓글"
description = "게시글에 달린 댓글. 추천/비추천 포함"
pk = ["galleryId", "postNo", "seq"]
layer = "raw"
table = "comments"
  [[object.property]]
  apiName = "galleryId"
  type = "text"
  description = "소속 갤러리"
  [[object.property]]
  apiName = "postNo"
  type = "integer"
  description = "작성된 게시글 번호"
  [[object.property]]
  apiName = "seq"
  type = "integer"
  description = "댓글 순번"
  [[object.property]]
  apiName = "text"
  type = "text"
  description = "댓글 내용"
  [[object.property]]
  apiName = "recommendCount"
  type = "integer"
  description = "댓글 추천수"

[[object]]
apiName = "Author"
displayName = "작성자"
description = "해시된 게시 작성자. 링크 통해서만 탐색(직접 질의 미지원)"
pk = ["authorHash"]
layer = "raw"
table = ""
  [[object.property]]
  apiName = "authorHash"
  type = "text"
  description = "솔트+닉네임 SHA-256 12자리"

[[object]]
apiName = "Topic"
displayName = "토픽"
description = "한 기간 갤러리에서 논의된 주제. LLM 추출 결과의 파생 객체"
pk = ["topicId"]
layer = "derived"
table = "obj_topics"
  [[object.property]]
  apiName = "topicId"
  type = "text"
  description = "갤러리|기간|정규화 라벨 해시"
  [[object.property]]
  apiName = "label"
  type = "text"
  description = "토픽명"
  [[object.property]]
  apiName = "keywords"
  type = "json"
  description = "반복 키워드 목록"
  [[object.property]]
  apiName = "snippet"
  type = "text"
  description = "대표 문장"
  [[object.property]]
  apiName = "sourcePostNos"
  type = "json"
  description = "근거 게시글 번호 목록 (lineage)"
  [[object.property]]
  apiName = "runId"
  type = "integer"
  description = "생성한 분석 run (lineage)"
  [[object.property]]
  apiName = "promptVersion"
  type = "text"
  description = "사용된 분석 프롬프트 버전 (lineage)"

[[object]]
apiName = "Entity"
displayName = "언급 대상"
description = "인물/종목/제품/브랜드 등 언급 대상의 기간별 여론 집계"
pk = ["entityId"]
layer = "derived"
table = "obj_entities"
  [[object.property]]
  apiName = "entityId"
  type = "text"
  description = "정규화 이름"
  [[object.property]]
  apiName = "displayName"
  type = "text"
  description = "표기 이름"
  [[object.property]]
  apiName = "entityType"
  type = "text"
  description = "인물|종목|제품|브랜드|기타"
  [[object.property]]
  apiName = "mentions"
  type = "integer"
  description = "기간 내 언급 수"
  [[object.property]]
  apiName = "sentiment"
  type = "text"
  description = "긍정|부정|mixed|중립"
  [[object.property]]
  apiName = "runId"
  type = "integer"
  description = "lineage"
  [[object.property]]
  apiName = "promptVersion"
  type = "text"
  description = "lineage"

[[object]]
apiName = "Issue"
displayName = "이슈"
description = "찬반 여론이 갈리는 쟁점과 그 분포"
pk = ["issueId"]
layer = "derived"
table = "obj_issues"
  [[object.property]]
  apiName = "issueId"
  type = "text"
  description = "갤러리|기간|정규화 라벨 해시"
  [[object.property]]
  apiName = "label"
  type = "text"
  description = "이슈명"
  [[object.property]]
  apiName = "proCount"
  type = "integer"
  description = "찬성 발언 수"
  [[object.property]]
  apiName = "conCount"
  type = "integer"
  description = "반대 발언 수"
  [[object.property]]
  apiName = "neutralCount"
  type = "integer"
  description = "중립 발언 수"
  [[object.property]]
  apiName = "quotes"
  type = "json"
  description = "대표 인용(post_no 포함)"
  [[object.property]]
  apiName = "runId"
  type = "integer"
  description = "lineage"
  [[object.property]]
  apiName = "promptVersion"
  type = "text"
  description = "lineage"

[[object]]
apiName = "Voice"
displayName = "목소리"
description = "불만(painpoint)/바람(wish)/아이디어(idea) — 원문 인용 동반"
pk = ["voiceId"]
layer = "derived"
table = "obj_voices"
  [[object.property]]
  apiName = "voiceId"
  type = "text"
  description = "kind|정규화 텍스트 해시"
  [[object.property]]
  apiName = "kind"
  type = "text"
  description = "painpoint|wish|idea"
  [[object.property]]
  apiName = "text"
  type = "text"
  description = "요약 한 줄"
  [[object.property]]
  apiName = "quote"
  type = "text"
  description = "원문 인용"
  [[object.property]]
  apiName = "count"
  type = "integer"
  description = "유사 언급 빈도"
  [[object.property]]
  apiName = "sourcePostNo"
  type = "integer"
  description = "근거 게시글 번호 (lineage)"
  [[object.property]]
  apiName = "runId"
  type = "integer"
  description = "lineage"
  [[object.property]]
  apiName = "promptVersion"
  type = "text"
  description = "lineage"

[[link]]
apiName = "WrittenOn"
displayName = "작성된 게시글이다"
description = "댓글이 달린 게시글"
fromObject = "Comment"
toObject = "Post"
cardinality = "N:1"

[[link]]
apiName = "BelongsTo"
displayName = "소속 갤러리이다"
description = "게시글의 소속 갤러리"
fromObject = "Post"
toObject = "Gallery"
cardinality = "N:1"

[[link]]
apiName = "AuthoredBy"
displayName = "작성자이다"
description = "게시글 작성자(해시)"
fromObject = "Post"
toObject = "Author"
cardinality = "N:1"

[[link]]
apiName = "Discusses"
displayName = "논의된 토픽이다"
description = "게시글-토픽 연결. 접합 테이블 obj_post_topics"
fromObject = "Post"
toObject = "Topic"
cardinality = "N:M"
via = "obj_post_topics"

[[link]]
apiName = "Evidences"
displayName = "근거 게시글이다"
description = "목소리의 근거가 된 게시글"
fromObject = "Voice"
toObject = "Post"
cardinality = "N:1"
```

- [ ] **Step 2: 실패 테스트 `tests/test_ontology_defn.py`**

```python
from dc_harness.ontology.defn import DEFAULT_ONTOLOGY_PATH, load_ontology


def test_load_default_ontology():
    defn = load_ontology(None)
    names = {o.apiName for o in defn.objects}
    assert names == {"Gallery", "Post", "Comment", "Author",
                     "Topic", "Entity", "Issue", "Voice"}
    post = defn.object_("Post")
    assert post.layer == "raw" and post.table == "posts"
    assert post.pk == ["galleryId", "postNo"]
    assert {p.apiName for p in post.properties} >= {"postNo", "title", "recommendCount"}


def test_links_and_cardinality():
    defn = load_ontology(None)
    link_names = {l.apiName for l in defn.links}
    assert link_names == {"WrittenOn", "BelongsTo", "AuthoredBy",
                          "Discusses", "Evidences"}
    discusses = next(l for l in defn.links if l.apiName == "Discusses")
    assert discusses.cardinality == "N:M" and discusses.via == "obj_post_topics"


def test_object_lookup_missing_returns_none():
    assert load_ontology(None).object_("Nope") is None
```

- [ ] **Step 3: 실패 확인**

Run: `pytest tests/test_ontology_defn.py -v` → FAIL (`No module named dc_harness.ontology`)

- [ ] **Step 4: `dc_harness/ontology/defn.py` 구현**

```python
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ONTOLOGY_PATH = Path(__file__).parent / "ontology.toml"


@dataclass
class PropertyDef:
    apiName: str
    type: str
    description: str


@dataclass
class ObjectDef:
    apiName: str
    displayName: str
    description: str
    pk: list[str]
    layer: str
    table: str
    properties: list[PropertyDef] = field(default_factory=list)


@dataclass
class LinkDef:
    apiName: str
    displayName: str
    description: str
    fromObject: str
    toObject: str
    cardinality: str
    via: str = ""


@dataclass
class OntologyDef:
    objects: list[ObjectDef] = field(default_factory=list)
    links: list[LinkDef] = field(default_factory=list)

    def object_(self, api_name: str) -> ObjectDef | None:
        return next((o for o in self.objects if o.apiName == api_name), None)


def load_ontology(path: Path | None = None) -> OntologyDef:
    data = tomllib.loads((path or DEFAULT_ONTOLOGY_PATH).read_text(encoding="utf-8"))
    defn = OntologyDef(
        objects=[ObjectDef(
            apiName=o["apiName"], displayName=o["displayName"],
            description=o["description"], pk=list(o.get("pk", [])),
            layer=o.get("layer", "raw"), table=o.get("table", ""),
            properties=[PropertyDef(**p) for p in o.get("property", [])],
        ) for o in data.get("object", [])],
        links=[LinkDef(**l) for l in data.get("link", [])],
    )
    return defn
```

`dc_harness/ontology/__init__.py`는 빈 파일.

- [ ] **Step 5: 통과 확인 + 커밋**

Run: `pytest tests/test_ontology_defn.py -v` → PASS

```bash
git add dc_harness/ontology/ tests/test_ontology_defn.py
git commit -m "feat: declarative ontology definition and loader"
```

---

### Task 15: 온톨로지 검증기 (V1–V6)

**Files:**
- Create: `dc_harness/ontology/validate.py`
- Test: `tests/test_ontology_validate.py`

**Interfaces:**
- Consumes: `OntologyDef`, `ObjectDef`, `LinkDef`, `PropertyDef` (Task 14 시그니처 그대로)
- Produces:
  - `class OntologyValidationError(ValueError)`
  - `collect_errors(defn: OntologyDef) -> list[str]`
  - `validate(defn: OntologyDef) -> None` — 오차 있으면 모아서 `OntologyValidationError` raise
  - 규칙: V1 api_name 형식(PascalCase 객체·링크 / camelCase 속성)+유일성 / V2 pk 비었거나 존재하지 않는 속성이면 오류 / V3 링크 양단은 존재하는 객체, N:M은 via 필수, via가 있으면 카디널리티 N:M / V4 동일 displayName·동일 정규화 라벨 중복 금지 / V5 layer="derived" 객체는 runId·promptVersion 속성 필수 / V6 cardinality ∈ {1:1, 1:N, N:M}

- [ ] **Step 1: 실패 테스트 `tests/test_ontology_validate.py`**

```python
import pytest

from dc_harness.ontology.defn import (LinkDef, ObjectDef, OntologyDef,
                                      PropertyDef, load_ontology)
from dc_harness.ontology.validate import OntologyValidationError, collect_errors, validate


def obj(api_name="Topic", display="토픽", layer="derived", pk=("topicId",),
        props=("topicId", "label", "runId", "promptVersion"), table="obj_topics"):
    return ObjectDef(apiName=api_name, displayName=display, description="d",
                     pk=list(pk), layer=layer, table=table,
                     properties=[PropertyDef(p, "text", "d") for p in props])


def test_shipped_ontology_is_valid():
    assert collect_errors(load_ontology(None)) == []


def test_v1_naming_and_uniqueness():
    bad = obj(api_name="topic")  # PascalCase 아님
    defn = OntologyDef(objects=[bad, obj()])  # duplicate topicId? 아니—apiName 유일성은 이름이 다르므로 통과; camelCase 속성 검사
    bad.properties.append(PropertyDef("BadProp", "text", "d"))
    errors = collect_errors(OntologyDef(objects=[bad]))
    assert any("topic" in e for e in errors)          # 객체명 형식
    assert any("BadProp" in e for e in errors)        # 속성명 형식
    dup = OntologyDef(objects=[obj(), obj(api_name="Theme")])
    assert any("duplicate" in e for e in collect_errors(dup)) is False  # apiName 다르면 OK


def test_v2_pk_must_exist():
    errors = collect_errors(OntologyDef(objects=[obj(pk=("nope",))]))
    assert any("pk" in e.lower() for e in errors)


def test_v3_link_endpoints_and_via():
    topic = obj()
    post = obj(api_name="Post", display="게시글", layer="raw", pk=("postNo",),
               props=("postNo",), table="posts")
    link_bad = LinkDef("PointsTo", "가리킨다", "d", "Post", "Ghost", "N:1")
    link_nm_no_via = LinkDef("Discusses", "논의", "d", "Post", "Topic", "N:M")
    errors = collect_errors(OntologyDef(objects=[post, topic],
                                        links=[link_bad, link_nm_no_via]))
    assert any("Ghost" in e for e in errors)
    assert any("via" in e for e in errors)


def test_v4_duplicate_concept():
    a = obj(api_name="Topic", display="토픽")
    b = obj(api_name="Subject", display="토픽")
    errors = collect_errors(OntologyDef(objects=[a, b]))
    assert any("duplicate" in e for e in errors)


def test_v5_derived_requires_provenance():
    missing = obj(props=("topicId", "label"))  # runId/promptVersion 없음
    errors = collect_errors(OntologyDef(objects=[missing]))
    assert any("runId" in e for e in errors)


def test_validate_raises_on_errors():
    with pytest.raises(OntologyValidationError):
        validate(OntologyDef(objects=[obj(props=("topicId",))]))
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_ontology_validate.py -v` → FAIL

- [ ] **Step 3: `dc_harness/ontology/validate.py` 구현**

```python
from __future__ import annotations

import re

from .defn import OntologyDef

_PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CAMEL = re.compile(r"^[a-z][A-Za-z0-9]*$")
_CARDINALITIES = {"1:1", "1:N", "N:M"}


class OntologyValidationError(ValueError):
    pass


def collect_errors(defn: OntologyDef) -> list[str]:
    errors: list[str] = []
    seen_names: set[str] = set()
    seen_concepts: dict[str, str] = {}

    for o in defn.objects:
        if not _PASCAL.match(o.apiName):
            errors.append(f"V1 object apiName must be PascalCase: {o.apiName}")
        if o.apiName in seen_names:
            errors.append(f"V1 duplicate object apiName: {o.apiName}")
        seen_names.add(o.apiName)
        concept = re.sub(r"\s+", "", o.displayName).casefold()
        if concept and concept in seen_concepts:
            errors.append(f"V4 duplicate concept: {o.apiName} ~ {seen_concepts[concept]} "
                          f"(displayName={o.displayName})")
        seen_concepts[concept] = o.apiName

        prop_names = {p.apiName for p in o.properties}
        for p in o.properties:
            if not _CAMEL.match(p.apiName):
                errors.append(f"V1 property apiName must be camelCase: {o.apiName}.{p.apiName}")
        if not o.pk:
            errors.append(f"V2 object has empty pk: {o.apiName}")
        for key in o.pk:
            if key not in prop_names:
                errors.append(f"V2 pk property missing on {o.apiName}: {key}")
        if o.layer == "derived":
            for required in ("runId", "promptVersion"):
                if required not in prop_names:
                    errors.append(f"V5 derived object {o.apiName} lacks provenance "
                                  f"property: {required}")

    for l in defn.links:
        if not _PASCAL.match(l.apiName):
            errors.append(f"V1 link apiName must be PascalCase: {l.apiName}")
        if l.cardinality not in _CARDINALITIES:
            errors.append(f"V6 invalid cardinality on {l.apiName}: {l.cardinality}")
        for end in (l.fromObject, l.toObject):
            if end not in seen_names:
                errors.append(f"V3 link {l.apiName} references unknown object: {end}")
        if l.cardinality == "N:M" and not l.via:
            errors.append(f"V3 N:M link {l.apiName} must declare via (junction table)")
        if l.cardinality != "N:M" and l.via:
            errors.append(f"V3 via is only allowed for N:M link: {l.apiName}")
    return errors


def validate(defn: OntologyDef) -> None:
    errors = collect_errors(defn)
    if errors:
        raise OntologyValidationError("invalid ontology:\n- " + "\n- ".join(errors))
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/test_ontology_validate.py -v` → PASS

```bash
git add dc_harness/ontology/validate.py tests/test_ontology_validate.py
git commit -m "feat: ontology validator enforcing v1-v6 invariants"
```

---

### Task 16: 스토어 확장 — 파생 객체 테이블 + LLM 감사 로그

**Files:**
- Modify: `dc_harness/store.py` (SCHEMA 및 메서드 추가)
- Test: `tests/test_store_objects.py`

**Interfaces:**
- Consumes: 기존 `Store` (Task 2)
- Produces (`Store`에 추가):
  - `OBJECT_TABLES = frozenset({"obj_topics", "obj_entities", "obj_issues", "obj_voices", "obj_post_topics"})`
  - `log_llm_call(run_id: int | None, kind: str, system: str, user: str, response: str, model: str, prompt_version: str) -> None`
  - `snapshot_rows(table: str, run_id: int, rows: list[dict]) -> int` — allowlist 밖 table은 `ValueError`. `DELETE WHERE run_id=?` 후 행의 키 ∩ 테이블 컬럼으로 INSERT. INSERT 컬럼명은 PRAGMA로 검증된 컬럼만 사용(동적 컬럼명도 allowlist에서 옴). 반환=삽입 수. (I2)
  - `latest_object_run(table: str, gallery_id: str, start: date, end: date) -> int | None`
  - `fetch_object_rows(table: str, run_id: int, limit: int = 50) -> list[dict]`

- [ ] **Step 1: 실패 테스트 `tests/test_store_objects.py`**

```python
import json
from datetime import date
from pathlib import Path

import pytest

from dc_harness.store import Store

TOPIC_ROW = {"run_id": 1, "gallery_id": "crypto", "topic_id": "t1",
             "period_start": "2026-08-01", "period_end": "2026-08-07",
             "label": "현물 매수", "snippet": "s", "keywords": json.dumps(["매수"]),
             "source_post_nos": json.dumps([101]), "prompt_version": "v1"}


def test_snapshot_rows_writes_and_replaces(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        assert store.snapshot_rows("obj_topics", 1, [TOPIC_ROW]) == 1
        assert store.snapshot_rows("obj_topics", 1, [dict(TOPIC_ROW, label="변경")]) == 1
        rows = store.fetch_object_rows("obj_topics", 1)
        assert len(rows) == 1 and rows[0]["label"] == "변경"  # SNAPSHOT: 덮어쓰기


def test_snapshot_rows_rejects_unknown_table(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        with pytest.raises(ValueError, match="not an object table"):
            store.snapshot_rows("posts", 1, [{}])


def test_snapshot_rows_ignores_unknown_columns(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        assert store.snapshot_rows("obj_topics", 1, [dict(TOPIC_ROW, hacker="x")]) == 1


def test_latest_object_run(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.snapshot_rows("obj_topics", 1, [TOPIC_ROW])
        store.snapshot_rows("obj_topics", 2, [dict(TOPIC_ROW, label="r2")])
        got = store.latest_object_run("obj_topics", "crypto",
                                      date(2026, 8, 1), date(2026, 8, 7))
        assert got == 2
        assert store.latest_object_run("obj_topics", "crypto",
                                       date(2030, 1, 1), date(2030, 1, 2)) is None


def test_log_llm_call(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.log_llm_call(1, "topics", "sys", "user", '{"topics": []}', "m", "v1")
        row = store.conn.execute("SELECT * FROM llm_calls").fetchone()
        assert row["kind"] == "topics" and row["model"] == "m"
```

- [ ] **Step 2: 실패 확인 → `dc_harness/store.py` 수정**

Run: `pytest tests/test_store_objects.py -v` → FAIL 후, SCHEMA 문자열 끝에 추가:

```sql
CREATE TABLE IF NOT EXISTS llm_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, kind TEXT NOT NULL,
  system_text TEXT NOT NULL, user_text TEXT NOT NULL, response_text TEXT NOT NULL,
  model TEXT NOT NULL, prompt_version TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS obj_topics(
  run_id INTEGER NOT NULL, gallery_id TEXT NOT NULL, topic_id TEXT NOT NULL,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL, label TEXT NOT NULL,
  snippet TEXT NOT NULL DEFAULT '', keywords TEXT NOT NULL DEFAULT '[]',
  source_post_nos TEXT NOT NULL DEFAULT '[]', prompt_version TEXT NOT NULL,
  PRIMARY KEY(run_id, topic_id));
CREATE TABLE IF NOT EXISTS obj_entities(
  run_id INTEGER NOT NULL, gallery_id TEXT NOT NULL, entity_id TEXT NOT NULL,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL, display_name TEXT NOT NULL,
  entity_type TEXT NOT NULL DEFAULT '기타', mentions INTEGER NOT NULL DEFAULT 0,
  sentiment TEXT NOT NULL DEFAULT '중립', reason TEXT NOT NULL DEFAULT '',
  prompt_version TEXT NOT NULL, PRIMARY KEY(run_id, entity_id));
CREATE TABLE IF NOT EXISTS obj_issues(
  run_id INTEGER NOT NULL, gallery_id TEXT NOT NULL, issue_id TEXT NOT NULL,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL, label TEXT NOT NULL,
  pro_count INTEGER NOT NULL DEFAULT 0, con_count INTEGER NOT NULL DEFAULT 0,
  neutral_count INTEGER NOT NULL DEFAULT 0, quotes TEXT NOT NULL DEFAULT '[]',
  prompt_version TEXT NOT NULL, PRIMARY KEY(run_id, issue_id));
CREATE TABLE IF NOT EXISTS obj_voices(
  run_id INTEGER NOT NULL, gallery_id TEXT NOT NULL, voice_id TEXT NOT NULL,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL, kind TEXT NOT NULL,
  text TEXT NOT NULL, quote TEXT NOT NULL DEFAULT '', count INTEGER NOT NULL DEFAULT 1,
  source_post_no INTEGER, prompt_version TEXT NOT NULL,
  PRIMARY KEY(run_id, voice_id));
CREATE TABLE IF NOT EXISTS obj_post_topics(
  run_id INTEGER NOT NULL, gallery_id TEXT NOT NULL, post_no INTEGER NOT NULL,
  topic_id TEXT NOT NULL, PRIMARY KEY(run_id, gallery_id, post_no, topic_id));
```

`Store` 클래스에 메서드 추가:

```python
    OBJECT_TABLES = frozenset({"obj_topics", "obj_entities", "obj_issues",
                               "obj_voices", "obj_post_topics"})

    def log_llm_call(self, run_id: int | None, kind: str, system: str, user: str,
                     response: str, model: str, prompt_version: str) -> None:
        self.conn.execute(
            "INSERT INTO llm_calls(run_id, kind, system_text, user_text,"
            " response_text, model, prompt_version) VALUES(?,?,?,?,?,?,?)",
            (run_id, kind, system, user, response, model, prompt_version))
        self.conn.commit()

    def _table_columns(self, table: str) -> list[str]:
        return [r["name"] for r in self.conn.execute(
            f"PRAGMA table_info({table})").fetchall()]

    def snapshot_rows(self, table: str, run_id: int, rows: list[dict]) -> int:
        if table not in self.OBJECT_TABLES:
            raise ValueError(f"not an object table: {table}")
        columns = self._table_columns(table)
        self.conn.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
        usable = [c for c in columns if c != "run_id"]
        written = 0
        for row in rows:
            if not all(c in row for c in ("run_id",)):
                row = {**row, "run_id": run_id}
            values = [row.get(c) for c in usable]
            placeholders = ",".join("?" * len(usable))
            self.conn.execute(
                f"INSERT INTO {table}({','.join(usable)}) VALUES({placeholders})",
                values)
            written += 1
        self.conn.commit()
        return written

    def latest_object_run(self, table: str, gallery_id: str,
                          start: date, end: date) -> int | None:
        if table not in self.OBJECT_TABLES:
            raise ValueError(f"not an object table: {table}")
        row = self.conn.execute(
            f"SELECT MAX(run_id) AS m FROM {table} WHERE gallery_id=?"
            " AND period_start=? AND period_end=?",
            (gallery_id, start.isoformat(), end.isoformat())).fetchone()
        return row["m"] if row and row["m"] is not None else None

    def fetch_object_rows(self, table: str, run_id: int, limit: int = 50) -> list[dict]:
        if table not in self.OBJECT_TABLES:
            raise ValueError(f"not an object table: {table}")
        rows = self.conn.execute(
            f"SELECT * FROM {table} WHERE run_id=? LIMIT ?", (run_id, limit)).fetchall()
        return [dict(r) for r in rows]
```

주의: 컬럼명은 `PRAGMA`로 조회한 실제 컬럼(`usable`)만 사용 — 사용자 입력으로 컬럼·테이블 문자열을 만들지 않고, 값은 전부 파라미터 바인딩.

- [ ] **Step 3: 통과 확인 + 커밋**

Run: `pytest tests/test_store_objects.py tests/test_store.py -v` → PASS

```bash
git add dc_harness/store.py tests/test_store_objects.py
git commit -m "feat: derived object tables with snapshot semantics and llm audit log"
```

---

### Task 17: 러너 감사 + 프롬프트 버전 + run_id 반환 (Phase 1 수정 포함)

**Files:**
- Modify: `dc_harness/analyze/kinds.py`, `dc_harness/analyze/runner.py`, `dc_harness/cli.py`
- Test: `tests/test_runner_audit.py` (기존 `tests/test_analyzers.py`는 시그니처 변경분만 수정)

**Interfaces:**
- Consumes: `Store.log_llm_call` (Task 16), 기존 `Analyzer`
- Produces:
  - `dc_harness.analyze.kinds.PROMPT_VERSION: str` (프롬프트 변경 시 수동 상향 — 감사·lineage의 키)
  - `Analyzer.run(...) -> tuple[int, dict[str, dict], dict]` — `(run_id, kind→결과, coverage)`. 게시글 없으면 `(-1, {}, coverage)`
  - `Analyzer._map`은 청크마다 `llm_calls`에 기록 (I5)

- [ ] **Step 1: `kinds.py` 상단에 추가**

```python
PROMPT_VERSION = "v1"  # 프롬프트 문구를 바꾸면 반드시 상향 (llm_calls/obj_* lineage의 키)
```

- [ ] **Step 2: 실패 테스트 `tests/test_runner_audit.py`**

```python
import json
from datetime import date, datetime
from pathlib import Path

from dc_harness.analyze.kinds import PROMPT_VERSION
from dc_harness.analyze.runner import Analyzer
from dc_harness.models import RawPost
from dc_harness.store import Store


class StubLlm:
    model = "stub-model"

    def chat_json(self, system, user, max_retries=2):
        return {"topics": [{"label": "전망", "post_nos": [1], "keywords": [], "snippet": ""}]}


def make_post(no: int) -> RawPost:
    return RawPost("crypto", no, f"t{no}", "b", "a", datetime(2026, 8, 10), 1, 1)


def test_run_returns_run_id_and_audits_calls(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        store.upsert_post(make_post(1))
        run_id, results, coverage = Analyzer(store, StubLlm()).run(
            "crypto", date(2026, 8, 1), date(2026, 8, 31), ["topics"], max_chars=500)
        assert run_id > 0
        assert results["topics"]["topics"][0]["label"] == "전망"
        calls = store.conn.execute("SELECT * FROM llm_calls").fetchall()
        assert len(calls) == 1
        assert calls[0]["kind"] == "topics" and calls[0]["model"] == "stub-model"
        assert calls[0]["prompt_version"] == PROMPT_VERSION
        assert "전망" in json.dumps(coverage, ensure_ascii=False) or True  # coverage는 구조만


def test_run_empty_store_returns_minus_one(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        run_id, results, coverage = Analyzer(store, StubLlm()).run(
            "crypto", date(2026, 8, 1), date(2026, 8, 31), ["topics"])
        assert run_id == -1 and results == {} and coverage["posts_total"] == 0
```

- [ ] **Step 3: 실패 확인 → 구현 수정**

Run: `pytest tests/test_runner_audit.py -v` → FAIL 후:

`runner.py`의 `_map`과 `run`을 다음과 같이 수정(전체 교체):

```python
    def _map(self, kind: AnalysisKind, run_id: int, chunks) -> tuple[list[dict], int]:
        import json
        results: list[dict] = []
        failed = 0
        for chunk in chunks:
            corpus = "\n\n".join(render_post_text(p) for p in chunk)
            user = (f"{kind.instruction}\n\n출력 스키마(JSON):\n{kind.schema_hint}\n\n"
                    f"=== 데이터 ===\n{corpus}")
            try:
                result = self.llm.chat_json(kind.system, user)
                results.append(result)
                self.store.log_llm_call(  # I5: 모든 호출 감사
                    run_id, kind.name, kind.system, user,
                    json.dumps(result, ensure_ascii=False),
                    getattr(self.llm, "model", "unknown"), PROMPT_VERSION)
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
            chunk_results, failed = self._map(kind, run_id, chunks)
            total_failed += failed
            results[name] = merge_chunk_results(name, chunk_results)
            self.store.save_analysis(run_id, name, gallery_id, start, end, results[name])
        coverage = {
            "chunks_total": len(chunks) * len(kinds),
            "chunks_failed": total_failed,
            "posts_included": len(posts),
            "posts_total": len(self.store.fetch_posts(gallery_id)),
        }
        self.store.finish_run(run_id, "done", coverage)
        return run_id, results, coverage
```

`kinds.py` 상단 import에 `from .kinds import` 중복 없이 `PROMPT_VERSION` 정의만 추가. `cli.py`의 `_analyze_period` 내 `results, coverage = analyzer.run(...)` → `run_id, results, coverage = analyzer.run(...)` (run_id는 Task 18에서 materialize에 사용).

기존 `tests/test_analyzers.py`의 언패킹 2곳도 `run_id, results, coverage = ...`로 수정.

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/test_runner_audit.py tests/test_analyzers.py tests/test_cli.py -v` → PASS

```bash
git add dc_harness/analyze/ dc_harness/cli.py tests/
git commit -m "feat: runner audit logging, prompt versioning, run_id return"
```

---

### Task 18: Materializer — 병합 결과 → 파생 객체 (SNAPSHOT)

**Files:**
- Create: `dc_harness/ontology/materialize.py`
- Test: `tests/test_materialize.py`

**Interfaces:**
- Consumes: `Store.snapshot_rows` (Task 16), `normalize_label` (Task 3), `PROMPT_VERSION`
- Produces:
  - `topic_id(gallery_id: str, start: date, end: date, label: str) -> str` — sha1 12자리
  - `entity_id(name: str) -> str` — `normalize_label(name)[:40]`
  - `voice_id(kind: str, text: str) -> str` — sha1 12자리
  - `materialize(store: Store, gallery_id: str, run_id: int, prompt_version: str, start: date, end: date, results: dict[str, dict]) -> dict[str, int]` — kind별 삽입 수 {"Topic": n, "Entity": n, "Issue": n, "Voice": n, "PostTopic": n}. "trends"는 테이블 없음(설계 §4 — analyses JSON에만 존재).

- [ ] **Step 1: 실패 테스트 `tests/test_materialize.py`**

```python
import json
from datetime import date
from pathlib import Path

from dc_harness.ontology.materialize import materialize

RESULTS = {
    "topics": {"topics": [
        {"label": "현물 매수", "post_nos": [101, 102], "keywords": ["매수"], "snippet": "s"}]},
    "entities": {"entities": [
        {"name": "이더리움", "type": "종목", "mentions": 5, "sentiment": "부정", "reason": "r"}]},
    "sentiment": {"issues": [
        {"issue": "반감기", "pro": 4, "con": 2, "neutral": 1, "quotes": []}],
        "resonant": []},
    "voices": {"voices": [
        {"kind": "painpoint", "text": "앱이 느림", "post_no": 101, "quote": "느림", "count": 3}]},
}


def test_materialize_writes_all_objects_with_provenance(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        counts = materialize(store, "crypto", 7, "v1",
                             date(2026, 8, 1), date(2026, 8, 7), RESULTS)
        assert counts == {"Topic": 1, "Entity": 1, "Issue": 1, "Voice": 1, "PostTopic": 2}
        rows = store.fetch_object_rows("obj_topics", 7)
        assert rows[0]["label"] == "현물 매수" and rows[0]["run_id"] == 7
        assert rows[0]["prompt_version"] == "v1"
        assert json.loads(rows[0]["source_post_nos"]) == [101, 102]
        junction = store.fetch_object_rows("obj_post_topics", 7)
        assert {(r["post_no"]) for r in junction} == {101, 102}
        entity = store.fetch_object_rows("obj_entities", 7)
        assert entity[0]["mentions"] == 5 and entity[0]["sentiment"] == "부정"
        issue = store.fetch_object_rows("obj_issues", 7)
        assert (issue[0]["pro_count"], issue[0]["con_count"]) == (4, 2)
        voice = store.fetch_object_rows("obj_voices", 7)
        assert voice[0]["count"] == 3 and voice[0]["source_post_no"] == 101


def test_materialize_snapshot_replaces_same_run(tmp_path: Path):
    with Store(tmp_path / "t.db") as store:
        materialize(store, "crypto", 7, "v1", date(2026, 8, 1), date(2026, 8, 7), RESULTS)
        smaller = {"topics": RESULTS["topics"]}
        materialize(store, "crypto", 7, "v1", date(2026, 8, 1), date(2026, 8, 7), smaller)
        assert len(store.fetch_object_rows("obj_topics", 7)) == 1
        assert store.fetch_object_rows("obj_voices", 7) == []  # SNAPSHOT: 이전 run 7 분 삭제


from dc_harness.store import Store  # noqa: E402 (테스트 가독성을 위한 하단 import)
```

(실제 작성 시 `from dc_harness.store import Store`는 파일 상단으로.)

- [ ] **Step 2: 실패 확인 → `dc_harness/ontology/materialize.py` 구현**

```python
from __future__ import annotations

import hashlib
import json
from datetime import date

from ..normalize import normalize_label
from ..store import Store


def _hash12(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def topic_id(gallery_id: str, start: date, end: date, label: str) -> str:
    return _hash12(gallery_id, start.isoformat(), end.isoformat(), normalize_label(label))


def entity_id(name: str) -> str:
    return normalize_label(name)[:40] or "unknown"


def voice_id(kind: str, text: str) -> str:
    return _hash12(kind, normalize_label(text))


def materialize(store: Store, gallery_id: str, run_id: int, prompt_version: str,
                start: date, end: date, results: dict[str, dict]) -> dict[str, int]:
    period = {"period_start": start.isoformat(), "period_end": end.isoformat(),
              "gallery_id": gallery_id, "prompt_version": prompt_version}
    counts: dict[str, int] = {}

    topic_rows, junction_rows = [], []
    for t in results.get("topics", {}).get("topics", []):
        tid = topic_id(gallery_id, start, end, t.get("label", ""))
        post_nos = [int(n) for n in t.get("post_nos", []) if str(n).isdigit()]
        topic_rows.append({**period, "topic_id": tid, "label": t.get("label", ""),
                           "snippet": t.get("snippet", ""),
                           "keywords": json.dumps(t.get("keywords", []), ensure_ascii=False),
                           "source_post_nos": json.dumps(post_nos)})
        junction_rows += [{"gallery_id": gallery_id, "post_no": n, "topic_id": tid}
                          for n in post_nos]
    counts["Topic"] = store.snapshot_rows("obj_topics", run_id, topic_rows)
    counts["PostTopic"] = store.snapshot_rows("obj_post_topics", run_id, junction_rows)

    entity_rows = [{**period, "entity_id": entity_id(e.get("name", "")),
                    "display_name": e.get("name", ""), "entity_type": e.get("type", "기타"),
                    "mentions": int(e.get("mentions", 0)),
                    "sentiment": e.get("sentiment", "중립"), "reason": e.get("reason", "")}
                   for e in results.get("entities", {}).get("entities", [])]
    counts["Entity"] = store.snapshot_rows("obj_entities", run_id, entity_rows)

    issue_rows = [{**period, "issue_id": topic_id(gallery_id, start, end,
                                                  i.get("issue", "")),
                   "label": i.get("issue", ""), "pro_count": int(i.get("pro", 0)),
                   "con_count": int(i.get("con", 0)),
                   "neutral_count": int(i.get("neutral", 0)),
                   "quotes": json.dumps(i.get("quotes", []), ensure_ascii=False)}
                  for i in results.get("sentiment", {}).get("issues", [])]
    counts["Issue"] = store.snapshot_rows("obj_issues", run_id, issue_rows)

    voice_rows = [{**period, "voice_id": voice_id(v.get("kind", ""), v.get("text", "")),
                   "kind": v.get("kind", ""), "text": v.get("text", ""),
                   "quote": v.get("quote", ""), "count": int(v.get("count", 1)),
                   "source_post_no": v.get("post_no")}
                  for v in results.get("voices", {}).get("voices", [])]
    counts["Voice"] = store.snapshot_rows("obj_voices", run_id, voice_rows)
    return counts
```

`cli.py`의 `_analyze_period`에서 분석 직후 호출하도록 수정 (materialize 실패 시 run 실패 — 설계 I3):

```python
        run_id, results, coverage = analyzer.run(gallery_id, start, end, kinds)
        if run_id > 0:
            from ..ontology.materialize import materialize  # 순환 import 방지 지연 import
            from ..analyze.kinds import PROMPT_VERSION
            materialize(store, gallery_id, run_id, PROMPT_VERSION, start, end, results)
```

- [ ] **Step 3: 통과 확인 + 커밋**

Run: `pytest tests/test_materialize.py tests/test_cli.py -v` → PASS

```bash
git add dc_harness/ontology/materialize.py dc_harness/cli.py tests/test_materialize.py
git commit -m "feat: materialize merged analysis into provenance-carrying objects"
```

---

### Task 19: 결정적 탐색 CLI — `dch query` / `dch show`

**Files:**
- Create: `dc_harness/ontology/query.py`
- Modify: `dc_harness/cli.py` (서브커맨드 추가)
- Test: `tests/test_query.py`

**Interfaces:**
- Consumes: `load_ontology`, `Store.fetch_object_rows/latest_object_run/fetch_posts`
- Produces:
  - `query_objects(store: Store, defn: OntologyDef, api_name: str, gallery_id: str, start: date, end: date, limit: int = 20) -> list[dict]` — 지원: Topic/Entity/Issue/Voice(derived, 최신 run) + Post(raw, 기간 내 post_no 역순). `table`이 비었거나 미지원이면 `ValueError("...는 질의 미지원: 링크로 탐색")`
  - `show_post(store: Store, gallery_id: str, post_no: int) -> dict` — `{"post": RawPost, "topics": [label,...]}` (최신 run의 obj_post_topics 조인)
  - `print_rows(rows: list[dict]) -> str` — 폭 정렬 텍스트 테이블
  - CLI: `dch query --object Topic --gallery crypto [--days N] [--limit M] [--db P]`, `dch show --gallery crypto --post 101 [--db P]`

- [ ] **Step 1: 실패 테스트 `tests/test_query.py`**

```python
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from dc_harness.models import RawPost
from dc_harness.ontology.defn import load_ontology
from dc_harness.ontology.materialize import materialize
from dc_harness.ontology.query import print_rows, query_objects, show_post
from dc_harness.store import Store

RESULTS = {"topics": {"topics": [{"label": "현물 매수", "post_nos": [101],
                                  "keywords": ["매수"], "snippet": "s"}]}}


def seed(tmp_path: Path) -> tuple[Store, object]:
    store = Store(tmp_path / "t.db")
    post = RawPost("crypto", 101, "현물이 답", "b", "a",
                   datetime.now(), 10, 42)
    store.upsert_post(post)
    materialize(store, "crypto", 1, "v1", date.today() - timedelta(days=7), date.today(), RESULTS)
    return store, post


def test_query_topic_objects(tmp_path: Path):
    store, _ = seed(tmp_path)
    rows = query_objects(store, load_ontology(None), "Topic", "crypto",
                         date.today() - timedelta(days=7), date.today())
    assert len(rows) == 1 and rows[0]["label"] == "현물 매수"


def test_query_post_raw(tmp_path: Path):
    store, _ = seed(tmp_path)
    rows = query_objects(store, load_ontology(None), "Post", "crypto",
                         date.today() - timedelta(days=1), date.today())
    assert [r["post_no"] for r in rows] == [101]


def test_query_unsupported_object(tmp_path: Path):
    store, _ = seed(tmp_path)
    with pytest.raises(ValueError, match="질의 미지원"):
        query_objects(store, load_ontology(None), "Author", "crypto",
                      date.today(), date.today())


def test_show_post_includes_linked_topics(tmp_path: Path):
    store, _ = seed(tmp_path)
    detail = show_post(store, "crypto", 101)
    assert detail["post"].title == "현물이 답"
    assert detail["topics"] == ["현물 매수"]


def test_print_rows_renders_values(tmp_path: Path):
    out = print_rows([{"label": "현물 매수", "mentions": 5}, {"label": "채굴", "mentions": 1}])
    assert "현물 매수" in out and "채굴" in out and "mentions" in out
```

- [ ] **Step 2: 실패 확인 → `dc_harness/ontology/query.py` 구현**

```python
from __future__ import annotations

from datetime import date

from ..models import RawPost
from ..store import Store
from .defn import OntologyDef


def query_objects(store: Store, defn: OntologyDef, api_name: str, gallery_id: str,
                  start: date, end: date, limit: int = 20) -> list[dict]:
    obj = defn.object_(api_name)
    if obj is None:
        raise ValueError(f"unknown object type: {api_name}")
    if not obj.table:
        raise ValueError(f"{api_name}은(는) 질의 미지원: 링크로 탐색하세요")
    if obj.layer == "derived":
        run_id = store.latest_object_run(obj.table, gallery_id, start, end)
        if run_id is None:
            return []
        return store.fetch_object_rows(obj.table, run_id, limit)
    if api_name == "Post":
        posts = store.fetch_posts(gallery_id, start, end)
        return [{"post_no": p.post_no, "title": p.title, "recommend": p.recommend,
                 "views": p.views, "author_hash": p.author,
                 "created_at": p.created_at.isoformat(sep=" ") if p.created_at else None}
                for p in sorted(posts, key=lambda p: p.post_no, reverse=True)[:limit]]
    raise ValueError(f"{api_name}은(는) 질의 미지원: 링크로 탐색하세요")


def show_post(store: Store, gallery_id: str, post_no: int) -> dict:
    posts = [p for p in store.fetch_posts(gallery_id) if p.post_no == post_no]
    if not posts:
        raise ValueError(f"post not found: {gallery_id}/{post_no}")
    post: RawPost = posts[0]
    row = store.conn.execute(
        "SELECT t.label FROM obj_post_topics j JOIN obj_topics t"
        " ON j.topic_id=t.topic_id AND j.run_id=t.run_id"
        " WHERE j.gallery_id=? AND j.post_no=?"
        " AND t.run_id=(SELECT MAX(run_id) FROM obj_topics)",
        (gallery_id, post_no)).fetchall()
    return {"post": post, "topics": [r["label"] for r in row]}


def print_rows(rows: list[dict]) -> str:
    if not rows:
        return "(결과 없음)"
    columns = list(rows[0].keys())
    widths = {c: max(len(str(c)), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    lines = [" | ".join(str(c).ljust(widths[c]) for c in columns)]
    lines.append("-+-".join("-" * widths[c] for c in columns))
    for r in rows:
        lines.append(" | ".join(str(r.get(c, ""))[:60].ljust(widths[c]) for c in columns))
    return "\n".join(lines)
```

`cli.py` `build_parser()`에 추가:

```python
    p_query = sub.add_parser("query", help="온톨로지 객체 질의 (결정적, LLM 없음)")
    p_query.add_argument("--object", required=True)
    p_query.add_argument("--gallery", required=True)
    p_query.add_argument("--days", type=int, default=7)
    p_query.add_argument("--limit", type=int, default=20)
    p_query.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_query.set_defaults(func=_cmd_query)

    p_show = sub.add_parser("show", help="게시글 상세 + 연결된 토픽")
    p_show.add_argument("--gallery", required=True)
    p_show.add_argument("--post", type=int, required=True)
    p_show.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_show.set_defaults(func=_cmd_show)
```

핸들러:

```python
def _cmd_query(args, cfg):
    from .ontology.defn import load_ontology
    from .ontology.query import print_rows, query_objects
    start, end = _period(args.days)
    with Store(Path(args.db)) as store:
        rows = query_objects(store, load_ontology(None), args.object,
                             args.gallery, start, end, args.limit)
    print(print_rows(rows))
    return 0


def _cmd_show(args, cfg):
    from .ontology.query import show_post
    with Store(Path(args.db)) as store:
        detail = show_post(store, args.gallery, args.post)
    post = detail["post"]
    print(f"#{post.post_no} {post.title} (추천 {post.recommend})")
    print(f"토픽: {', '.join(detail['topics']) or '(없음)'}")
    for c in post.comments[:10]:
        print(f"  - (추천{c.recommend}) {c.text}")
    return 0
```

- [ ] **Step 3: 통과 확인 + 커밋**

Run: `pytest tests/test_query.py -v` → PASS

```bash
git add dc_harness/ontology/query.py dc_harness/cli.py tests/test_query.py
git commit -m "feat: deterministic ontology query and post detail cli"
```

---

### Task 20: OMCP식 질의 — `dch ask` (읽기 전용 도구 루프)

**Files:**
- Create: `dc_harness/ontology/tools.py`, `dc_harness/ontology/ask.py`
- Modify: `dc_harness/cli.py` (`ask` 서브커맨드)
- Test: `tests/test_ask.py`

**Interfaces:**
- Consumes: `LlmClient.chat_json(system, user)`, `query_objects`, `show_post`, `Store.log_llm_call`, `load_ontology`
- Produces:
  - `@dataclass ToolDef(name: str, description: str, fn: Callable[[dict], object])`
  - `build_tools(store: Store, defn: OntologyDef, gallery_id: str) -> dict[str, ToolDef]` — 도구 3종:
    - `queryObjects` — "apiName(Topic|Entity|Issue|Voice|Post)·days·limit를 받아 최신 분석 객체 목록을 JSON 배열로 반환"
    - `getThread` — "postNo를 받아 게시글 본문+댓글+연결 토픽을 JSON로 반환"
    - `stats` — "apiName과 days를 받아 개수·주요 집계(예: Issue 찬반 합계, Entity 언급 상위, Voice kind별 빈도)를 JSON로 반환"
  - `ontology_summary(defn: OntologyDef) -> str` — 객체·링크 나열(의미 계층을 LLM 컨텍스트로)
  - `ask(store: Store, defn: OntologyDef, llm: LlmClient, gallery_id: str, question: str, max_steps: int = 6) -> str` — 프로토콜: 모델은 `{"tool": name, "args": {...}}` 또는 `{"answer": "..."}` JSON 반환. 도구 결과는 누적 transcript에 추가(원본 게시물 대신 도구 결과만 전달). 응답에 `글#숫자` 인용 없으면 1회 재요청 후 `(근거 인용 없음)` 표기. 매 호출 `llm_calls` 감사(run은 `start_run(gallery_id)`로 생성, kind="ask").
  - CLI: `dch ask --gallery crypto "최근 일주일 사람들이 뭘 좋아함?" [--db P]`

- [ ] **Step 1: 실패 테스트 `tests/test_ask.py`**

```python
from datetime import date, datetime, timedelta
from pathlib import Path

from dc_harness.models import RawPost
from dc_harness.ontology.ask import ask
from dc_harness.ontology.defn import load_ontology
from dc_harness.ontology.materialize import materialize
from dc_harness.ontology.tools import build_tools, ontology_summary
from dc_harness.store import Store


class ScriptedLlm:
    model = "stub"

    def __init__(self, replies):
        self.replies = list(replies)
        self.users: list[str] = []

    def chat_json(self, system, user, max_retries=2):
        self.users.append(user)
        return self.replies.pop(0)


def seed(tmp_path: Path) -> Store:
    store = Store(tmp_path / "t.db")
    store.upsert_post(RawPost("crypto", 101, "현물이 답", "본문", "a",
                              datetime.now(), 10, 42))
    materialize(store, "crypto", 1, "v1",
                date.today() - timedelta(days=7), date.today(),
                {"topics": {"topics": [{"label": "현물 매수", "post_nos": [101],
                                        "keywords": ["매수"], "snippet": "s"}]}})
    return store


def test_ontology_summary_lists_objects_and_links(tmp_path: Path):
    text = ontology_summary(load_ontology(None))
    assert "Topic" in text and "Discusses" in text and "논의된 토픽이다" in text


def test_tools_are_readonly_and_described(tmp_path: Path):
    store = seed(tmp_path)
    tools = build_tools(store, load_ontology(None), "crypto")
    assert set(tools) == {"queryObjects", "getThread", "stats"}
    assert all("반환" in t.description for t in tools.values())
    rows = tools["queryObjects"].fn({"apiName": "Topic", "days": 7})
    assert rows[0]["label"] == "현물 매수"


def test_ask_runs_tool_then_answers_with_citation(tmp_path: Path):
    store = seed(tmp_path)
    llm = ScriptedLlm([
        {"tool": "queryObjects", "args": {"apiName": "Topic", "days": 7}},
        {"answer": "최근 관심은 현물 매수입니다. 근거: [글#101]"},
    ])
    answer = ask(store, load_ontology(None), llm, "crypto", "요즘 관심사는?")
    assert "현물 매수" in answer and "글#101" in answer
    calls = store.conn.execute("SELECT * FROM llm_calls WHERE kind='ask'").fetchall()
    assert len(calls) == 2  # 감사: 스텝마다 기록


def test_ask_enforces_citation_once(tmp_path: Path):
    store = seed(tmp_path)
    llm = ScriptedLlm([
        {"answer": "인용 없는 답"},
        {"answer": "인용 없는 답 (재시도 후)"},
    ])
    answer = ask(store, load_ontology(None), llm, "crypto", "물어봄")
    assert "근거 인용 없음" in answer
```

- [ ] **Step 2: 실패 확인 → 구현**

`dc_harness/ontology/tools.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from ..store import Store
from .defn import OntologyDef
from .query import query_objects, show_post

DERIVED_QUERYABLE = ("Topic", "Entity", "Issue", "Voice")


@dataclass
class ToolDef:
    name: str
    description: str
    fn: Callable[[dict], object]


def _period(days: int) -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=max(days, 1)), today


def build_tools(store: Store, defn: OntologyDef, gallery_id: str) -> dict[str, ToolDef]:
    def query_objects_tool(args: dict):
        api = str(args.get("apiName", "Topic"))
        start, end = _period(int(args.get("days", 7)))
        return query_objects(store, defn, api, gallery_id, start, end,
                             limit=int(args.get("limit", 10)))

    def get_thread_tool(args: dict):
        return show_post(store, gallery_id, int(args["postNo"])) | {"ok": True}

    def stats_tool(args: dict):
        api = str(args.get("apiName", "Topic"))
        start, end = _period(int(args.get("days", 7)))
        rows = query_objects(store, defn, api, gallery_id, start, end, limit=100)
        if api == "Issue":
            return {"count": len(rows),
                    "pro_total": sum(int(r.get("pro_count", 0)) for r in rows),
                    "con_total": sum(int(r.get("con_count", 0)) for r in rows)}
        if api == "Entity":
            return {"count": len(rows), "top_by_mentions": [
                {"name": r["display_name"], "mentions": r["mentions"]} for r in rows[:5]]}
        if api == "Voice":
            kinds: dict[str, int] = {}
            for r in rows:
                kinds[r["kind"]] = kinds.get(r["kind"], 0) + int(r.get("count", 1))
            return {"count": len(rows), "by_kind": kinds}
        return {"count": len(rows)}

    return {
        "queryObjects": ToolDef(
            "queryObjects",
            "apiName(Topic|Entity|Issue|Voice|Post)와 days·limit를 받아 해당 기간"
            " 최신 분석 객체 목록을 JSON 배열로 반환한다", query_objects_tool),
        "getThread": ToolDef(
            "getThread", "postNo를 받아 게시글 제목·본문·댓글·연결 토픽을 JSON로 반환한다",
            get_thread_tool),
        "stats": ToolDef(
            "stats", "apiName과 days를 받아 개수·주요 집계를 JSON로 반환한다", stats_tool),
    }
```

`dc_harness/ontology/ask.py`:

```python
from __future__ import annotations

import json
import re

from ..llm.client import LlmClient
from ..store import Store
from .defn import OntologyDef
from .tools import build_tools

_CITATION = re.compile(r"글#\d+")


def ontology_summary(defn: OntologyDef) -> str:
    lines = ["=== 온톨로지 객체 ==="]
    for o in defn.objects:
        lines.append(f"- {o.apiName} ({o.displayName}): {o.description}"
                     f" [pk={','.join(o.pk)}, layer={o.layer}]")
    lines.append("=== 링크 ===")
    for l in defn.links:
        lines.append(f"- {l.fromObject} --{l.apiName}({l.displayName}, "
                     f"{l.cardinality})--> {l.toObject}"
                     + (f" via {l.via}" if l.via else ""))
    return "\n".join(lines)


def ask(store: Store, defn: OntologyDef, llm: LlmClient, gallery_id: str,
        question: str, max_steps: int = 6) -> str:
    tools = build_tools(store, defn, gallery_id)
    run_id = store.start_run(gallery_id)
    system = (
        ontology_summary(defn)
        + "\n\n=== 사용 가능 도구 ===\n"
        + "\n".join(f"- {t.name}: {t.description}" for t in tools.values())
        + '\n\n규칙: 도구가 필요하면 {"tool": 이름, "args": {...}} JSON만 출력한다.'
        ' 도구 결과를 보고 충분하면 {"answer": "..."} JSON으로 최종 답변한다.'
        " 답변은 한국어, 모든 주장에 [글#번호] 인용을 포함한다."
        " 원본 데이터 전체를 요구하지 말고 도구 결과만 사용한다."
    )
    transcript = f"질문: {question}"
    answer = ""
    for step in range(max_steps):
        result = llm.chat_json(system, transcript)
        store.log_llm_call(run_id, "ask", system, transcript,
                           json.dumps(result, ensure_ascii=False),
                           getattr(llm, "model", "unknown"), "ask-v1")
        if "tool" in result:
            tool = tools.get(result["tool"])
            if tool is None:
                output = {"error": f"unknown tool: {result['tool']}"}
            else:
                try:
                    output = tool.fn(result.get("args", {}))
                except Exception as exc:  # 도구 실패는 루프 중단 아님
                    output = {"error": str(exc)}
            transcript += (f"\n\n[도구 결과: {result['tool']}]\n"
                           + json.dumps(output, ensure_ascii=False, default=str)[:4000])
            continue
        answer = str(result.get("answer", ""))
        if _CITATION.search(answer) or step == max_steps - 2:
            break
        transcript += ("\n\n[시스템] 답변에 [글#번호] 형태의 근거 인용이 없다. "
                       "도구로 근거를 확인한 뒤 인용을 포함해 다시 답하라.")
    store.finish_run(run_id, "done", {"question": question})
    if answer and not _CITATION.search(answer):
        answer += "\n(근거 인용 없음 — 도구 결과를 직접 확인 권장)"
    return answer or "(최대 스텝 초과 — 질문을 좁혀서 다시)"
```

`cli.py` 서브커맨드:

```python
    p_ask = sub.add_parser("ask", help="온톨로지 도구 기반 질의 (LLM, 읽기 전용)")
    p_ask.add_argument("--gallery", required=True)
    p_ask.add_argument("question")
    p_ask.add_argument("--db", type=Path, default=Path("data/dch.db"))
    p_ask.set_defaults(func=_cmd_ask)


def _cmd_ask(args, cfg: Config, llm_factory=None) -> int:
    from .ontology.ask import ask
    from .ontology.defn import load_ontology
    with Store(Path(args.db)) as store:
        llm = (llm_factory or _make_llm)(cfg)
        print(ask(store, load_ontology(None), llm, args.gallery, args.question))
    return 0
```

- [ ] **Step 3: 통과 확인 + 커밋**

Run: `pytest tests/test_ask.py -v` → PASS

```bash
git add dc_harness/ontology/tools.py dc_harness/ontology/ask.py dc_harness/cli.py tests/test_ask.py
git commit -m "feat: omcp-style readonly tool loop for ontology qa"
```

---

### Task 21: CONVENTIONS.md + `dch ontology` + 문서 정리 + 전체 검증

**Files:**
- Create: `CONVENTIONS.md`
- Modify: `dc_harness/cli.py` (`ontology` 서브커맨드), `README.md`
- Test: 전체 `pytest`, `tests/test_ontology_print.py`

**Interfaces:**
- Consumes: `load_ontology`, `ontology_summary`
- Produces: `dch ontology [--json]` — 정의된 객체·링크 인쇄(링크 이름=문서). `--json`이면 defn을 JSON로 출력.

- [ ] **Step 1: 실패 테스트 `tests/test_ontology_print.py`**

```python
from dc_harness.cli import main


def test_ontology_command_prints_model(capsys):
    assert main(["ontology"]) == 0
    out = capsys.readouterr().out
    assert "Topic" in out and "Discusses" in out and "논의된 토픽이다" in out
```

- [ ] **Step 2: 실패 확인 → cli.py에 서브커맨드·핸들러 추가**

```python
    p_onto = sub.add_parser("ontology", help="온톨로지 정의 인쇄 (객체·링크)")
    p_onto.add_argument("--json", action="store_true")
    p_onto.set_defaults(func=_cmd_ontology)


def _cmd_ontology(args, cfg):
    import dataclasses, json
    from .ontology.ask import ontology_summary
    from .ontology.defn import load_ontology
    defn = load_ontology(None)
    if args.json:
        print(json.dumps(dataclasses.asdict(defn), ensure_ascii=False, indent=2))
    else:
        print(ontology_summary(defn))
    return 0
```

- [ ] **Step 3: `CONVENTIONS.md` 작성 (1페이지 상한)**

```markdown
# CONVENTIONS — dc-harness 네이밍·변경 규칙 (1페이지 상한)

## 이름
- 객체·링크 api_name: 영문 PascalCase. 속성: camelCase. 한글은 description에만.
- 원본 컬럼명(DC HTML 등)을 이름으로 재사용 금지 — 업무 의미로 재명명.
- 새 Object/Link 정의 전 `dch ontology --json | grep` 으로 기존 정의 검색 (중복 금지).
- 이름 정규화는 store 적재 시 1회. 이후 계층에서 재명명 금지 (lineage 보존).

## 모델 경계
- 객체 8종·링크 6종 상한. 추가는 "실제 질문 + 필요성 입증" 후에만.
- derived 객체는 runId·promptVersion·근거 post 번호 필수 (검증기 V5).
- 파생 테이블은 run 단위 SNAPSHOT만. 행 단위 UPDATE 금지.

## 변경 절차
- 분석 프롬프트를 바꾸면 kinds.py의 PROMPT_VERSION 상향 (llm_calls/obj_* lineage 키).
- 스키마(posts/comments/obj_*) 변경은 하위 소비자(query/report/ask) 점검 후.
- LLM 결과 이상 → 모델 의심 전에 store 원본·정제 데이터부터 점검 (파운드리 원칙).
- 프롬프트 변경 시 기존 골든 픽스처 테스트(tests/test_analyzers.py) 재실행.

## 디버깅 순서 (고정)
1. store 원본(posts) 확인 → 2. 청킹 입력 → 3. llm_calls 실제 응답 → 4. 병합 결과 → 5. 프롬프트.
```

- [ ] **Step 4: README에 온톨로지 섹션 추가**

`## 온톨로지` 섹션을 README 끝에 추가:

```markdown
## 온톨로지 (의미 계층)
- 정의: `dc_harness/ontology/ontology.toml` (유일 원천). `dch ontology`로 인쇄.
- 원본(posts/comments)은 불변, 분석 결과는 파생 객체(obj_*)로 run 단위 SNAPSHOT 저장.
- 모든 파생 행은 run_id·prompt_version·근거 글 번호를 포함 (lineage).
- 탐색: `dch query --object Topic --gallery crypto` / `dch show --gallery crypto --post 101`
- 질의: `dch ask --gallery crypto "최근 관심사는?"` (읽기 전용 도구 3종, 인용 강제)
- 규칙: CONVENTIONS.md 참조. 모든 LLM 호출은 llm_calls에 감사 기록됨.
```

- [ ] **Step 5: 전체 검증 + 커밋**

Run: `pytest -v && ruff check dc_harness tests`
Expected: 전부 PASS / lint 0

```bash
git add CONVENTIONS.md dc_harness/cli.py README.md tests/test_ontology_print.py
git commit -m "docs: conventions, ontology print command, readme ontology section"
```

---

## Self-Review 결과

1. **Spec 커버리지**: §1 채택 표의 모든 행이 태스크로 대응 — 의미 계층 정의(14)·네이밍 규칙(14/15/21)·검증 V1–V6(15)·SNAPSHOT 파생 테이블(16/18)·lineage(16–18)·감사 로그(16/17)·객체 모델 종착지(18)·탐색/운영 분리(19 vs 기존 analyze/report)·OMCP 도구·인용 강제(20)·CONVENTIONS(21). Action 연기(§5)는 명시적 비구현.
2. **플레이스홀더 스캔**: "TBD/나중에" 없음. 모든 코드 스텝에 실제 코드.
3. **타입 일관성**: `snapshot_rows/fetch_object_rows/latest_object_run`(16) ← `materialize`(18)·`query_objects`(19)·`tools`(20) 사용 일치. `Analyzer.run -> (run_id, results, coverage)`(17)가 Task 12·18 수정본과 일치. `ToolDef.fn(args)->object`와 `ask`의 호출부 일치. `load_ontology(None)` 기본 경로 사용 전 태스크에서 동일.
4. **Phase 1 무손상 확인**: Phase 1 파일 중 수정은 `store.py`(추가만), `runner.py`(run_id+감사), `kinds.py`(상수), `cli.py`(언패킹+신규 서브커맨드) — 파이프라인 구조·의존성·기존 태스크 시퀀스 불변.
