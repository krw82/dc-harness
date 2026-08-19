# dc-harness 온톨로지 계층 설계 (v2 addendum)

- 날짜: 2026-08-19
- 선행 문서: `2026-08-19-dc-inside-opinion-harness-design.md` (v1 설계), `2026-08-19-dc-inside-opinion-harness.md` (Phase 1 계획)
- 근거 자료: ontologyaimap.com 온톨로지/파운드리/AIP/OMCP 시리즈 24편 (4개 병렬 리서치 에이전트가 전문 독해)

## 0. 전제 — 흔들리지 않는 것 (불변 선언)

이 문서는 v1 설계를 **대체하지 않고 가산**한다. 다음은 온톨로지 도입과 무관하게 불변이다:

1. 파이프라인 방향 단방향: `collectors → store → analyzers → reports`. 어떤 계층도 상류를 수정하지 않는다.
2. 런타임 의존 `openai`, `httpx`, `beautifulsoup4` 3개만. 온톨로지 계층은 **stdlib만** 사용한다 (정의 파일은 TOML = `tomllib`).
3. 모든 스테이지 멱등. 수집은 upsert, 파일 인제스트 탈출구 유지.
4. LLM은 판단 지점에만 최소 배치. 청킹·집계·포맷은 결정론적 Python.
5. API 키는 env만. 아웃바운드 URL은 guard 통과. 리포트에 개인정보 없음.

## 1. 연구 종합 — 채택과 거부 (근거 명시)

### 채택 (전이 가능 + 우리 질문에 필요)

