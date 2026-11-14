"""Check the benchmark BEFORE any retrieval run: structure, split, filters, and that every
evidence quote really occurs on its gold page of the parsed corpus.

Run from ``starter/``:  python scripts/validate_benchmark.py
"""
import json
import sys
from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STARTER))

from src.evaluation import validate_benchmark  # noqa: E402
from src.ingestion import load_html  # noqa: E402

ROOT = STARTER.parent
pages, _ = load_html(ROOT / "data" / "pg1342-images.html")
questions = json.loads((ROOT / "benchmark" / "questions.json").read_text(encoding="utf-8"))["questions"]
problems = validate_benchmark(questions, pages)
splits = {s: sum(q["split"] == s for q in questions) for s in ("dev", "test")}
filters = [(q["id"], q["split"]) for q in questions if q.get("filter")]
print(f"{len(questions)} questions, split {splits}, filter questions {filters}")
if problems:
    print("PROBLEMS:\n  " + "\n  ".join(problems))
    sys.exit(1)
print("Benchmark OK: all evidence quotes verified on their gold pages.")
