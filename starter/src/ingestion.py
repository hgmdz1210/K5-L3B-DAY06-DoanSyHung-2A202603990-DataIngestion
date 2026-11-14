"""Read and normalize the Project Gutenberg HTML edition of *Pride and Prejudice*.

The HTML carries the printed page numbers as ``<span class="pagenum">{n}</span>``
markers (frequently in the middle of a sentence) and the chapter headings as
``<h2>`` elements.  We turn that into ``DocumentPage`` units that each belong to
exactly one printed page *and* one chapter, so every chunk can be traced back to
``(document_id, page, chapter)``.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from .models import DocumentPage

DOCUMENT_ID = "pride-and-prejudice-pg1342"
TITLE = "Pride and Prejudice (Jane Austen) - Project Gutenberg eBook #1342, illustrated HTML edition"

_PAGE_MARK = "\x00PAGE:{}\x00"
_DROP_CAP_END = "\x01"
_PAGE_RE = re.compile(r"\x00PAGE:([^\x00]+)\x00")
# "\s*" because the source has headings such as "CHAPTERXXVII." with no space.
_CHAPTER_RE = re.compile(r"chapter\s*([ivxlc]+)\b", re.IGNORECASE)
_PAGENUM_TEXT_RE = re.compile(r"\{([^}]+)\}")

# Typographic characters that differ between the source and what people type in
# quotes; used only for *matching* (see ``match_form``), never to alter stored text.
_MATCH_TRANSLATION = str.maketrans(
    {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "—": "-", "–": "-", " ": " ",
    }
)


def roman_to_int(value: str) -> int:
    numerals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    total = 0
    prev = 0
    for ch in reversed(value.lower()):
        n = numerals[ch]
        total += n if n >= prev else -n
        prev = max(prev, n)
    return total


def normalize_text(text: str) -> str:
    """Normalize Unicode (NFC) and whitespace; paragraph breaks (blank line) are kept."""
    text = unicodedata.normalize("NFC", text).replace(" ", " ")
    paragraphs = [re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\s*\n\s*", " ", p)).strip()
                  for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)


def match_form(text: str) -> str:
    """Whitespace-insensitive, punctuation-variant-insensitive form for evidence matching."""
    text = unicodedata.normalize("NFC", text).translate(_MATCH_TRANSLATION)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _inline_text(node: Tag) -> str:
    """Flatten a block element, emitting page markers and dropping figures/captions."""
    parts: list[str] = []

    def walk(el: Any) -> None:
        if isinstance(el, NavigableString):
            parts.append(str(el))
            return
        if not isinstance(el, Tag):
            return
        classes = el.get("class") or []
        if el.name == "span" and "pagenum" in classes:
            m = _PAGENUM_TEXT_RE.search(el.get_text())
            if m:
                parts.append(_PAGE_MARK.format(m.group(1).strip()))
            return
        if el.name == "img" and el.find_parent("span", class_="letra") is not None:
            # Illuminated initial drawn as an image: its letter lives only in `alt`.
            parts.append(_drop_cap_letters(el) + _DROP_CAP_END)
            return
        if el.name in {"img", "script", "style"} or "caption" in classes:
            return
        if el.name == "br":
            parts.append(" ")
            return
        for child in el.children:
            walk(child)

    walk(node)
    return "".join(parts)


# Drop-cap images whose `alt` is empty in the source. Verified by looking at the image file.
DROP_CAP_OVERRIDES = {"i_282_b.png": "IF "}   # Chapter XXXVI: picture shows the letters 'I' and 'F'


def _drop_cap_letters(img: Tag) -> str:
    alt = (img.get("alt") or "").strip()
    if alt:
        return alt
    name = (img.get("src") or "").rsplit("/", 1)[-1]
    if name in DROP_CAP_OVERRIDES:
        return DROP_CAP_OVERRIDES[name]
    raise ValueError(f"drop-cap image {name!r} has no alt text and no override")


def _recase_token(token: str) -> str:
    for i, ch in enumerate(token):
        if ch.isalpha():
            return token[:i + 1] + token[i + 1:].lower()
    return token


def _fix_drop_cap(raw_paragraph: str, tag: Tag) -> str:
    """Chapters open with an illuminated initial followed by small caps
    ('MR. BENNET was among', 'IT is a truth'). Re-case the leading run of all-caps words
    ('Mr. Bennet was among', 'It is a truth'); stop at the first word with a lower-case letter.
    """
    if tag.find("span", class_="letra") is None:
        return raw_paragraph
    # The initial is a whole word when the text continues in lower case ('“I' + 'hope');
    # otherwise it is the first letter of the next word ('M' + 'R. BENNET').
    raw_paragraph = re.sub(_DROP_CAP_END + r"(?=[a-z])", " ", raw_paragraph).replace(_DROP_CAP_END, "")
    pieces = re.split(r"(\s+)", raw_paragraph)
    out: list[str] = []
    recasing = True
    words_done = 0
    for piece in pieces:
        if recasing and piece and not piece.isspace():
            letters = re.sub(r"[^A-Za-z]", "", piece)
            if "\x00" in piece or not letters or not letters.isupper():
                recasing = False
            elif words_done > 0 and letters.lower() in _COMMON_WORDS:
                piece = piece.lower()          # '“I HAVE been' -> '“I have been'
            else:
                piece = _recase_token(piece)   # names keep a capital: 'MR. BENNET' -> 'Mr. Bennet'
            words_done += 1
        out.append(piece)
    return "".join(out)


# Ordinary words that can follow the initial inside the small-caps run (seen in this source).
_COMMON_WORDS = {"have", "few", "a", "an", "the", "is", "was", "of", "to", "in", "and"}


def load_html(path: Path, document_id: str = DOCUMENT_ID, source: str | None = None
              ) -> tuple[list[DocumentPage], dict[str, Any]]:
    """Return narrative ``DocumentPage`` units (one per page x chapter) and a parse log.

    Scope: from the heading of Chapter I (printed page 1) through the last narrative
    page. Front matter (title, preface, illustration list, roman-numbered pages) and
    the Gutenberg header/footer are excluded and counted in the log.
    """
    source = source or path.name
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

    footer = soup.find(id="pg-footer")
    if footer is not None:
        footer.decompose()
    for fig in soup.find_all("div", class_="figcenter"):
        fig.decompose()

    current_page: int | None = None
    current_chapter: int | None = None
    ended = False
    # (page, chapter) -> list of paragraph strings, in reading order
    segments: dict[tuple[int, int], list[str]] = {}
    order: list[tuple[int, int]] = []
    log: dict[str, Any] = {"skipped_roman_pages": [], "events": [], "the_end_seen": False}

    def add(page: int, chapter: int, text: str) -> None:
        text = text.strip()
        if not text:
            return
        # A page marker sometimes sits just before a closing quote (`...week.{3}"`), which would
        # leave a lone '"' as its own page unit. Glue it back to the sentence it closes.
        if not re.search(r"\w", text) and order and order[-1][1] == chapter:
            segments[order[-1]][-1] += text
            log.setdefault("glued_orphan_punctuation", []).append(f"p{page}:{text}")
            return
        key = (page, chapter)
        if key not in segments:
            segments[key] = []
            order.append(key)
        segments[key].append(text)

    body = soup.body
    for block in body.find_all(["h2", "p"]):
        if block.find_parent("header", id="pg-header"):
            continue
        # skip a <p> nested inside another <p>/<h2> we already walk (not expected, be safe)
        if block.name == "p" and block.find_parent(["p", "h2"]):
            continue

        if block.name == "h2":
            raw = _inline_text(block)
            for m in _PAGE_RE.finditer(raw):
                if m.group(1).isdigit():
                    current_page = int(m.group(1))
            m = _CHAPTER_RE.search(_PAGE_RE.sub("", raw))
            if m:
                current_chapter = roman_to_int(m.group(1))
                log["events"].append(f"chapter {current_chapter} starts on page {current_page}")
            continue

        raw = _fix_drop_cap(_inline_text(block), block)
        if ended:
            continue
        # walk text pieces and page markers in order
        pos = 0
        pieces: list[tuple[str, str]] = []
        for m in _PAGE_RE.finditer(raw):
            pieces.append(("text", raw[pos:m.start()]))
            pieces.append(("page", m.group(1)))
            pos = m.end()
        pieces.append(("text", raw[pos:]))

        for kind, value in pieces:
            if kind == "page":
                if value.isdigit():
                    current_page = int(value)
                else:
                    current_page = None
                    log["skipped_roman_pages"].append(value)
                continue
            if current_chapter is None or current_page is None:
                continue
            clean = re.sub(r"\s+", " ", value)
            # The printer's imprint after the last paragraph is not narrative text.
            if clean.strip().upper().startswith("CHISWICK PRESS"):
                ended = True
                log["the_end_seen"] = True
                continue
            add(current_page, current_chapter, clean)

    pages: list[DocumentPage] = []
    for page, chapter in order:
        text = normalize_text("\n\n".join(segments[(page, chapter)]))
        if not text:
            continue
        pages.append(DocumentPage(
            document_id=document_id,
            source=source,
            page=page,
            text=text,
            metadata={"chapter": chapter, "language": "en"},
        ))
    return pages, log


def corpus_stats(pages: list[DocumentPage], short_chars: int = 300) -> dict[str, Any]:
    """Page-level statistics used by the manifest and by run.py validation."""
    by_page: dict[int, dict[str, Any]] = {}
    for p in pages:
        info = by_page.setdefault(p.page, {"page": p.page, "chars": 0, "chapters": []})
        info["chars"] += len(p.text)
        info["chapters"].append(p.metadata["chapter"])
    ordered = [by_page[k] for k in sorted(by_page)]
    return {
        "content_pages": len(ordered),
        "page_min": ordered[0]["page"] if ordered else None,
        "page_max": ordered[-1]["page"] if ordered else None,
        "page_units": len(pages),
        "total_chars": sum(p["chars"] for p in ordered),
        "short_pages(<%d chars)" % short_chars: [p["page"] for p in ordered if p["chars"] < short_chars],
        "pages": ordered,
    }


def read_gutenberg_header(path: Path) -> dict[str, str]:
    """Version facts printed in the Gutenberg header (nothing is guessed)."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    header = soup.find(id="pg-header")
    text = re.sub(r"\s+", " ", header.get_text(" ")) if header else ""
    info: dict[str, str] = {}
    for key, pattern in {
        "release_date": r"Release date\s*:\s*(.+?)\s*(?:\[|Most recently updated|Language\s*:)",
        "most_recently_updated": r"Most recently updated\s*:\s*(.+?)\s*(?:Language\s*:|Credits\s*:|$)",
        "language": r"Language\s*:\s*(\w+)",
        "ebook_number": r"eBook\s*#\s*(\d+)",
    }.items():
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            info[key] = m.group(1).strip()
    return info


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