| 개념 | 출처 | 우리 구현 |
|---|---|---|
| 데이터 계층 위 의미 계층 (Object=Row, Property=Column, Link=Join 승격) | 온톨로지 개관/핵심 구성요소 | 선언적 `ontology.toml` + 검증기. SQLite는 그대로, 의미는 별도 정의 계층에 |
| 네이밍 규칙: 영문 PascalCase/camelCase 이름 + 한글은 description, 원본 컬럼명 재사용 금지, 생성 전 중복 검색 | 네이밍 전략 | `CONVENTIONS.md` 1페이지 + 검증기 규칙(V4) |
| Object→Link→Action 순서, Action은 구조 안정 후 | 핵심 구성요소/Ontology Manager | 지금은 Object+Link만 정의. **Action 계층은 명시적으로 연기**(§5) |
| 링크는 실제 질문에서 역산해 필요한 만큼만 | 온톨로지 개관/매니저 가이드 | 존재하는 FK/접점만 6개 링크 선언 (§3) |
| Primary Property(PK) 필수 + 유니크 검증 | Ontology Manager | 검증기 규칙 V2 |
| ELT: 원본 불변 + 파생 재계산, 파생은 SNAPSHOT(run 단위 삭제 후 재작성) | 데이터 저장/파이프라인 | `posts/comments` = 원본 계층(수집 멱등 upsert), `obj_*` = 파생 계층(run_id SNAPSHOT) |
| Row-level lineage: 파생 행마다 run_id·prompt_version·근거 post 번호 | Data Lineage | 모든 `obj_*` 행에 provenance 칼럼. 검증기 규칙 V5 |
| LLM 호출 감사 로그 | AIP 개관 | `llm_calls` 테이블: 입력·출력·모델·프롬프트 버전 |
| "리포트가 아니라 객체 모델이 종착지" — LLM 추출 결과를 재사용 가능한 구조화 객체로 저장, 리포트는 소비 계층 | SAP BI 마이그레이션 | `obj_topics/obj_entities/obj_issues/obj_voices` 테이블. 리포트는 동일 입력의 다른 투영 |
| 탐색(1회성)과 운영(반복) 분리 | Explore/Insight | `dch query`/`dch show`(결정적 탐색) vs `dch analyze`/`report`(반복 파이프라인) |
| OMCP 도구 규칙: 소수·구체적 도구("입력 X→Y 반환"), 정의된 경로만 탐색, 근거 재확인 | OMCP 가이드 | `dch ask`: 읽기 전용 도구 3개 + 응답에 [글#번호] 인용 강제 |
| "AI 오답은 모델 탓 전에 데이터/스키마 점검" | 파운드리 아키텍처 | 디버깅 순서를 CONVENTIONS.md에 문서화 |
| LLM 최소 배치, 원본 대신 요약 전달 | AIP 워크플로우 | 기존 map-reduce 구조가 이미 부합 — 변경 없음 |

### 거부 (플랫폼 종속 또는 과잉)

그래프 DB, Foundry/OSv2/writeback, 데이터 브랜치, RBAC·필드 권한·감사 서버, Searchable/Filterable 색인 플래그, Workshop/UI 계층, 3단 medallion(2계층으로 충분 — 원문에도 3단은 없음), 자동 lineage 캡처(우리는 명시적 기록), 실시간 Action 실행. 거부 이유가 필요해지는 시점 = 요구사항이 바뀌는 시점이며 그때 재검토한다.

## 2. 불변식 (I1–I10) — 구현·리뷰의 준거

- **I1 (단방향)**: 파생 계산은 `posts/comments`를 절대 수정하지 않는다.
- **I2 (SNAPSHOT)**: `obj_*` 테이블은 run_id 단위로 `DELETE → INSERT`. 행 단위 즉석 수정 금지(Foundry "전체 재작성 또는 변경분 적층" 원칙).
- **I3 (Provenance)**: 모든 파생 행은 `run_id`, `prompt_version`, 근거(`source_post_nos`/`source_post_no`)를 가진다. 검증기가 강제.
- **I4 (근거 접지)**: 리포트와 `ask` 응답의 모든 주장은 글 번호 인용을 동반한다.
- **I5 (감사)**: 모든 LLM 호출은 `llm_calls`에 기록된다(요청·응답·모델·프롬프트 버전).
- **I6 (의존성)**: 온톨로지 계층 모듈은 stdlib만 사용한다.
- **I7 (순서)**: Object→Link 확정 후에만 소비자(query/report/ask)를 붙인다. Action은 Object·Link가 안정된 뒤(현재 연기).
- **I8 (중복 금지)**: 새 Object Type 정의 전 기존 정의 검색. 검증기 V4가 동일 개념 중복을 거부.
- **I9 (최소 링크)**: 실제 질문이 필요로 하는 링크만 선언한다. "혹시 몰라" 링크 금지.
- **I10 (이름 규칙)**: api_name은 영문 PascalCase(객체·링크)/camelCase(속성). 한글은 description에만. 중간 계층 이름 재변경 금지(정규화는 store 적재 시 1회).

## 3. 온톨로지 모델

정의 파일: `dc_harness/ontology/ontology.toml` (유일한 원천, `dch ontology`로 인쇄 가능 — "링크 이름=문서").

**Object Type 8종**

| apiName | 계층 | PK | 비고 |
|---|---|---|---|
| Gallery | raw | galleryId | 갤러리 |
| Post | raw | galleryId+postNo | 원본 게시글. table=posts |
| Comment | raw | galleryId+postNo+seq | table=comments |
| Author | raw | authorHash | 해시된 작성자. 링크 통해서만 탐색 |
| Topic | derived | topicId | run·기간·정규화 라벨로 생성 |
| Entity | derived | entityId | 정규화 이름. 기간 단위 집계(인물/종목/제품…) |
| Issue | derived | issueId | 이슈별 찬반 집계 + 대표 인용 |
| Voice | derived | voiceId | 불만/바람/아이디어 + 원문 인용 + 빈도 |

**Link Type 6종** (전부 업무 언어 이름, 한국어 displayName)

| apiName | 관계 | 카디널리티 | 구현 |
|---|---|---|---|
| WrittenOn | Comment→Post "작성된 게시글이다" | N:1 | FK |
| BelongsTo | Post→Gallery "소속 갤러리이다" | N:1 | FK |
| AuthoredBy | Post→Author "작성자이다" | N:1 | author_hash |
| Discusses | Post↔Topic "논의된 토픽이다" | N:M | obj_post_topics 접합(via 선언) |
| Evidences | Voice→Post "근거 게시글이다" | N:1 | source_post_no |
| WrittenIn | Comment/Post→Gallery 는 BelongsTo로 흡수 | — | (선언 안 함 — I9) |

Entity↔Post 개별 링크는 **선언하지 않는다**: 현재 추출 스키마가 포스트 단위 근거를 내지 않고 기간 집계만 내므로, 존재하지 않는 관계를 문서화하는 것은 I9 위반이다. 포스트 단위 근거 추출이 필요해지면 추출 스키마 확장과 함께 추가한다.

**검증 규칙 (validator)**: V1 이름 형식·유일성 / V2 PK 존재·속성 일치 / V3 링크 양단 존재·N:M은 via 필수 / V4 동일 개념 중복(displayName·정규화 라벨) 금지 / V5 derived 객체는 runId·promptVersion 속성 필수(I3) / V6 카디널리티 열거형.

## 4. 데이터 흐름 v2

```
[원본 계층 — 수집 멱등 upsert, 파생이 절대 안 고침]
posts, comments
        │ Analyzer.run (map-reduce, LLM 최소 배치, llm_calls 감사)
        ▼
[병합 결과] ──투영 1──▶ analyses (run 아카이브 JSON — 리포트 소비)
        │
        └──투영 2──▶ materialize() ──▶ obj_topics/entities/issues/voices + obj_post_topics
                                    (SNAPSHOT, provenance 포함)
                                        │
        ┌───────────────────────────────┼─────────────────────────┐
        ▼                               ▼                         ▼
  dch report (반복·운영)         dch query / show (1회성 탐색)   dch ask (OMCP식 질의)
```

두 투영은 같은 run에서 같은 병합 입력으로부터 같은 트랜잭션 시점에 작성되므로 어긋날 수 없다(I2, I3). materialize 실패는 run 실패로 처리한다.

`dch ask` 도구 3종 (읽기 전용, "입력→출력" 명시): `queryObjects(apiName, days, limit)` / `getThread(postNo)` / `stats(apiName)`. 도구 루프는 chat-completions 위에 수동 구현(모델이 `{"tool":…}` 또는 `{"answer":…}` JSON을 반환), 최대 6스텝, 응답은 [글#번호] 인용 없으면 재요청, 전 과정 llm_calls 감사.

## 5. Action 계층 — 명시적 연기

분석 전용 하네스에는 검증된 쓰기(write-back) 요구가 없다(원문 기준: "조회만으로 충분하면 온톨로지의 Action 층은 선택"). 재검토 트리거: 토픽 병합·엔티티 정규화 확정 같은 사람 승인 쓰기가 필요해질 때. 그때 "파라미터→검증→효과" 4단 구조 + 승인 게이트로 설계한다.

## 6. Phase 구조와 Phase 1 영향

- **Phase 1 (기존 13 태스크): 거의 무손상.** 수정은 단 한 곳 — `Analyzer.run`이 `run_id`를 함께 반환하도록 시그니처 변경(`-> (run_id, results, coverage)`)과 cli 언패킹 2줄. 나머지 태스크는 그대로.
- **Phase 2 (신규 태스크 14–21)**: 14 온톨로지 정의+로더 → 15 검증기 → 16 스토어 확장(obj_*·llm_calls) → 17 러너 감사·프롬프트 버전 → 18 materializer → 19 query/show CLI → 20 dch ask → 21 CONVENTIONS·문서·`dch ontology`. 순서는 I7(스키마 먼저, 소비자 나중)을 그대로 따른다.
- 태스크 20(`ask`)은 독립 태스크로 필요 시 제거 가능(이전에 '대화형보다 리포트'를 선호하셨으므로 분리 가능하게 둔다).

## 7. 리스크

| 리스크 | 대응 |
|---|---|
| 온톨로지 과잉 모델링 (원문 1위 실패 패턴) | 객체 8종·링크 6종 상한을 검증기·CONVENTIONS로 고정. 추가는 "실제 질문 제출 → 필요성 입증" 후에만 |
| 두 투영(analyses/obj_*) 이중 저장 비용 | SQLite 수준에서 무시 가능. 어긋남은 구조적으로 불가(같은 run·같은 입력) |
| ask 루프의 환각 | 정의된 도구만 사용, 원본 미전달(도구 결과만), 인용 강제, 최대 스텝 수, 감사 로그 |
| 이름 표류 | CONVENTIONS.md 1페이지 + V4 중복 검사 + 새 이름은 여기에 등록 후 사용 |
