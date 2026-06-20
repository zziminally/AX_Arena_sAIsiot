# DEVLOG.md — 시행착오·개발 과정 로그

> 발표 시 "어떤 AI 도구를 어떤 순서로 사용했고, 어떤 시행착오를 겪었는가"를 설명하기 위한 기록.  
> 에러, 시도, 실패, 해결, 성공 모두 기록. 사소한 것도 기록 대상.

---

## 형식

```
## [날짜] 작업 제목
**단계**: Phase N — 모듈명
**시도한 것**: 무엇을 어떻게 시도했나
**결과**: 성공 / 실패 / 부분 성공
**문제**: 무엇이 왜 안됐나 (실패·부분 성공인 경우)
**해결**: 어떻게 해결했나
**소요 시간**: 예상 vs 실제
**배운 것**: 다음에 같은 상황에서 어떻게 할 것인가
```

---

## [2026-06-20] SPEC.md 초안 작성 완료

**단계**: Phase 0 이전 — 설계 단계  
**시도한 것**: 과제 요건 분석 후 전체 시스템 설계를 SPEC.md로 문서화  
**결과**: 초안 완성. 승인 대기 중  
**소요 시간**: (설계 단계)  
**다음 단계**: 미결 질문(Q1~Q7) 답변 수령 후 기술 스택 확정 → Phase 0 환경 설정 시작

---

---

## [2026-06-20] Phase 0 완료 — 환경 설정

**단계**: Phase 0  
**시도한 것**: venv(Python 3.11) 확인 후 requirements.txt 작성 및 패키지 설치  
**결과**: 성공  
**설치 패키지**: anthropic, openai, langchain + langchain-openai/anthropic/community, chromadb, python-pptx, streamlit, python-dotenv, pandas  
**확인 사항**: `import` 전체 OK, `.env` API 키 양쪽 설정 확인, 데이터 경로(`docs/`) 접근 정상  
**소요 시간**: 약 10분  
**다음 단계**: Phase 1 — PPTX 파싱 + CSV 로딩 + ChromaDB 인덱싱

---

## [2026-06-20] Phase 1 완료 — 인덱싱 파이프라인

**단계**: Phase 1  
**시도한 것**: PPTX 파싱 → 섹션 단위 청킹 → ChromaDB 인덱싱  
**결과**: 성공 (171청크 / 21문서, 6초)

**시행착오**:
- PPTX 파일 두 가지 섹션 구분 스타일 발견: `"01 제안 배경..."` vs `"ACT 02"` 코드형
  - 원인: 섹션명을 구분 슬라이드 텍스트에서 추출했는데 일부 파일은 구분 슬라이드가 의미 없는 코드만 포함
  - 해결: 섹션명을 구분 슬라이드 다음 첫 번째 콘텐츠 슬라이드의 첫 줄에서 추출 (`_extract_section_name`)
- CSV 문서 수: 21개로 잘못 기재 → 실제 20개 (PPTX 22개 파일 중 중복 2개)
- 폴더명 `과거 제안서 자료(가상데이터)` → `mock_data` 반영
- PDF(회사소개서) 추가: ACT 단위 5청크, 처음엔 페이지마다 분리됨 → ACT 번호별 병합으로 수정

**소요 시간**: 약 45분  
**다음 단계**: Phase 2 — Hybrid Retriever (메타데이터 필터 + 시맨틱 점수 결합)

---

## [2026-06-20] Phase 2 완료 — Hybrid Retriever

**단계**: Phase 2  
**시도한 것**: LLM Request Analyzer + 메타데이터 스코어링 + ChromaDB 시맨틱 검색 결합  
**결과**: 성공

**설계 포인트**:
- Request Analyzer (Claude): 자유 텍스트 → 구조화 JSON (industry, project_type, key_needs_keywords 등)
- 메타데이터 스코어: industry 정확일치 0.5 / 별칭 0.25 / 확장레퍼런스 0.1 + project_type 키워드 overlap × 0.3
- 하이브리드 = 0.4 × metadata + 0.6 × semantic (cosine 기반)
- 동일 project_type 최대 2개 슬롯 — 다양성 캡 적용

