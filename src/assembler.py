"""
PPT Assembler: copies top-1 retrieved PPTX, replaces text while preserving
ALL formatting (color, font, size, spacing, bullet style) via XML deepcopy.
"""
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn

from src.config import OUTPUT_DIR, BOILERPLATE
from src.ingestor import _slide_text, _is_divider, _extract_section_name

NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PAGE_NUM_RE = re.compile(r"^\d{1,3}$")


# ── Format-preserving text replacement ───────────────────────────────────────

def _first_run(para_elem) -> Optional[Any]:
    """Return first <a:r> element in a paragraph, or None."""
    runs = para_elem.findall(f"{{{NS}}}r")
    return runs[0] if runs else None


def _set_para_text(para_elem, text: str) -> None:
    """
    Replace text in a single paragraph element while preserving ALL run formatting.
    Keeps <a:pPr> (paragraph props: spacing, indent, bullet, alignment) intact.
    Keeps <a:rPr> (run props: color, font, size, bold) from the first run.
    """
    runs = para_elem.findall(f"{{{NS}}}r")
    brs  = para_elem.findall(f"{{{NS}}}br")

    # Remove existing runs and line-break elements
    for elem in runs + brs:
        para_elem.remove(elem)

    if not runs:
        # No template run — create a bare run
        r = etree.SubElement(para_elem, qn("a:r"))
        t = etree.SubElement(r, qn("a:t"))
        t.text = text
        return

    # Clone first run (preserves <a:rPr> with color, font, size…)
    template_r = deepcopy(runs[0])
    t_elem = template_r.find(f"{{{NS}}}t")
    if t_elem is None:
        t_elem = etree.SubElement(template_r, qn("a:t"))
    t_elem.text = text
    para_elem.append(template_r)


def _set_tf_single(tf, text: str) -> None:
    """
    Replace text frame with a single line of text.
    Preserves paragraph and run formatting of the original first paragraph.
    """
    txBody = tf._txBody
    paras = txBody.findall(f"{{{NS}}}p")
    if not paras:
        return

    # Keep only the first paragraph
    for p in paras[1:]:
        txBody.remove(p)

    _set_para_text(paras[0], text)


def _set_tf_lines(tf, lines: List[str]) -> None:
    """
    Replace text frame with multiple lines (one paragraph per line).
    Each new paragraph is a deep-clone of the first original paragraph,
    so all formatting (bullet style, indent, font color, size) is preserved.
    """
    if not lines:
        return

    txBody = tf._txBody
    paras = txBody.findall(f"{{{NS}}}p")
    if not paras:
        return

    # Find best template paragraph: first one that has a run
    template_p = None
    for p in paras:
        if p.findall(f"{{{NS}}}r"):
            template_p = p
            break
    if template_p is None:
        template_p = paras[0]

    # Remove ALL existing paragraphs
    for p in paras:
        txBody.remove(p)

    # Create one paragraph per line, cloned from template
    for line in lines:
        new_p = deepcopy(template_p)
        _set_para_text(new_p, line)
        txBody.append(new_p)


def _set_tf_with_breaks_v2(tf, text: str) -> None:
    """
    Better version: preserve run format AND support \\n soft line breaks.
    """
    parts = [p.strip() for p in re.split(r"\\n|\n", text) if p.strip()]
    if not parts:
        return

    txBody = tf._txBody
    paras = txBody.findall(f"{{{NS}}}p")
    if not paras:
        return

    para = paras[0]
    for p in paras[1:]:
        txBody.remove(p)

    # Capture template run BEFORE removing
    runs = para.findall(f"{{{NS}}}r")
    template_r = deepcopy(runs[0]) if runs else None

    # Remove existing content from paragraph
    for elem in para.findall(f"{{{NS}}}r") + para.findall(f"{{{NS}}}br"):
        para.remove(elem)

    for i, part in enumerate(parts):
        if i > 0:
            br = etree.SubElement(para, qn("a:br"))
            # Copy rPr to break element so color/font is consistent
            if template_r is not None:
                rpr = template_r.find(f"{{{NS}}}rPr")
                if rpr is not None:
                    br.insert(0, deepcopy(rpr))

        if template_r is not None:
            new_r = deepcopy(template_r)
            t_elem = new_r.find(f"{{{NS}}}t")
            if t_elem is None:
                t_elem = etree.SubElement(new_r, qn("a:t"))
            t_elem.text = part
            para.append(new_r)
        else:
            r = etree.SubElement(para, qn("a:r"))
            t = etree.SubElement(r, qn("a:t"))
            t.text = part


# ── Shape classification ──────────────────────────────────────────────────────

def _text_shapes_by_area(slide) -> List[Tuple[int, Any]]:
    """
    Return (area_emu, shape) for non-boilerplate text shapes, sorted by area DESC.
    Area = width × height in EMU units.
    """
    result = []
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        t = shape.text_frame.text.strip()
        if not t or t in BOILERPLATE or PAGE_NUM_RE.match(t):
            continue
        area = shape.width * shape.height
        result.append((area, shape))
    return sorted(result, key=lambda x: -x[0])


# ── Cover slide ───────────────────────────────────────────────────────────────

def _replace_cover(slide, cover: Dict) -> None:
    """
    Replace cover title and subtitle.
    Strategy: shapes sorted by area — largest = main title, 2nd = subtitle.
    Uses _set_tf_with_breaks_v2 to support \\n in subtitle.
    """
    shapes = _text_shapes_by_area(slide)
    if not shapes:
        return

    title    = cover.get("title", "")
    subtitle = cover.get("subtitle", "")

    if len(shapes) >= 2:
        _set_tf_single(shapes[0][1].text_frame, title)
        _set_tf_with_breaks_v2(shapes[1][1].text_frame, subtitle)
    elif shapes:
        _set_tf_single(shapes[0][1].text_frame, title)


