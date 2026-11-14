"""Independent check of the metadata shown in the metadata audit sheet.

It does NOT reuse the pipeline parser: the raw HTML is flattened with plain regular
expressions, keeping the printed page markers ``{n}`` and the ``CHAPTER N`` headings. For each
audited chunk a probe taken from the middle of its text is located in that stream, and the page
and chapter in force at that point are compared with what the pipeline stored.

Run from ``starter/``:  python scripts/verify_metadata.py   (fills metadata_audit_sheet.csv)
"""
import csv
import html
import json
import re
import sys
from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STARTER))
from src.ingestion import match_form, roman_to_int  # noqa: E402  (text normalisation only)

ROOT = STARTER.parent
SHEET = STARTER / "results" / "manual_labels" / "metadata_audit_sheet.csv"

raw = (ROOT / "data" / "pg1342-images.html").read_text(encoding="utf-8")
raw = raw[raw.index("*** START OF"):raw.index("*** END OF")]
raw = re.sub(r'<span class="pagenum"><a id="page_[^"]*">\{([^}]*)\}</a></span>',
             lambda m: " \x02P%s\x02 " % m.group(1), raw)
raw = re.sub(r"<h2[^>]*>(.*?)</h2>",
             lambda m: (" \x02C%s\x02 " % roman_to_int(c.group(1)))
             if (c := re.search(r"CHAPTER\s*([IVXLC]+)\b", re.sub(r"<[^>]+>", "", m.group(1)), re.I)) else " ",
             raw, flags=re.S)
raw = re.sub(r'<div class="caption".*?</div>|<span class="caption">.*?</span>', " ", raw, flags=re.S)
text = html.unescape(re.sub(r"<[^>]+>", " ", raw))

# Build a normalised stream plus, for every character, the page and chapter in force.
stream, pages, chapters = [], [], []
page = chapter = None
for part in re.split(r"(\x02[PC][^\x02]*\x02)", text):
    if part.startswith("\x02P"):
        v = part[2:-1]
        page = int(v) if v.isdigit() else None
        continue
    if part.startswith("\x02C"):
        chapter = int(part[2:-1])
        continue
    norm = match_form(part)
    if norm:
        norm = " " + norm
        stream.append(norm)
        pages.extend([page] * len(norm))
        chapters.extend([chapter] * len(norm))
flat = "".join(stream)


def locate(chunk_text: str):
    t = match_form(chunk_text)
    # middle probe avoids the chapter-initial words, which the pipeline re-cases
    for length in (60, 100, 160, 240):
        start = max(0, len(t) // 2 - length // 2)
        probe = t[start:start + length]
        hits = [m.start() for m in re.finditer(re.escape(probe), flat)]
        if len(hits) == 1:
            i = hits[0]
            return pages[i], chapters[i], pages[i + len(probe) - 1]
    return None


traces = {}
for line in (STARTER / "results" / "traces_test.jsonl").read_text(encoding="utf-8").splitlines():
    t = json.loads(line)
    for h in t["hits"]:
        traces[h["chunk_id"]] = h

with SHEET.open(newline="", encoding="utf-8-sig") as fh:
    rows = list(csv.DictReader(fh))
fields = list(rows[0])
ok = 0
for r in rows:
    h = traces[r["chunk_id"]]
    found = locate(h["text"])
    problems = []
    if r["source_shown"] != "pg1342-images.html":
        problems.append(f"source {r['source_shown']!r} is not the corpus file")
    if found is None:
        problems.append("chunk text not located uniquely in raw HTML")
    else:
        p_start, ch, p_end = found
        if str(p_start) != r["page_shown"]:
            problems.append(f"raw HTML says page {p_start}, shown {r['page_shown']}")
        if str(ch) != r["chapter_shown"]:
            problems.append(f"raw HTML says chapter {ch}, shown {r['chapter_shown']}")
    r["metadata_complete_and_correct_Y_N"] = "N" if problems else "Y"
    r["error_notes"] = "; ".join(problems) if problems else "source, page and chapter match the raw HTML"
    ok += not problems

with SHEET.open("w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
print(f"metadata complete and correct: {ok}/{len(rows)}")
for r in rows:
    if r["metadata_complete_and_correct_Y_N"] == "N":
        print("  ", r["strategy"], r["question_id"], r["rank"], r["error_notes"])
