import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict, Any, Optional

from src.config import (
    CHROMA_DIR, CHROMA_COLLECTION, OPENAI_API_KEY, EMBEDDING_MODEL, TOP_K
)


def _get_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    ef = embedding_functions.OpenAIEmbeddingFunction(
        api_key=OPENAI_API_KEY,
        model_name=EMBEDDING_MODEL,
    )
    return client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def index_chunks(chunks: List[Dict[str, Any]], batch_size: int = 50) -> None:
    """Upsert all chunks into ChromaDB in batches."""
    collection = _get_collection()
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        collection.upsert(
            ids=[c["chunk_id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )
        done = min(i + batch_size, len(chunks))
        print(f"  [{done}/{len(chunks)}] chunks indexed")


def search(
    query_text: str,
    n_results: int = TOP_K,
    where: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
    """
    Semantic search. Returns chunks sorted by cosine similarity (descending).
    distance is L2 by default but we set hnsw:space=cosine so distance ∈ [0,2],
    similarity = 1 - distance/2.
    """
    collection = _get_collection()
    kwargs: Dict = {
        "query_texts": [query_text],
        "n_results":   n_results,
        "include":     ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    results = collection.query(**kwargs)

    hits = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({
            "text":           doc,
            "metadata":       meta,
            "distance":       dist,
            "semantic_score": max(0.0, 1.0 - dist / 2),
        })
    return hits


def count() -> int:
    return _get_collection().count()


def reset() -> None:
    """Drop and recreate the collection (use for re-indexing)."""
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    client.delete_collection(CHROMA_COLLECTION)
    print(f"  Collection '{CHROMA_COLLECTION}' reset.")
