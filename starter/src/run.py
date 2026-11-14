"""Day 06 pipeline: ingest -> chunk (A/B) -> embed -> store -> retrieve (A/B/C) -> evaluate.

Usage (from ``starter/``)::

    python -m src.run                 # ingest (idempotent) + run the DEV questions
    python -m src.run --split test    # run the TEST questions, only after the strategy is frozen
    python -m src.run --skip-ingest   # reuse vectors already in PostgreSQL

Strategies
    A  fixed 500-char windows, overlap 50, own index, no filter
    B  paragraph groups <= 1200 chars,           own index, no filter
    C  same chunks and index as B, adds a `chapter` filter ONLY for questions that carry one
       (B vs C differ in exactly one factor: the metadata filter, so C needs no second index).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import EmbeddingError, MyEmbedder
from .evaluation import evaluate_query, summarize, validate_benchmark
from .ingestion import (DOCUMENT_ID, TITLE, corpus_stats, load_html, read_gutenberg_header, sha256_file)
from .models import Chunk, DocumentPage
from .store import PgVectorStore

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
CORPUS_PATH = ROOT / "data" / "pg1342-images.html"
MANIFEST_PATH = ROOT / "data" / "manifest.json"
BENCHMARK_PATH = ROOT / "benchmark" / "questions.json"
RESULTS = STARTER / "results"
LABELS = RESULTS / "manual_labels"
EXPERIMENT_LOG = ROOT / "artifacts" / "experiment_log.csv"

CHUNKERS = {
    "A": {"label": "A", "name": "fixed", "size": 500, "overlap": 50, "use_filter": False},
    "B": {"label": "B", "name": "paragraph", "max_size": 1200, "use_filter": False},
    "C": {"label": "B", "name": "paragraph", "max_size": 1200, "use_filter": True},  # reuses B's index
}
INGESTED = ("A", "B")
TOP_K = 3
# Date the corpus file was obtained. Evidence: the file was created on this disk on
# 2026-11-14 10:13 +07:00 (filesystem birth time); its Last-Modified time (2026-10-26) is the
# Gutenberg server's file date, not the access date. Change it if you downloaded it earlier.
ACCESSED_AT = "2026-11-14"
LABEL_COLUMNS = {"score_0_1_2", "reason", "metadata_complete_and_correct_Y_N", "error_notes",
                 "grounding_0_1_2"}


def write_sheet(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a label sheet, but never overwrite one that already holds labels."""
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as fh:
            old = list(csv.DictReader(fh))
        if any((r.get(c) or "").strip() for r in old for c in LABEL_COLUMNS):
            print(f"kept {path.relative_to(STARTER)} (already labelled; not overwritten)")
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def lib_versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for pkg in ("openai", "psycopg", "beautifulsoup4", "python-dotenv"):
        try:
            out[pkg] = importlib_metadata.version(pkg)
        except importlib_metadata.PackageNotFoundError:
            out[pkg] = "n/a"
    return out


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_chunks(pages: list[DocumentPage], key: str) -> list[Chunk]:
    cfg = CHUNKERS[key]
    chunks: list[Chunk] = []
    for page in pages:
        if cfg["name"] == "fixed":
            chunks.extend(fixed_size(page, cfg["size"], cfg["overlap"]))
        else:
            chunks.extend(by_paragraph(page, cfg["max_size"]))
    ids = [c.chunk_id for c in chunks]
    if len(set(ids)) != len(ids):
        raise RuntimeError(f"strategy {key}: duplicate chunk ids")
    return chunks


def length_stats(chunks: list[Chunk]) -> dict[str, Any]:
    lengths = sorted(len(c.text) for c in chunks)
    return {
        "chunk_count": len(lengths), "total_chars": sum(lengths),
        "min": lengths[0], "mean": round(statistics.mean(lengths), 1), "median": statistics.median(lengths),
        "p95": lengths[int(0.95 * (len(lengths) - 1))], "max": lengths[-1],
    }


