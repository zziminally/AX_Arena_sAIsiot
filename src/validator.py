"""
Output validators and limit enforcers for LLM responses.
Raises ValueError with a descriptive message so callers can retry.
"""
from typing import Any, Dict

from src.config import MAX_HEADLINE_LEN, MAX_BULLET_LEN, MAX_BULLETS

_REQUIRED_QUERY = {"industry", "project_type", "key_needs_keywords", "query_text", "tone_and_manner"}


def validate_query(query: Dict[str, Any]) -> None:
    """Raise ValueError if the Request Analyzer output is missing required fields."""
    if not isinstance(query, dict):
        raise ValueError(f"query is not a dict: {type(query)}")
    missing = [k for k in _REQUIRED_QUERY if not query.get(k)]
    if missing:
        raise ValueError(f"query missing required fields: {missing}")
    if not isinstance(query.get("key_needs_keywords"), list):
        raise ValueError("key_needs_keywords must be a list")


def validate_draft(draft: Dict[str, Any]) -> None:
    """Raise ValueError if the Draft Generator output is structurally invalid."""
    if not isinstance(draft, dict):
        raise ValueError(f"draft is not a dict: {type(draft)}")

    cover = draft.get("cover")
    if not isinstance(cover, dict) or not cover.get("title"):
        raise ValueError("draft.cover.title is missing or empty")

    sections = draft.get("sections")
    if not isinstance(sections, list) or len(sections) < 6:
        raise ValueError(f"draft.sections must have ≥6 items, got {len(sections) if isinstance(sections, list) else sections}")

    for i, sec in enumerate(sections):
        if not sec.get("section_name"):
            raise ValueError(f"sections[{i}].section_name is empty")
        if not sec.get("headline"):
            raise ValueError(f"sections[{i}].headline is empty")
        if not isinstance(sec.get("bullets"), list) or len(sec["bullets"]) == 0:
            raise ValueError(f"sections[{i}].bullets is missing or empty")


def enforce_limits(draft: Dict[str, Any]) -> Dict[str, Any]:
    """
    Truncate text fields to configured limits in-place.
    Guarantees the assembler never receives oversized strings.
    """
    cover = draft.get("cover", {})
    cover["title"] = (cover.get("title") or "")[:50]
    cover["subtitle"] = (cover.get("subtitle") or "")[:80]

    for sec in draft.get("sections", []):
        sec["headline"] = (sec.get("headline") or "")[:MAX_HEADLINE_LEN]
        sec["subtitle"] = (sec.get("subtitle") or "")[:80]
        bullets = (sec.get("bullets") or [])[:MAX_BULLETS]
        sec["bullets"] = [(b or "")[:MAX_BULLET_LEN] for b in bullets]

    for sec in draft.get("sections_slide2", []):
        sec["headline"] = (sec.get("headline") or "")[:MAX_HEADLINE_LEN]
        sec["subtitle"] = (sec.get("subtitle") or "")[:80]
        bullets = (sec.get("bullets") or [])[:MAX_BULLETS]
        sec["bullets"] = [(b or "")[:MAX_BULLET_LEN] for b in bullets]

    return draft
