"""Fixed-size (strategy A) and paragraph-aware (strategies B/C) chunking.

Both work *within one DocumentPage* (one printed page x one chapter), so every chunk
keeps a single ``page`` and ``chapter`` and its character span inside that page text
(``char_start``/``char_end``).  Chunk IDs are deterministic, so re-ingesting the same
corpus with the same parameters yields the same IDs (no duplicates).
"""
from __future__ import annotations

import re

from .models import Chunk, DocumentPage

_SENTENCE_END_RE = re.compile(r"[.!?][\"”’]?\s+")


def _make_chunk(page: DocumentPage, start: int, end: int, kind: str, params: dict) -> Chunk:
    chapter = page.metadata["chapter"]
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page}:ch{chapter}:{start}-{end}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=page.text[start:end].strip(),
        metadata={**page.metadata, "char_start": start, "char_end": end,
                  "chunking": kind, **params},
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Overlapping character windows. A window never crosses the page boundary."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("need size > 0 and 0 <= overlap < size")
    text, n = page.text, len(page.text)
    chunks: list[Chunk] = []
    start = 0
    while start < n:
        end = min(start + size, n)
        if page.text[start:end].strip():
            chunks.append(_make_chunk(page, start, end, "fixed", {"size": size, "overlap": overlap}))
        if end == n:
            break
        start += size - overlap
    return chunks


def _split_long_paragraph(page: DocumentPage, p_start: int, p_end: int, max_size: int
                          ) -> list[tuple[int, int]]:
    """Cut an oversized paragraph at sentence ends (contiguous spans); hard-cut only
    when a single sentence is itself longer than ``max_size``."""
    body = page.text[p_start:p_end]
    cuts = sorted({0, len(body), *(m.end() for m in _SENTENCE_END_RE.finditer(body))})
    sentences = [(p_start + a, p_start + b) for a, b in zip(cuts, cuts[1:]) if b > a]
    spans: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = None
    for s, e in sentences:
        if e - s > max_size:
            if cur:
                spans.append(cur)
                cur = None
            while e - s > max_size:
                spans.append((s, s + max_size))
                s += max_size
        if cur is None:
            cur = (s, e)
        elif e - cur[0] <= max_size:
            cur = (cur[0], e)
        else:
            spans.append(cur)
            cur = (s, e)
    if cur:
        spans.append(cur)
    return spans


def _units(page: DocumentPage, max_size: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"[^\n]+", page.text):
        if m.end() - m.start() <= max_size:
            spans.append((m.start(), m.end()))
        else:
            spans.extend(_split_long_paragraph(page, m.start(), m.end(), max_size))
    return spans


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Greedily group consecutive paragraphs up to ``max_size`` characters."""
    units = _units(page, max_size)
    chunks: list[Chunk] = []
    group_start = group_end = None
    for u_start, u_end in units:
        if group_start is None:
            group_start, group_end = u_start, u_end
        elif u_end - group_start <= max_size:
            group_end = u_end
        else:
            chunks.append(_make_chunk(page, group_start, group_end, "paragraph", {"max_size": max_size}))
            group_start, group_end = u_start, u_end
    if group_start is not None:
        chunks.append(_make_chunk(page, group_start, group_end, "paragraph", {"max_size": max_size}))
    return [c for c in chunks if c.text]