**시행착오**:
- `max_tokens=512` → JSON 절단. `max_tokens=1024`로 수정
- INDUSTRY_ALIASES에 CSV 실제값("자동차 제조 기업", "프리미엄 가전 브랜드" 등) 수동 추가 필요

**소요 시간**: 약 30분  
**다음 단계**: Phase 3 — Draft Generator + PPT Assembler

---

## [2026-06-20] Phase 3 완료 — Draft Generator + PPT Assembler

**단계**: Phase 3  
**시도한 것**: Claude 단일 호출 8섹션 JSON 생성 → 검색된 PPTX 복사 후 텍스트 교체  
**결과**: 성공 (3개 검증 시나리오 모두 PPTX 출력 확인)

**검증 시나리오 결과**:

| 시나리오 | 참조 문서 (Top-1) | 생성 파일 | 처리 시간 |
|---------|------------------|----------|----------|
| 자동차 XR | OP-S1-03 | draft_신차_출시_XR_통합_체험_마케팅_전략_제안서.pptx | ~73s |
| 가전 hybrid | OP-S2-03 | draft__고객사__프리미엄_가전_신제품_체험_마케팅_전략_제안서.pptx | ~70s |
| 식음료 popup | OP-S3-01 | draft__고객사___제품명__신규_브랜드_런칭_체험_마케팅_전략_제안.pptx | ~70s |

**검색 정확도 확인**:
- 자동차 XR → 자동차 산업 문서 3개 중 2개(OP-S1-03, OP-S1-01) + 확장 레퍼런스(OP-S4-02) 혼합 ✓
- 가전 hybrid → 가전 산업 문서 2개(OP-S2-03, OP-S2-01) + 확장 레퍼런스(OP-S4-02) ✓
- 식음료 popup → 식음료 산업 문서 3개(OP-S3-01, OP-S3-02, OP-S3-03) 완전 매칭 ✓

**시행착오**:
- `prs.slides[i]` → `AttributeError: 'list' object has no attribute 'rId'`. `for slide in prs.slides` 이터레이션으로 수정
- 텍스트 교체 시 기존 `<a:r>` 노드 수 불일치 → lxml로 `<a:p>` 전체 삭제 후 재삽입
- 섹션명 매칭 실패 케이스: 정확 매칭 + 부분 매칭(in 연산) 2단계 폴백 적용
- 처리 시간 ~70s (목표 ≤3분 충족) — 주로 API 호출 2회 합산

**소요 시간**: 약 60분  
**다음 단계**: Phase 4 — Streamlit Web UI

---

## [2026-06-20] Phase 4 완료 — Streamlit Web UI

