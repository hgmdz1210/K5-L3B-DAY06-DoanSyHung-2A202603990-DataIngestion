"""Automatic retrieval metrics (Hit@1, Evidence Hit@3), benchmark validation and summaries.

Only *retrieval* is scored automatically.  Chunk coherence, metadata correctness and
grounding quality are manual labels and are never inferred from string matching here.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .ingestion import match_form
from .models import DocumentPage

REQUIRED_FIELDS = ["id", "split", "question", "expected_answer", "gold_source_id", "gold_page",
                   "evidence_quote"]
ALLOWED_FILTER_KEYS = {"chapter"}


def _evidences(question: dict[str, Any]) -> list[dict[str, Any]]:
    """Primary evidence plus every documented alternative (any one of them is accepted)."""
    out = [{"gold_page": question["gold_page"], "evidence_quote": question["evidence_quote"]}]
    out.extend(question.get("alt_evidence") or [])
    return out


def validate_benchmark(questions: list[dict[str, Any]], pages: list[DocumentPage]) -> list[str]:
    """Return a list of problems (empty = OK). Checks the structural rules from BENCHMARK.md
    and that every evidence quote really occurs on its gold page."""
    problems: list[str] = []
    by_page: dict[int, str] = {}
    for p in pages:
        by_page[p.page] = by_page.get(p.page, "") + " " + match_form(p.text)

    ids = [q.get("id") for q in questions]
    if len(set(ids)) != len(ids):
        problems.append("duplicate question ids")
    if len(questions) < 20:
        problems.append(f"only {len(questions)} questions (need >= 20)")
    dev = [q for q in questions if q.get("split") == "dev"]
    test = [q for q in questions if q.get("split") == "test"]
    if len(dev) < 15 or len(test) < 5:
        problems.append(f"split is {len(dev)} dev / {len(test)} test (need >= 15 / >= 5)")
    if any(q.get("split") not in {"dev", "test"} for q in questions):
        problems.append("split must be 'dev' or 'test'")
    filtered = [q for q in questions if q.get("filter")]
    if len(filtered) < 3 or not any(q["split"] == "test" for q in filtered):
        problems.append("need >= 3 filter questions, at least one in test")

    for q in questions:
        qid = q.get("id", "?")
        for f in REQUIRED_FIELDS:
            if q.get(f) in (None, ""):
                problems.append(f"{qid}: missing {f}")
        if q.get("filter"):
            bad = set(q["filter"]) - ALLOWED_FILTER_KEYS
            if bad:
                problems.append(f"{qid}: unsupported filter keys {sorted(bad)}")
            if q.get("gold_chapter") not in (None, q["filter"].get("chapter")):
                problems.append(f"{qid}: filter chapter differs from gold chapter")
        for ev in _evidences(q):
            page_text = by_page.get(ev["gold_page"])
            if page_text is None:
                problems.append(f"{qid}: gold page {ev['gold_page']} not in corpus")
            elif match_form(ev["evidence_quote"]) not in page_text:
                problems.append(f"{qid}: evidence quote not found on page {ev['gold_page']}")
    return problems


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """A hit = right source, right page and the chunk text contains the *whole* evidence
    quote (after whitespace/quote normalization), for the primary or an alternative evidence."""
    evs = _evidences(question)
    quotes = [(ev["gold_page"], match_form(ev["evidence_quote"])) for ev in evs]
    details = []
    for rank, h in enumerate(hits, start=1):
        text = match_form(h["text"])
        same_source = h["document_id"] == question["gold_source_id"]
        page_hit = same_source and any(h["page"] == pg for pg, _ in quotes)
        evidence_hit = same_source and any(h["page"] == pg and q in text for pg, q in quotes)
        details.append({
            "rank": rank, "chunk_id": h["chunk_id"], "page": h["page"], "chapter": h["chapter"],
            "score": h["score"], "page_hit": page_hit, "evidence_hit": evidence_hit,
            # right page but evidence incomplete in this chunk -> likely split across chunks
            "evidence_split_or_partial": page_hit and not evidence_hit,
        })
    first = next((d["rank"] for d in details if d["evidence_hit"]), None)
    flt = question.get("filter")
    return {
        "hit1": bool(details and details[0]["evidence_hit"]),
        "hit3": first is not None and first <= 3,
        "first_hit_rank": first,
        "filter": flt,
        "filter_compliant": (all(h.get(k) == v for h in hits for k, v in flt.items()) if flt else None),
        "hit_details": details,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate by strategy and split. Counts are returned as n and N (never only %)."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in traces:
        buckets[(t["strategy"], t["split"])].append(t)
    result: dict[str, Any] = {}
    for (strategy, split), items in sorted(buckets.items()):
        n = len(items)
        # Compliance is measured on every question that *has* a filter, whether or not the
        # strategy applied it: for A/B it shows how often unfiltered top-3 stays in scope.
        flt_items = [t for t in items if t["filter"]]
        result[f"{strategy}/{split}"] = {
            "strategy": strategy, "split": split, "N": n,
            "hit1_n": sum(t["hit1"] for t in items),
            "hit3_n": sum(t["hit3"] for t in items),
            "filter_questions_N": len(flt_items),
            "filter_applied_N": sum(1 for t in items if t["filter_applied"]),
            "filter_compliant_n": sum(1 for t in flt_items if t["filter_compliant"]),
            "failed_ids_hit3": [t["question_id"] for t in items if not t["hit3"]],
        }
    return result