# ── Content slide ─────────────────────────────────────────────────────────────

def _replace_content_slide(slide, sec_draft: Dict) -> None:
    """
    Replace a content slide's text with generated draft content.

    Shape role assignment by area (EMU):
      - Largest shape  → body (subtitle line + bullet points)
      - 2nd largest    → headline
      - Smaller shapes → section header labels (do NOT modify)

    This is more reliable than the previous text-length heuristic because
    shape dimensions are fixed by the template design and don't change with content.
    """
    shapes = _text_shapes_by_area(slide)
    if not shapes:
        return

    headline = sec_draft.get("headline", "")
    subtitle = sec_draft.get("subtitle", "")
    bullets  = sec_draft.get("bullets", [])

    # Build body lines: subtitle first (if present), then each bullet as its own line
    body_lines: List[str] = []
    if subtitle:
        # Subtitle may contain \n markers — expand into separate body lines
        sub_parts = [p.strip() for p in re.split(r"\\n|\n", subtitle) if p.strip()]
        body_lines.extend(sub_parts)
    body_lines.extend(bullets)

    if len(shapes) >= 3:
        # 3+ shapes: largest=body, 2nd=headline, rest=section headers (skip)
        _set_tf_lines(shapes[0][1].text_frame, body_lines)
        _set_tf_single(shapes[1][1].text_frame, headline)
    elif len(shapes) == 2:
        # 2 shapes: larger=body, smaller=headline
        _set_tf_lines(shapes[0][1].text_frame, body_lines)
        _set_tf_single(shapes[1][1].text_frame, headline)
    else:
        # 1 shape: put everything in it
        all_lines = ([headline] if headline else []) + body_lines
        _set_tf_lines(shapes[0][1].text_frame, all_lines)


# ── Section-to-slide mapping ──────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """Normalize a section name for fuzzy matching."""
    return re.sub(r"[\s/·\-·또는|]", "", name).lower()


def _map_sections_to_slides(prs: Presentation) -> Dict[str, List[int]]:
    """
    Parse PPTX and return {section_name: [content_slide_indices]}.
    Skips slide 0 (cover) and slide 1 (TOC).
    """
    texts = [_slide_text(s) for s in prs.slides]
    section_map: Dict[str, List[int]] = {}
    current_section: Optional[str] = None

    for i, text in enumerate(texts):
        if i < 2:
            continue
        if not text:
            continue
        if _is_divider(text):
            next_text = texts[i + 1] if i + 1 < len(texts) else ""
            current_section = _extract_section_name(text, next_text)
            section_map[current_section] = []
        elif current_section is not None:
            section_map[current_section].append(i)

    return section_map


def _find_slide_indices(sec_name: str, section_map: Dict[str, List[int]]) -> List[int]:
    """
    Find slide indices for a section name with fuzzy matching.
    Priority: exact → normalized-exact → partial-overlap.
    """
    # 1. Exact match
    if sec_name in section_map:
        return section_map[sec_name]

    norm_query = _normalize(sec_name)

    # 2. Normalized exact match
    for mapped, indices in section_map.items():
        if _normalize(mapped) == norm_query:
            return indices

    # 3. Best partial overlap (longest common substring of normalized names)
    best_indices: List[int] = []
    best_overlap = 0
    for mapped, indices in section_map.items():
        norm_mapped = _normalize(mapped)
        # Count overlapping chars using set of substrings of length 3+
        overlap = sum(1 for k in range(len(norm_query) - 2)
                      if norm_query[k:k+3] in norm_mapped)
        if overlap > best_overlap:
            best_overlap = overlap
            best_indices = indices

    return best_indices if best_overlap >= 1 else []


# ── Main assembly ─────────────────────────────────────────────────────────────

def assemble(draft: Dict[str, Any], template_pptx_path: str) -> Path:
    """
    Copy template PPTX and replace text with generated draft.
    - Slide 0: cover
    - Per section: first content slide ← slide-1 draft
                   second content slide ← slide-2 draft (if available)
    Returns output file path.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    title_slug = re.sub(r"[^\w가-힣]", "_", draft["cover"].get("title", "proposal"))[:40]
    output_path = OUTPUT_DIR / f"draft_{title_slug}.pptx"

    shutil.copy(template_pptx_path, output_path)
    prs = Presentation(str(output_path))

    # 1. Cover
    _replace_cover(prs.slides[0], draft["cover"])

    # 2. Build section → slide index map
    section_map = _map_sections_to_slides(prs)

    # 3. Build slide-2 lookup: section_name → sec_draft
    slide2_lookup: Dict[str, Dict] = {}
    for s in draft.get("sections_slide2", []):
        slide2_lookup[s.get("section_name", "")] = s

    # 4. Replace content slides section by section
    for sec_draft in draft.get("sections", []):
        sec_name = sec_draft.get("section_name", "")
        slide_indices = _find_slide_indices(sec_name, section_map)
        if not slide_indices:
            continue

        # First content slide ← primary draft
        _replace_content_slide(prs.slides[slide_indices[0]], sec_draft)

        # Second content slide ← slide-2 draft (if available and exists)
        if len(slide_indices) >= 2:
            s2 = slide2_lookup.get(sec_name)
            if s2:
                _replace_content_slide(prs.slides[slide_indices[1]], s2)

    prs.save(str(output_path))
    return output_path
