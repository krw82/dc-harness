# DC Inside 여론 분석 하네스 (dc-harness) — 설계 문서

- 날짜: 2026-08-19
- 목적: 연구용(비상업). DC Inside 갤러리별 관심사·여론·트렌드·니즈(VOC)를 LLM으로 분석하는 CLI 하네스.
- 참고: [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)의 모듈형 하네스 철학에서 착안. 단, 단인 연구자 도구에는 플러그인 레지스트리 전체 아키텍처는 과하므로(YAGNI) "깨끗한 인터페이스를 가진 파이프라인"으로 번역함.

## 1. 목표와 비목표

**목표**
1. 지정 갤러리·기간에 대해: 게시글+댓글+추천수를 수집·저장
2. LLM(OpenAI 호환 API, 기본 `motif-12.7b-reasoning` @ `chat.motiftech.io`)으로 5종 분석:
   - **토픽/관심사**: 상위 주제, 반복 키워드, 대표 게시글
   - **여론/감성**: 이슈별 찬반/긍부정 분포, **추천수 기반 인기 반응**(사람들이 뭘 좋아하는지)
   - **시간 트렌드**: 기간 대비 토픽·감성 변화, 떠오르는/식는 이슈
   - **엔티티 여론**: 인물/종목/제품/브랜드별 감성 집계
   - **VOC(니즈)**: 불편한 점, "~있으면 좋겠다", 요구·아이디어 추출 (product-design 플러그인 스타일, 증거 인용 포함)
3. 결과물: Markdown 리포트 + 원시 JSON. CLI 한 줄(`dch run`)로 전체 파이프라인 실행.

**비목표**
- 캡차 우회/로그인 강제 시도 안 함(차단 감지 시 정지·보고). 대신 파일 인제스트로 분석 항상 가능.
- 실시간 스트리밍/웹 대시보드/상업 서비스화 없음.
- 개인 식별 정보 프로파일링 없음. 작성자 ID는 해시 처리.

## 2. 접근법 비교 (결정: B)

| | A. 스크립트 모음 | **B. 모듈형 파이프라인 패키지 (채택)** | C. deepseek-harness식 플러그인 아키텍처 |
|---|---|---|---|
| 시작 속도 | 가장 빠름 | 빠름 | 느림 |
| 재개/중복 실행 안전성 | 없음 | SQLite upsert로 보장 | 보장하나 오버헤드 큼 |
| 테스트 용이성 | 어려움 | 스테이지별 fixture 테스트 | 좋으나 설정 비용 큼 |
| 확장성 | 나쁨 | 콜렉터/분석기 추가는 인터페이스 구현만으로 확장 | 최상이지만 단인 연구 도구에 과함 |

## 3. 아키텍처

```
collectors ──▶ store(SQLite) ──▶ analyzers(LLM) ──▶ reports(MD/JSON)
 (dcinside,                        (topics,            (gallery report)
  jsonl 파일)                       sentiment, trends,
                                   entities, voices)
        ▲                                              │
        └──────────── config.toml + env (API key) ◀────┘
```

하나의 Python 패키지 `dc_harness`, CLI 진입점 `dch`.

### 3.1 collectors/ — 수집
- 공통 인터페이스: `Collector.collect(spec) -> Iterator[RawPost]`
- `dcinside.py` (내장 스크래퍼)
  - 대상: `gall.dcinside.com`, `m.dcinside.com` 고정 허용 목록(allowlist). 요청 전 host 검증 + http/https 만 허용 + 사설/루프백 주소 거부.
  - 수집 단위: 갤러리 목록 페이지(제목·말머리·작성자·작성시각·조회수·추천수) → 게시글 본문 → 댓글(추천/비추천 포함).
  - 예의: 기본 1~2초 + 지터 딜레이(설정 가능). 429/캡차 감지 시 즉시 중단 후 부분 결과 보고. 쿠키·User-Agent는 env/파일로 제공(필요시).
  - 인증 없이 공개된 페이지만. 로그인 필요 갤러리는 건너뛰고 보고.
- `jsonl.py` (파일 인제스트): 정규화된 JSONL을 그대로 적재. 수집 경로가 막혀도 분석 파이프라인은 항상 동작하는 탈출구.

### 3.2 store/ — 저장
- stdlib `sqlite3`, 파일 DB(`data/dch.db`). 외부 DB 의존 없음.
- 테이블: `posts`(gallery_id, post_no, title, body, author_hash, created_at, views, recommend, raw JSON), `comments`(post_no, text, rec, unrec), `analyses`(run_id, kind, gallery_id, period, result JSON), `runs`(상태·통계).
- `(gallery_id, post_no)` UNIQUE → 재실행 upsert로 멱등(idempotent) 보장. 수집 체크포인트 재개도 여기서 자연 해결.