def write_manifest(pages: list[DocumentPage], stats: dict[str, Any], log: dict[str, Any]) -> None:
    header = read_gutenberg_header(CORPUS_PATH)
    manifest = {
        "source_id": DOCUMENT_ID,
        "title": TITLE,
        "source_path_or_url": "data/pg1342-images.html (from https://www.gutenberg.org/ebooks/1342)",
        "license_or_permission": (
            "Project Gutenberg eBook #1342; the Gutenberg header states it may be used with almost no "
            "restrictions in the United States and most other parts of the world. Keep the Project "
            "Gutenberg License if you redistribute the file; check local copyright law elsewhere."),
        "accessed_at": ACCESSED_AT,
        "accessed_at_note": ("Date the HTML file was saved into this project (filesystem creation time "
                             "2026-11-14 10:13 +07:00). The file's modification time 2026-10-26 is the "
                             "Gutenberg server date of this version, kept as snapshot information."),
        "snapshot": {**header, "sha256": sha256_file(CORPUS_PATH), "file_bytes": CORPUS_PATH.stat().st_size},
        "page_counting_rule": (
            "A content page is a printed (Arabic-numbered) page that has narrative text of Chapters I-LXI "
            "after removing: Gutenberg header/footer, title/preface/list of illustrations (roman-numbered "
            "pages), figure captions, illustration images and the printer's imprint. A printed page that "
            "contains two chapters is split into two page units but counted once."),
        "chapter_rule": "chapter = number in the 'Chapter N' heading (parsed from Roman numerals, e.g. 'CHAPTERXXVII.').",
        "physical_pages": "n/a (HTML edition); printed page numbers {1}..{476} are used as 'page'.",
        "content_pages": stats["content_pages"],
        "page_range": [stats["page_min"], stats["page_max"]],
        "page_units": stats["page_units"],
        "total_chars_normalized": stats["total_chars"],
        "short_pages_under_300_chars": stats["short_pages(<300 chars)"],
        "pages_without_text_in_range": [n for n in range(stats["page_min"], stats["page_max"] + 1)
                                        if n not in {p["page"] for p in stats["pages"]}],
        "front_matter_roman_pages_skipped": log["skipped_roman_pages"],
        "glued_orphan_punctuation": log.get("glued_orphan_punctuation", []),
        "known_limitations": [
            "Each chapter opens with an illuminated initial (60 of 61 are images whose letter is only in the "
            "alt text) followed by small caps. The parser restores the letter from alt text and re-cases the "
            "small-caps run ('M' + 'R. BENNET was' -> 'Mr. Bennet was'). Chapter XXXVI's image has an empty alt; "
            "its letters 'IF' were read from images/i_282_b.png and hard-coded (DROP_CAP_OVERRIDES).",
            "A lone closing quote that the page marker separated from its sentence is glued back to the "
            "previous page (listed in the parse log as glued_orphan_punctuation).",
            "Chapter headings and illustration captions are not part of the chunk text.",
            "Printed page markers fall mid-sentence, so chunks are bounded by page and a sentence that "
            "crosses a page break is split between two chunks.",
        ],
        "pages": stats["pages"],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def ingest(store: PgVectorStore, embedder: MyEmbedder, key: str, chunks: list[Chunk]) -> dict[str, Any]:
    started = time.perf_counter()
    tokens_before, seconds_before = embedder.total_tokens, embedder.api_seconds
    existing = store.existing_hashes(key)
    rows_before = len(existing)
    hashes = [hashlib.sha256(f"{embedder.model_name}\n{c.text}".encode()).hexdigest() for c in chunks]
    todo = [i for i, (c, h) in enumerate(zip(chunks, hashes)) if existing.get(c.chunk_id) != h]
    vectors = embedder.embed_documents([chunks[i].text for i in todo]) if todo else []
    if todo:
        store.upsert(key, [chunks[i] for i in todo], vectors, [hashes[i] for i in todo])
    deleted = store.delete_obsolete(key, DOCUMENT_ID, {c.chunk_id for c in chunks})
    tokens = embedder.total_tokens - tokens_before
    return {
        "strategy": key, "at": now(), "model": embedder.model_name, "dimensions": embedder.dimensions,
        "chunk_count": len(chunks), "rows_before": rows_before, "embedded_this_run": len(todo),
        "skipped_unchanged": len(chunks) - len(todo), "deleted_obsolete": deleted,
        "rows_after": store.count(key), "embedding_tokens": tokens,
        "embedding_cost_usd_estimate": round(tokens / 1_000_000 * embedder.price_per_1m, 6),
        "embedding_api_seconds": round(embedder.api_seconds - seconds_before, 2),
        "wall_seconds": round(time.perf_counter() - started, 2), "length_stats": length_stats(chunks),
    }


def coherence_sheet(pages: list[DocumentPage], chunk_sets: dict[str, list[Chunk]]) -> None:
    """Fix 10 positions BEFORE seeing any retrieval score (deterministic, spread over the book)
    and write an empty manual-label sheet for the chunk that covers each position."""
    longest: dict[int, DocumentPage] = {}
    for p in pages:
        if p.page not in longest or len(p.text) > len(longest[p.page].text):
            longest[p.page] = p
    ordered = [longest[k] for k in sorted(longest)]
    picks = [ordered[i * (len(ordered) - 1) // 9] for i in range(10)]
    rows = []
    for n, p in enumerate(picks, start=1):
        offset = len(p.text) // 2
        for key in INGESTED:
            cover = [c for c in chunk_sets[key] if c.page == p.page
                     and c.metadata["chapter"] == p.metadata["chapter"]
                     and c.metadata["char_start"] <= offset < c.metadata["char_end"]]
            c = cover[0]
            rows.append({"position_id": f"pos{n:02d}", "page": p.page, "chapter": p.metadata["chapter"],
                         "offset": offset, "strategy": key, "chunk_id": c.chunk_id,
                         "chunk_text": c.text, "score_0_1_2": "", "reason": ""})
    write_sheet(LABELS / "coherence_sheet.csv", rows)


def label_sheets(traces: list[dict[str, Any]], questions: list[dict[str, Any]]) -> None:
    """Empty manual-label sheets for the first 5 TEST questions (metadata audit + grounding)."""
    test_ids = [q["id"] for q in questions if q["split"] == "test"][:5]
    meta_rows, ground_rows = [], []
    for t in traces:
        if t["split"] != "test" or t["question_id"] not in test_ids:
            continue
        for h in t["hits"]:
            meta_rows.append({"strategy": t["strategy"], "question_id": t["question_id"], "rank": h["rank"],
                              "chunk_id": h["chunk_id"], "source_shown": h["source"], "page_shown": h["page"],
                              "chapter_shown": h["chapter"], "filter_in_question": json.dumps(t["filter"]),
                              "metadata_complete_and_correct_Y_N": "", "error_notes": ""})
        row = {"strategy": t["strategy"], "question_id": t["question_id"], "question": t["question"],
               "expected_answer": t["expected_answer"], "gold_page": t["gold_page"],
               "gold_evidence": t["evidence_quote"]}
        for rank in range(1, TOP_K + 1):
            h = next((x for x in t["hits"] if x["rank"] == rank), None)
            row[f"top{rank}_page"] = h["page"] if h else ""
            row[f"top{rank}_chapter"] = h["chapter"] if h else ""
            row[f"top{rank}_text"] = h["text"] if h else ""
        row.update({"grounding_0_1_2": "", "reason": ""})
        ground_rows.append(row)
    write_sheet(LABELS / "metadata_audit_sheet.csv", meta_rows)
    write_sheet(LABELS / "grounding_sheet.csv", ground_rows)


def run_queries(store: PgVectorStore, embedder: MyEmbedder, questions: list[dict[str, Any]], split: str
                ) -> list[dict[str, Any]]:
    selected = [q for q in questions if q["split"] == split]
    qvecs = {}
    q_seconds = {}
    for q in selected:
        t0 = time.perf_counter()
        qvecs[q["id"]] = embedder.embed_query(q["question"])
        q_seconds[q["id"]] = time.perf_counter() - t0
    traces = []
    for key, cfg in CHUNKERS.items():
        for q in selected:
            flt = q["filter"] if (cfg["use_filter"] and q.get("filter")) else None
            t0 = time.perf_counter()
            hits = store.search(cfg["label"], qvecs[q["id"]], TOP_K, flt)
            search_ms = (time.perf_counter() - t0) * 1000
            ev = evaluate_query(q, hits)
            traces.append({
                "run_at": now(), "strategy": key, "index": cfg["label"], "split": split,
                "question_id": q["id"], "type": q["type"], "question": q["question"],
                "expected_answer": q["expected_answer"], "evidence_quote": q["evidence_quote"],
                "gold_page": q["gold_page"], "gold_source_id": q["gold_source_id"],
                "filter": q.get("filter"), "filter_applied": flt, "search_ms": round(search_ms, 1),
                "query_embed_seconds": round(q_seconds[q["id"]], 3),
                "hits": [{**{k: h[k] for k in ("chunk_id", "document_id", "source", "page", "chapter",
                                                "char_start", "char_end", "score", "text")},
                          "rank": i} for i, h in enumerate(hits, start=1)],
                **ev,
            })
    return traces


def update_experiment_log(summary: dict[str, Any]) -> None:
    if not EXPERIMENT_LOG.exists():
        return
    with EXPERIMENT_LOG.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0].keys()) if rows else []
    for row in rows:
        for split in ("dev", "test"):
            s = summary.get(f"{row['strategy']}/{split}")
            if s:
                row[f"{split}_hit1"] = f"{s['hit1_n']}/{s['N']}"
                row[f"{split}_hit3"] = f"{s['hit3_n']}/{s['N']}"
    with EXPERIMENT_LOG.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def full_builds() -> dict[str, dict[str, Any]]:
    """Latest ingest run per index that embedded every chunk (= the real build time/cost)."""
    out: dict[str, dict[str, Any]] = {}
    path = RESULTS / "ingest_runs.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["embedded_this_run"] == r["chunk_count"] and r["chunk_count"] > 0:
                out[r["strategy"]] = r
    return out


def markdown_table(summary: dict[str, Any], chunk_stats: dict[str, Any]) -> str:
    builds = full_builds()
    lines = ["| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Filter compliance (n/N) "
             "| Chunk count | Build time (s) | Build tokens | Build cost (USD, est.) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in summary.values():
        label = CHUNKERS[s["strategy"]]["label"]
        fc = f"{s['filter_compliant_n']}/{s['filter_questions_N']}" if s["filter_questions_N"] else "N/A"
        if s["strategy"] == "C":
            fc += " (filter applied)"
        cc = chunk_stats.get(label, {}).get("chunk_count", "?")
        b = builds.get(label)
        if s["strategy"] == "C":
            build = "0 (reuses B index)", "0", "0"
        elif b:
            build = (f"{b['wall_seconds']}", f"{b['embedding_tokens']:,}", f"{b['embedding_cost_usd_estimate']}")
        else:
            build = ("?", "?", "?")
        lines.append(f"| {s['strategy']} | {s['split']} | {s['hit1_n']}/{s['N']} | {s['hit3_n']}/{s['N']} "
                     f"| {fc} | {cc} | {build[0]} | {build[1]} | {build[2]} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 06 data-ingestion benchmark")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev",
                        help="which questions to run; use 'test' only after the strategy is frozen")
    parser.add_argument("--skip-ingest", action="store_true", help="reuse vectors already stored")
    parser.add_argument("--manifest-only", action="store_true",
                        help="parse the corpus, rewrite data/manifest.json and stop (no API, no DB)")
    args = parser.parse_args()

    load_dotenv(STARTER / ".env")
    RESULTS.mkdir(exist_ok=True)

    pages, parse_log = load_html(CORPUS_PATH)
    stats = corpus_stats(pages)
    if stats["content_pages"] < 30:
        print(f"ERROR: only {stats['content_pages']} content pages (need >= 30)")
        return 1
    write_manifest(pages, stats, parse_log)
    print(f"corpus: {stats['content_pages']} content pages, {stats['total_chars']:,} chars, "
          f"{stats['page_units']} page units; manifest -> {MANIFEST_PATH.relative_to(ROOT)}")
    if args.manifest_only:
        return 0

    questions = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))["questions"]
    problems = validate_benchmark(questions, pages)
    if problems:
        print("BENCHMARK INVALID:\n  " + "\n  ".join(problems))
        return 1
    print(f"benchmark: {len(questions)} questions valid "
          f"({sum(q['split'] == 'dev' for q in questions)} dev / {sum(q['split'] == 'test' for q in questions)} test)")

    try:
        embedder = MyEmbedder()
        database_url = os.environ["DATABASE_URL"]
        store = PgVectorStore(database_url, embedder.dimensions)
        store.create_schema()
    except (EmbeddingError, KeyError) as exc:
        print(f"ERROR: {exc}")
        return 2
    except Exception as exc:  # database not reachable etc.
        print(f"ERROR: database/setup failure: {type(exc).__name__}: {exc}")
        return 2

    chunk_sets = {k: build_chunks(pages, k) for k in INGESTED}
    chunk_stats = {k: length_stats(v) for k, v in chunk_sets.items()}
    coherence_sheet(pages, chunk_sets)

    if not args.skip_ingest:
        runs = []
        for key in INGESTED:
            r = ingest(store, embedder, key, chunk_sets[key])
            runs.append(r)
            print(f"ingest {key}: {r['chunk_count']} chunks, embedded {r['embedded_this_run']}, "
                  f"skipped {r['skipped_unchanged']}, deleted {r['deleted_obsolete']}, rows {r['rows_before']}->{r['rows_after']}, "
                  f"{r['embedding_tokens']:,} tokens, ~${r['embedding_cost_usd_estimate']}, {r['wall_seconds']}s")
        with (RESULTS / "ingest_runs.jsonl").open("a", encoding="utf-8") as fh:
            for r in runs:
                fh.write(json.dumps({**r, "libs": lib_versions()}, ensure_ascii=False) + "\n")
    (RESULTS / "chunk_stats.json").write_text(json.dumps(chunk_stats, indent=2), encoding="utf-8")

    splits = ["dev", "test"] if args.split == "all" else [args.split]
    all_traces: list[dict[str, Any]] = []
    for split in splits:
        traces = run_queries(store, embedder, questions, split)
        all_traces.extend(traces)
        with (RESULTS / f"traces_{split}.jsonl").open("w", encoding="utf-8") as fh:
            for t in traces:
                fh.write(json.dumps(t, ensure_ascii=False) + "\n")
        summary = summarize(traces)
        (RESULTS / f"metrics_{split}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        table = markdown_table(summary, chunk_stats)
        (RESULTS / f"metrics_{split}.md").write_text(table + "\n", encoding="utf-8")
        print(f"\n== {split} ==\n{table}")
        for s in summary.values():
            print(f"   {s['strategy']}/{split} misses@3: {s['failed_ids_hit3']}")
        update_experiment_log(summary)
    if "test" in splits:
        label_sheets(all_traces, questions)
    print(f"\nquery-embedding tokens this process: {embedder.total_tokens:,} "
          f"(~${embedder.cost_usd:.6f} at {embedder.price_per_1m}/1M tokens, estimate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