**단계**: Phase 4  
**시도한 것**: `app.py` — Streamlit 기반 웹 UI 구현  
**결과**: 성공 (http://localhost:8501 정상 서빙 확인)

**구현 기능**:
- 자유 텍스트 입력 폼 + 예시 시나리오 버튼 3종 (자동차 XR / 가전 hybrid / 식음료 popup)
- "제안서 생성" 버튼 → `retrieve → generate_draft → assemble` 파이프라인 실행
- `st.status()` 진행 표시 (3단계: 검색 / 초안 생성 / PPT 파일 생성)
- 검색 결과 패널: Top-3 레퍼런스 카드 (Hybrid/Semantic/Metadata 점수 + 섹션 텍스트 미리보기)
- 초안 미리보기 패널: 표지 + 8섹션 (헤드라인 / 서브타이틀 / 불릿 / 발표 노트)
- PPTX 다운로드 버튼 (브라우저 직접 다운로드)
- 처리 시간 표시 / 요청 분석 상세 expander

**소요 시간**: 약 20분  
**처리 시간 측정**: ~70초 (목표 ≤3분 충족)

---

## [2026-06-20] 고도화 1단계 — 검색 품질 개선

**단계**: 고도화 Phase 1 — retriever.py 개선 + evaluator.py 신규  
**결과**: 성공

**발견한 문제**:
- `_metadata_score()` 키워드 매칭이 정확 문자열 비교 → "팝업 스토어" ≠ "F&B 팝업" → OP-S3-02 keyword_score = 0
- 섹션 집계 max pooling → OP-S4-02(확장 레퍼런스)의 XR 섹션 하나가 자동차·가전 시나리오 top-3에 침투
- 톤앤매너가 메타데이터 스코어에 미반영

**적용한 수정**:
1. `_soft_keyword_match()` 추가 — 토큰 split 기반 부분 매칭
2. 가중치 조정: project_type 0.30→0.25, key_needs 0.20→0.15, tone 0.10 신규 추가
3. 섹션 집계: max → top-2 평균

**검증**:
- `src/evaluator.py` 신규 작성 — LLM 호출 없이 3개 사전 정의 테스트 케이스로 P@3/MRR/H-P@3 계산
- Alpha sweep(0.2~0.7): 모든 alpha에서 P@3=1.0, MRR=1.0 → alpha-insensitive 확인 → 0.4 유지

**개선 결과**:
| 시나리오 | 개선 전 | 개선 후 |
|---------|---------|---------|
| 자동차 XR | S1-03, S1-01, **S4-02** | S1-03, S1-01, **S1-02** ✓ |
| 가전 hybrid | S2-03, S2-01, **S4-02** | S2-01, S2-03, **S2-05** ✓ |
| 식음료 popup | S3-01, S3-02, S3-03 | S3-01, S3-02, S3-03 ✓ (유지) |

**소요 시간**: 약 30분  
**다음 단계**: 고도화 2단계 — 안정성 (LLM 출력 검증 + 에러 핸들링)

---

## [2026-06-20] 고도화 2단계 — 안정성 강화

**단계**: 고도화 Phase 2 — validator.py 신규 + retriever/generator/run/app 에러 핸들링 추가  
**결과**: 성공

**추가된 보호 장치**:

| 위치 | 처리 |
|------|------|
| `src/validator.py` | `validate_query()`: 필수 필드 누락 감지 / `validate_draft()`: 구조 이상 감지 / `enforce_limits()`: 자·줄 수 강제 절사 |
| `src/retriever.py` `analyze_request()` | 파싱 실패·검증 실패 시 최대 2회 재시도, 3회 모두 실패 시 명확한 RuntimeError |
| `src/generator.py` `generate_draft()` | 메인 초안 최대 3회 재시도. 슬라이드2는 best-effort (실패 시 빈 배열, 크래시 없음) |
| `run.py` | 3단계 각각 try/except, 실패 시 오류 메시지 출력 후 sys.exit(1) |
| `app.py` | 3단계 각각 try/except, 실패 시 st.error() + st.stop() |

**검증**:
- `validate_query({industry: 자동차})` → `ValueError: query missing required fields: [...]` ✓
- `enforce_limits()`: headline 80자 → 45자, bullets 7개 → 5개 절사 ✓

**소요 시간**: 약 20분  
**다음 단계**: 고도화 3단계 — UX (스트리밍 출력, 섹션 재생성)

---

## [2026-06-20] 고도화 3단계 — UX: 스트리밍 출력

**단계**: 고도화 Phase 3 — app.py 스트리밍  
**결과**: 성공

**변경 내용**:
- `generate_draft()` 호출을 `build_prompts()` + Anthropic `messages.stream()` 컨텍스트로 교체
- 스트림 중 `section_name` 필드를 정규식으로 실시간 파싱 → `st.empty()` 박스에 "섹션 N/8 — 마지막 섹션: ..." 진행 표시
- slide-2 보조 콘텐츠는 스트리밍 완료 후 별도 non-streaming 호출 (best-effort)
- JSON 파싱·검증·limit 강제는 스트리밍 완료 후 기존 validator 재사용

**효과**: 70초 완전 블로킹 → 토큰 도착 즉시 화면 업데이트. 사용자가 생성 진행 상황을 실시간 확인 가능

**소요 시간**: 약 20분

<!-- 이후 개발 과정은 아래에 추가 -->
