"""
PPT Assembler: copies top-1 retrieved PPTX, replaces text content
with generated draft while preserving design/layout.
"""
import re
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from pptx import Presentation
from pptx.util import Pt

from src.config import OUTPUT_DIR, BOILERPLATE
from src.ingestor import _slide_text, _is_divider, _extract_section_name

PAGE_NUM_RE = re.compile(r"^\d{1,2}$")


# ── Text-frame utilities ──────────────────────────────────────────────────────

def _useful_shapes(slide) -> List[Tuple[int, Any]]:
    """Return (text_length, shape) for non-boilerplate text shapes, sorted desc."""
    result = []
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        t = shape.text_frame.text.strip()
        if t and t not in BOILERPLATE and not PAGE_NUM_RE.match(t):
            result.append((len(t), shape))
    return sorted(result, key=lambda x: -x[0])


def _overwrite_frame(tf, lines: List[str]) -> None:
    """
    Replace text frame content with given lines.
    Preserves font size/bold of the original first run where possible.
    Each line becomes one paragraph.
    """
    # Capture formatting from first run before we clear
    ref_size: Optional[int] = None
    ref_bold: Optional[bool] = None
    try:
        first_run = tf.paragraphs[0].runs[0]
        ref_size = first_run.font.size
        ref_bold = first_run.font.bold
    except (IndexError, AttributeError):
        pass

    # Remove all existing paragraph XML nodes
    from lxml import etree
    NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
    txBody = tf._txBody
    for p_elem in txBody.findall(f"{{{NS}}}p"):
        txBody.remove(p_elem)

    # Re-add paragraphs via python-pptx API
    for i, line in enumerate(lines):
        para = tf.add_paragraph()
        run = para.add_run()
        run.text = line
        if ref_size:
            run.font.size = ref_size
        if ref_bold is not None:
            run.font.bold = ref_bold


def _replace_cover(slide, cover: Dict) -> None:
    """Replace cover title and subtitle."""
    shapes = _useful_shapes(slide)
    if len(shapes) >= 1:
        _overwrite_frame(shapes[0][1].text_frame, [cover.get("title", "")])
    if len(shapes) >= 2:
        _overwrite_frame(shapes[1][1].text_frame, [cover.get("subtitle", "")])


def _replace_content_slide(slide, sec_draft: Dict) -> None:
    """
    Replace a content slide's text with generated draft content.
    Strategy:
      - Shortest substantial shape (≤ 50 chars): section header → keep or update
      - Medium shape: replace with headline
      - Largest shape: replace with subtitle + bullets
    """
    shapes = _useful_shapes(slide)
    if not shapes:
        return

    # Classify shapes by text length
    small  = [(l, s) for l, s in shapes if l <= 50]   # section header
    medium = [(l, s) for l, s in shapes if 50 < l <= 150]
    large  = [(l, s) for l, s in shapes if l > 150]

    headline = sec_draft.get("headline", "")
    subtitle = sec_draft.get("subtitle", "")
    bullets  = [f"• {b}" for b in sec_draft.get("bullets", [])]

    # Large shape → subtitle + bullets (or headline+bullets if no medium)
    if large:
        body_lines = []
        if not medium and headline:
            body_lines.append(headline)
        if subtitle:
            body_lines.append(subtitle)
        body_lines.extend(bullets)
        _overwrite_frame(large[0][1].text_frame, body_lines)

    # Medium shape → headline
    if medium and headline:
        _overwrite_frame(medium[0][1].text_frame, [headline])
    elif not large and shapes:
        # Fallback: use largest available shape
        body_lines = [headline] + bullets if headline else bullets
        _overwrite_frame(shapes[0][1].text_frame, body_lines)


# ── Section-to-slide mapping ──────────────────────────────────────────────────

def _map_sections_to_slides(prs: Presentation) -> Dict[str, List[int]]:
    """
    Parse PPTX and return {section_name: [slide_indices_of_content_slides]}.
    Slide 0 (cover) and Slide 1 (TOC) are excluded from the map.
    """
    texts = [_slide_text(s) for s in prs.slides]
    section_map: Dict[str, List[int]] = {}
    current_section: Optional[str] = None

    for i, text in enumerate(texts):
        if i < 2:  # skip cover and TOC
            continue
        if not text:
            continue
        if _is_divider(text):
            # Peek at next slide to get the section name
            next_content = texts[i + 1] if i + 1 < len(texts) else ""
            current_section = _extract_section_name(text, next_content)
            section_map[current_section] = []
        elif current_section is not None:
            section_map[current_section].append(i)

    return section_map


# ── Main assembly ─────────────────────────────────────────────────────────────

def assemble(draft: Dict[str, Any], template_pptx_path: str) -> Path:
    """
    Copy template PPTX and replace text content with generated draft.
    Returns the path of the saved output file.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Build output filename from cover title
    title_slug = re.sub(r"[^\w가-힣]", "_", draft["cover"].get("title", "proposal"))[:40]
    output_path = OUTPUT_DIR / f"draft_{title_slug}.pptx"

    shutil.copy(template_pptx_path, output_path)
    prs = Presentation(str(output_path))

    # 1. Cover slide
    _replace_cover(prs.slides[0], draft["cover"])

    # 2. Map section names → slide indices
    section_map = _map_sections_to_slides(prs)

    # 3. Replace content slides section by section
    for sec_draft in draft.get("sections", []):
        sec_name = sec_draft.get("section_name", "")
        # Try exact match first, then partial match
        slide_indices = section_map.get(sec_name)
        if slide_indices is None:
            for mapped_name, indices in section_map.items():
                if sec_name in mapped_name or mapped_name in sec_name:
                    slide_indices = indices
                    break
        if not slide_indices:
            continue

        # Replace first content slide of the section (the main content slide)
        for idx in slide_indices[:2]:
            _replace_content_slide(prs.slides[idx], sec_draft)

    prs.save(str(output_path))
    return output_path
