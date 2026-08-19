# dc-harness

DC Inside 갤러리별 관심사·여론·트렌드·니즈(VOC)를 분석하는 연구용 하네스.

## 설치

    python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

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

## 온톨로지 (의미 계층)

- 정의: `dc_harness/ontology/ontology.toml` (유일 원천). `dch ontology`로 인쇄.
- 원본(posts/comments)은 불변, 분석 결과는 파생 객체(obj_*)로 run 단위 SNAPSHOT 저장.
- 모든 파생 행은 run_id·prompt_version·근거 글 번호를 포함 (lineage).
- 탐색: `dch query --object Topic --gallery crypto` / `dch show --gallery crypto --post 101`
- 질의: `dch ask --gallery crypto "최근 관심사는?"` (읽기 전용 도구 3종, 인용 강제)
- 규칙: CONVENTIONS.md 참조. 모든 LLM 호출은 llm_calls에 감사 기록됨.
