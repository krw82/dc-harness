# CONVENTIONS — dc-harness 네이밍·변경 규칙 (1페이지 상한)

## 이름
- 객체·링크 api_name: 영문 PascalCase. 속성: camelCase. 한글은 description에만.
- 원본 컬럼명(DC HTML 등)을 이름으로 재사용 금지 — 업무 의미로 재명명.
- 새 Object/Link 정의 전 `krw-ontology-dc ontology --json | grep` 으로 기존 정의 검색 (중복 금지).
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
