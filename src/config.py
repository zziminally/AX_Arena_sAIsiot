from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent.parent
DOCS_DIR = BASE_DIR / "docs"
PROPOSALS_DIR = DOCS_DIR / "mock_data"
SAMPLE_DIR    = DOCS_DIR / "sample"
METADATA_CSV = DOCS_DIR / "document-metadata.csv"
CHROMA_DIR = BASE_DIR / ".chroma"
OUTPUT_DIR = BASE_DIR / "output"

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Model settings
EMBEDDING_MODEL = "text-embedding-3-small"
LLM_MODEL = "claude-sonnet-4-6"

# Retrieval settings
CHROMA_COLLECTION = "proposals"
TOP_K = 5        # 벡터 검색 후보
FINAL_TOP_K = 3  # 최종 추천 수
ALPHA = 0.4      # 메타데이터 가중치 (1-ALPHA = 시맨틱 가중치)

# PPT text limits
MAX_HEADLINE_LEN = 45
MAX_BULLET_LEN = 75
MAX_BULLETS = 5

# Section divider detection
SECTION_DIVIDER_MAX_LEN = 30
BOILERPLATE = {"OLIMPLANET", "© OLIMPLANET Reference Asset"}
