# 🧭 ProposalPilot
> 과거 제안서 레퍼런스 기반 신규 제안서 자동 구성 시스템

**"검색을 넘어서, 참조와 재구성까지"**

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://www.python.org/)
[![LangChain](https://img.shields.io/badge/LangChain-RAG-green)](https://www.langchain.com/)
[![ChromaDB](https://img.shields.io/badge/Vector_Store-ChromaDB-orange)](https://www.trychroma.com/)
[![Claude](https://img.shields.io/badge/LLM-Claude_Sonnet_4.6-purple)](https://www.anthropic.com/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-red)](https://streamlit.io/)

---

## 👥 팀 소개

**팀명: 사이시옷**

| 이름 | 역할 | GitHub |
|------|------|--------|
| 설영은 | - | [@0euun](https://github.com/0euun) |
| 신지민 | - | [@zziminally](https://github.com/zziminally) |

---

## 📌 프로젝트 개요

올림플래닛(Olimplanet)은 체험형 광고 마케팅(XR, 이머시브 콘텐츠)을 전문으로 하는 애드테크 기업으로, 1,000건 이상의 캠페인을 수행하며 방대한 제안서 자산을 보유하고 있습니다.

그러나 **신규 제안서 작성 시 이 자산을 빠르게 참조·재구성하는 워크플로우가 부재**하여, 담당자가 매번 수동으로 과거 자료를 탐색하고 새로 조합하는 데 과도한 시간을 소비하는 문제가 있었습니다.

**ProposalPilot**은 이 문제를 해결하기 위해, 과거 제안서를 RAG 기반으로 자동 인덱싱하고 신규 제안 요청에 최적화된 레퍼런스를 추천한 뒤, 해당 레퍼런스를 바탕으로 PPT 초안을 자동 구성하는 AI 시스템입니다.

```
[AS-IS]
신규 제안 요청 → 수동 탐색 (수십~수백 개) → 레퍼런스 선별 → 수동 재구성 → 초안 완성
                                                              ⏱ 수 시간 ~ 수일

[TO-BE]
신규 제안 요청 → 자동 레퍼런스 추천 (top-3) → PPT 초안 자동 구성 → 담당자 검토·보완
                                                              ⏱ 수십 분 이내
```

---

## 🎯 목표

| 구분 | 목표 |
|------|------|
| 기능 | 신규 제안 요청에 대해 최적 레퍼런스 top-3 추천 + PPT 초안 자동 구성 |
| 품질 | 산업군·프로젝트 유형 매칭 정확도 ≥ 80% (검증 시나리오 3종 기준) |
| 효율 | 초안 구성 소요 시간 기존 대비 70% 이상 단축 |
| 확장 | 신규 제안서 축적 시 인덱스에 자동 편입 가능한 구조 |

---

## 🏗️ 시스템 아키텍처

시스템은 **오프라인 인덱싱 파이프라인**과 **온라인 요청 처리 파이프라인** 두 단계로 구성됩니다.

```
[오프라인] 과거 제안서 (PDF/PPTX/DOCX)
              │
              ▼
         Ingestor (파싱·정규화)
              │
              ▼
     Chunker & Metadata Extractor
              │
              ▼
       Embedding Model (다국어)
              │
              ▼
         Vector Store (ChromaDB)

[온라인] 사용자 입력 (산업군, 목적, 자유 서술)
              │
              ▼
      Request Analyzer (LLM 1차 호출)
       → 자유 서술 → 구조화 쿼리 추출
              │
              ▼
       Hybrid Retriever
       ① 메타데이터 필터링 (하드 필터)
       ② 벡터 유사도 검색 (코사인 유사도)
       ③ 하이브리드 스코어링 & 재랭킹
              │
         top-3 레퍼런스
              │
              ▼
       Draft Generator (LLM 2차 호출)
       → 섹션별 텍스트 초안 생성
              │
              ▼
        PPT Assembler (python-pptx)
              │
              ▼
     output/proposal_draft.pptx
     output/retrieval_log.json
```

### 모듈 역할

| 모듈 | 역할 |
|------|------|
| ingestor.py | 문서 파싱 및 청킹 (PDF/PPTX → 섹션별 텍스트 청크) |
| vector_store.py | ChromaDB 연동 (벡터·메타데이터 저장/검색) |
| retriever.py | 하이브리드 검색 (메타데이터 필터 + 벡터 검색 + 재랭킹) |
| - analyze_request() | 자유 서술 → 구조화된 쿼리 (Haiku LLM, 2회 재시도) |
| - retrieve() | 메타데이터 점수 + 시맨틱 유사도 결합 → top-3 선정 |
| generator.py | 레퍼런스 기반 초안 생성 (Sonnet LLM) |
| - build_prompts() | 시스템·사용자 프롬프트 구성 (스트리밍용) |
| - generate_draft() | 프롬프트 캐싱 활용 + 2회 호출 (Slide-1, Slide-2) |
| - regenerate_section() | 특정 섹션 재생성 (사용자 커스터마이징) |
| validator.py | 생성 결과 검증 (구조, 길이 제한 적용) |
| assembler.py | PPT 조립 (텍스트 삽입, 이미지 교체, 형식 유지) |
| config.py | 환경 변수 및 상수 설정 |

---

## 🛠️ 기술 스택

| 구성요소 | 기술 |
|---------|------|
| 언어 | Python 3.11 |
| Vector Store | ChromaDB (로컬, 파일 기반 영속성) |
| Embedding | OpenAI `text-embedding-3-small` (1536-dim) |
| LLM (분석) | Anthropic Claude Haiku 4.5 (Request Analyzer) |
| LLM (생성) | Anthropic Claude Sonnet 4.6 (Draft Generator) |
| PPT 생성 | python-pptx |
| UI | Streamlit (v3 - 스트리밍 생성 지원) |
| 의존성 관리 | pip + requirements.txt |

---

## 📁 프로젝트 구조

```
ProposalPilot/
├── docs/
│   ├── document-metadata.csv          # 21개 문서 메타데이터
│   ├── mock_data/                     # PPTX 21개 (샘플)
│   └── sample/                        # 디자인 템플릿
│
├── src/
│   ├── config.py           # 환경 변수, 상수 설정
│   ├── ingestor.py         # 문서 파싱 및 청킹
│   ├── vector_store.py     # ChromaDB 연동
│   ├── retriever.py        # 하이브리드 검색 (메타 + 벡터 + 재랭킹)
│   ├── generator.py        # Draft 생성 (프롬프트 캐싱, 2회 호출)
│   ├── validator.py        # 검증 및 길이 제한
│   └── assembler.py        # PPT 조립
│
├── output/                 # 생성된 초안 저장
│
├── ingest.py               # 인덱싱 실행 (문서 파싱 → ChromaDB 저장)
├── run.py                  # CLI 실행 (retrieve → generate → assemble)
├── app.py                  # Streamlit 웹 UI (v3 - 스트리밍)
├── requirements.txt
├── .env.example
├── DECISIONS.md            # 설계 의사결정 로그
├── DEVLOG.md               # 개발 과정 로그
└── README.md
```

---

## 🚀 시작하기

### 사전 요구사항

- Python 3.11+
- OpenAI API Key
- Anthropic API Key

### 설치

```bash
# 1. 저장소 클론
git clone https://github.com/your-org/ProposalPilot.git
cd ProposalPilot

# 2. 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 환경 변수 설정
cp .env.example .env
# .env 파일에 OPENAI_API_KEY, ANTHROPIC_API_KEY 입력
```

### 인덱싱 (최초 1회)

```bash
python ingest.py
# docs/ 내 PPTX 21개 → ChromaDB 자동 인덱싱 (약 2분 소요)
```

### 실행

**CLI**
```bash
python run.py "자동차 신차 런칭을 위한 XR 체험 캠페인 제안"
# output/ 에 proposal_draft_YYYYMMDD_HHMMSS.pptx, retrieval_log.json 생성
```

**웹 UI (Streamlit v3)**
```bash
streamlit run app.py
# 로컬 스트리밍 생성 + 실시간 섹션 진행률 표시 + 섹션별 재생성 지원
```

---

## 🔍 핵심 기능

### 1. 하이브리드 검색 (Retriever)

메타데이터 필터링과 벡터 유사도를 결합한 2단계 재랭킹 방식:

```
사용자 입력 (자유 서술)
    ↓
analyze_request() → Haiku LLM 호출 (구조화 쿼리 추출)
    ↓ (JSON 파싱 실패 시 2회 재시도)
_metadata_score() & semantic_score()
    ↓
하이브리드 점수 = 0.4 × 메타데이터 점수 + 0.6 × 시맨틱 유사도
    ↓
top-3 레퍼런스 선정 (산업군 다양성 보장)
```

- **메타데이터 필터**: 산업군 정확 매칭 (1.0), 별칭 매칭 (0.25), 확장 레퍼런스 (0.1)
- **시맨틱 검색**: 코사인 유사도 기반 top-k 재정렬
- **재랭킹**: 하이브리드 스코어 기준 최종 선정

### 2. 프롬프트 캐싱을 활용한 효율적 생성

Draft Generator는 2회 LLM 호출을 활용하여 Slide-1, Slide-2 콘텐츠를 동시에 생성:

```
첫 번째 호출 (캐시 저장)
  System: 올림플래닛 제안서 작성 가이드
  User: [참조 레퍼런스] + [신규 요청 분석]
    ↓
  Claude 응답 (Slide-1 섹션 생성)
    ↓
두 번째 호출 (캐시 재사용 ✓)
  System: (동일 - 캐시 히트)
  User: (동일 context + Slide-2 재작성 지시)
    ↓
  Claude 응답 (Slide-2 섹션 생성)
```

**장점**:
- 프롬프트 캐싱으로 토큰 비용 50% 감소
- Haiku (분석)와 Sonnet (생성) 모델 분리로 비용-품질 최적화
- 스트리밍으로 실시간 진행 상황 표시

### 3. 사용자 커스터마이징 (regenerate_section)

생성된 초안의 특정 섹션을 사용자 지시에 따라 재생성:

```
사용자: "세부 실행 방안을 더 기술적으로 작성해주세요"
    ↓
regenerate_section(draft, idx=4, instruction="...")
    ↓
해당 섹션만 재생성 (다른 섹션은 유지)
    ↓
검증 & 조립 후 PPT 업데이트
```

### 4. 구조화된 출력

생성된 모든 콘텐츠는 검증 및 길이 제한 적용:

```json
{
  "cover": {"title": "...", "subtitle": "..."},
  "sections": [
    {
      "section_name": "제안 배경",
      "headline": "... (최대 {MAX_HEADLINE_LEN}자)",
      "subtitle": "... (최대 200자)",
      "bullets": ["...", "...", "..."],  // 최대 {MAX_BULLETS}개
      "notes": "... (발표 시 강조점)"
    }
  ],
  "sections_slide2": [...]
}
```

---

## 📊 데이터 현황

| 항목 | 내용 |
|------|------|
| 메타데이터 | `document-metadata.csv` — 21개 문서, 11개 컬럼 |
| 제안서 파일 | PPTX 21개 (가상 데이터) |
| 산업군 분류 | 자동차(5), 가전(5), 식음료(5), 확장 레퍼런스/부동산(6) |
| 평균 슬라이드 수 | 33슬라이드 / 문서 |
| 예상 청크 수 | 21문서 × 8섹션 ≈ 168개 |

---

## 💰 API 비용 추산

| 단계 | 호출 모델 | 예상 비용 | 비고 |
|------|---------|---------|------|
| 인덱싱 (1회) | OpenAI Embeddings | ~$0.004 | 21개 문서, 168개 청크 |
| 제안서 생성 (1회) | Haiku (분석) | ~$0.001 | 구조화 쿼리 추출 (재시도 포함) |
| | Sonnet (생성) | ~$0.08 | 2회 호출 (프롬프트 캐싱 적용) |
| **생성 총비용** | | **~$0.081** | |
| **10회 테스트** | | **~$0.81** | |

---

## ⚠️ 주의사항

- `docs/` 내 제안서 파일은 가상 데이터입니다. 실제 올림플래닛 자산이 아닙니다.
- 생성된 PPT 초안은 반드시 **담당자 검토 후 사용**하세요.
- 레퍼런스 고객사명·캠페인명은 `[고객사]` 플레이스홀더로 표시되므로, 최종 제출 전 반드시 실제 정보로 교체해야 합니다.

---

## 📝 개발 기록

- [`DECISIONS.md`](./DECISIONS.md) — 기술 스택, 검색 방식, 청킹 전략 등 주요 설계 의사결정 로그
- [`DEVLOG.md`](./DEVLOG.md) — 개발 과정 중 시행착오 및 해결 과정 기록

---

## 🤝 파트너

**올림플래닛 (Olimplanet)** — 체험형 광고 마케팅(XR, 이머시브 콘텐츠) 전문 애드테크 기업