### 3.3 normalize/ — 정규화
- HTML 태그/엔티티 제거, DC 특유 노이즈(고정 접두사, 이모지 코드) 정리, 본문·제목 길이 컷.
- 키워드 빈도용 경량 토크나이저(정규식 기반, 한글 자소 처리 최소). 형태소 분석기 의존 없음 — 어휘 통계는 보조 지표이고 LLM이 본 분석을 담당.

### 3.4 analyzers/ — LLM 분석 (map-reduce)
- 공통 `LlmClient`: `openai` SDK, `base_url`/`model`은 config, API 키는 **env(`MOTIF_API_KEY`)** 에서만 읽음(소스에 리터럴 금지).
- reasoning 모델 대응: 응답에서 `<think>...</think>` 등 추론 영역 제거 후 JSON 파싱, 파싱 실패 시 재시도·경량 복구(repair).
- 청킹: 스레드 또는 게시글 묶음을 토큰 상한(기본 ~12k chars, 설정 가능) 청크로 분할 → 각 청크에서 구조화 JSON 추출(map) → 기간 전체 집계(reduce). 청크 실패는 격리되고 리포트에 커버리지 명시.
- 모듈: `topics`, `sentiment`(이슈별 찬반 + 추천수 가중 인기 반응), `trends`(기간 대비 diff), `entities`(엔티티 추출+감성 집계), `voices`(불만/니즈/아이디어 + 증거 인용 + 빈도).
- 출력 스키마는 각 분석기가 prompt 내 JSON 스키마로 고정. 모든 분석 결과는 원본 인용(post_no)을 포함해 검증 가능성 유지.

### 3.5 reports/ — 리포트
- 갤러리+기간 단위 Markdown(섹션: 요약, 토픽, 여론, 트렌드, 엔티티, VOC, 커버리지/한계) + 동일 내용 JSON.
- `reports/<gallery_id>/<yyyymmdd>-<period>.md`. 템플릿은 stdlib `string.Template` (Jinja 의존 없음).

### 3.6 cli — `dch`
- stdlib `argparse` 서브커맨드: `collect`, `analyze`, `report`, `run`(전체), `ingest`(JSONL). 의존성 최소화(런타임 의존 = `openai` 만).
- 설정: `config.toml`(갤러리 목록, 기간, rate limit, LLM base_url/model/api_key_env) + env.

## 4. 데이터 흐름 예

```
dch run --gallery crypto --days 7
  1) collect: 목록→본문→댓글 수집, SQLite upsert (재실행 시 이어받기)
  2) analyze: 기간 내 데이터 조회 → 청킹 → LLM map-reduce → analyses 저장
  3) report: Markdown + JSON 렌더 → reports/crypto/...
```

## 5. 오류 처리

- **스크래퍼**: 429/캡차/차단 페이지 감지 → 현재까지 수집분 저장 후 정지, 원인 보고. 타임아웃/재시도(지수 백오프, 최대 3회).
- **LLM**: 호출 실패 재시도(백오프), JSON 파싱 실패 시 1회 repair 재요청, 청크 단위 격리(부분 실패가 전체를 죽이지 않음).
- **전체**: 모든 스테이지 멱등. `runs` 테이블에 단계별 상태 기록.

## 6. 테스트 전략

- 단위: 정규화기, 청커, JSON repair, store upsert — 순수 함수/임시 DB.
- 스크래퍼: **저장된 HTML fixture**로 파서 테스트(테스트에서 실네트워크 없음).
- 분석기: 기록된 LLM 응답 fixture(golden)로 오프라인 테스트.
- 통합: `dch ingest + analyze + report` 를 fixture JSONL로 종단 테스트. 라이브 스모크(`make smoke`)는 키 있을 때 선택 실행.

## 7. 책임 있는 연구 제약

- 공개 데이터만, 연구 목적, 예의적 rate limit, 개인정보는 리포트에 미포함(작성자 해시), 원시 데이터는 로컬 SQLite에만 보관.

## 8. 기술 스택

- Python 3.11+, 런타임 의존: `openai`. 개발: `pytest`, `ruff`. 그 외 전부 stdlib.

## 9. 리스크와 대응

| 리스크 | 대응 |
|---|---|
| DC 인사이드 차단/캡차 (가장 큰 리스크) | rate limit 디폴트 보수적, 쿠키/UA 설정 지원, 차단 감지 시 정지, 파일 인제스트 탈출구 |
| 12.7B 모델의 구조화 출력 품질 | 스키마 단순화, repair 재시도, 청크 축소 옵션, 커버리지 투명 표시 |
| 갤러리별 로그인 필요 | 사전 감지 후 skip + 리포트에 명시 |
