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
| Ingestor | 문서 파싱 및 정규화 (PDF/PPTX/DOCX → 텍스트 청크) |
| Embedding Model | 텍스트 → 1536-dim 벡터 (`text-embedding-3-small`) |
| Vector Store | 벡터·메타데이터 저장 및 검색 (ChromaDB) |
| Request Analyzer | 자유 서술 → 구조화 쿼리 (LLM 1차 호출) |
| Hybrid Retriever | 메타데이터 필터 + 벡터 검색 결합 → top-k 선정 |
| Draft Generator | 레퍼런스 기반 섹션별 초안 생성 (LLM 2차 호출) |
| PPT Assembler | 디자인 템플릿에 생성 텍스트 삽입 → `.pptx` 파일 출력 |

---

## 🛠️ 기술 스택

| 구성요소 | 기술 |
|---------|------|
| 언어 | Python 3.11 |
| RAG 프레임워크 | LangChain |
| Vector Store | ChromaDB (로컬, 파일 기반 영속성) |
| Embedding | OpenAI `text-embedding-3-small` (1536-dim) |
| LLM | Anthropic Claude Sonnet 4.6 |
| PPT 생성 | python-pptx |
| UI | Streamlit |
| 의존성 관리 | pip + requirements.txt |

---

## 📁 프로젝트 구조

```
ProposalPilot/
├── docs/
│   ├── document-metadata.csv          # 21개 문서 메타데이터 (11개 컬럼)
│   ├── 디자인 샘플/                   # 회사소개서의 디자인 양식
│   └── 과거 제안서 자료(가상데이터)/   # PPTX 21개
│
├── src/
│   ├── ingestor.py         # 문서 파싱 및 청킹
│   ├── embedder.py         # 임베딩 생성 및 ChromaDB 저장
│   ├── retriever.py        # 하이브리드 검색 (메타데이터 필터 + 벡터)
│   ├── analyzer.py         # Request Analyzer (LLM 1차)
│   ├── generator.py        # Draft Generator (LLM 2차)
│   └── assembler.py        # PPT Assembler (python-pptx)
│
├── output/                 # 생성된 초안 저장 디렉토리
│
├── ingest.py               # 인덱싱 실행 스크립트
├── run.py                  # 전체 파이프라인 실행 스크립트
├── app.py                  # Streamlit 웹 UI
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
python run.py --scenario "자동차 신차 런칭을 위한 XR 체험 캠페인 제안"
# output/ 에 proposal_draft_YYYYMMDD_HHMMSS.pptx, retrieval_log.json 생성
```

**웹 UI**
```bash
streamlit run app.py
```

---

## 🔍 핵심 기능

### 1. 하이브리드 검색

단순 키워드 검색의 한계를 넘어, **메타데이터 필터링**과 **시맨틱 벡터 검색**을 결합한 2단계 검색을 수행합니다.

```
최종 점수 = α × metadata_score + (1-α) × semantic_score
           (α = 0.4 기본값)
```

- **메타데이터 필터**: 산업군, 프로젝트 유형, 문서 연도 기반 하드 필터링
- **시맨틱 검색**: 자유 서술 임베딩 → 코사인 유사도 기반 소프트 랭킹
- **재랭킹**: 하이브리드 스코어 기준 최종 top-3 선정 (다양성 보장)

### 2. 레퍼런스 기반 PPT 자동 생성

검색된 top-1 PPTX를 디자인 템플릿으로 복사 후, LLM이 생성한 텍스트로 교체합니다. 배경·레이아웃·폰트 등 디자인 요소는 그대로 유지됩니다.

- 섹션별 헤드라인 / 서브타이틀 / 불릿 포인트 자동 생성
- 레퍼런스 고객사명·캠페인명은 `[고객사]`, `[제품명]` 플레이스홀더로 치환
- 생성 근거를 `retrieval_log.json`에 기록

### 3. 추천 근거 추적

```json
// retrieval_log.json 예시
{
  "query": "자동차 신차 런칭 XR 체험 캠페인",
  "top_references": [
    {
      "doc_id": "OP-S1-01",
      "industry": "자동차",
      "project_type": "브랜드/캠페인 전략",
      "hybrid_score": 0.87,
      "metadata_score": 0.80,
      "semantic_score": 0.91
    }
  ]
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

| 단계 | API | 예상 비용 |
|------|-----|---------|
| 인덱싱 (1회) | OpenAI Embeddings | ~$0.004 |
| 제안서 생성 (1회) | Claude Sonnet 4.6 | ~$0.05 |
| **테스트 10회 기준** | | **≈ $0.50** |

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
