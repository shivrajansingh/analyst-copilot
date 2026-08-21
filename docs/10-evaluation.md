# Evaluation

Two stages: a **runner** produces model answers, a **scorer** grades them against the practice key.

```text
questions-by-doc.json → run_practice.py / run_all_questions.py → results JSON → score.py → eval-scores.json
```

## Stage 1 — produce answers

`data/questions-by-doc.json` is an array of:

```json
{ "doc_path": "filings/3M_2018_10K.htm", "questions": ["...", "..."] }
```

Rebuild it from the JSONL:

```bash
PYTHONPATH=src python scripts/examples/build_questions_by_doc.py
```

Two runners, both safe to interrupt — results are written after **every** question.

```bash
# Grouped by filing, resumes by skipping questions that already have answers
python scripts/examples/run_all_questions.py
python scripts/examples/run_all_questions.py --limit 5     # limit counts UNANSWERED questions

# Flat slice across all docs, always re-runs the slice
PYTHONPATH=src python scripts/eval/run_practice.py --limit 10
PYTHONPATH=src python scripts/eval/run_practice.py --offset 10 --limit 20
PYTHONPATH=src python scripts/eval/run_practice.py            # all 136
```

`--limit` on `run_all_questions.py` counts *unanswered* questions. If the results file already has answers for everything in range, the run does no model calls and rewrites the same file — check the `Unanswered questions:` line it prints.

Both runners index a filing first if no current index exists. A parser change invalidates indices automatically (see [03-html-parsing.md](03-html-parsing.md#index-invalidation)), so the first run after one will re-embed.

### Output shape

```json
{
  "text": "1,577",
  "evidence": "Purchases of property, plant and equipment (PP&E) (1,577)",
  "found": true,
  "page": 59,
  "abstention_reason": null,
  "retrieved_pages": [59, 57, 61, 43, 58]
}
```

`abstention_reason` and `retrieved_pages` are diagnostics. Together they separate the two failure modes that need completely different fixes:

| Symptom | Meaning |
| ------- | ------- |
| gold page absent from `retrieved_pages` | retrieval problem — fusion, query expansion, chunking |
| gold page present, but abstained | prompt/verifier/truncation problem |

## Stage 2 — score against the key

```bash
PYTHONPATH=src python scripts/eval/score.py
PYTHONPATH=src python scripts/eval/score.py --results data/eval-results.json
PYTHONPATH=src python scripts/eval/score.py --judge              # grade prose answers with the chat model
PYTHONPATH=src python scripts/eval/score.py --page-tolerance 1   # how much is the residual page offset costing?
```

Applies the challenge rubric:

| Outcome | Score |
| ------- | ----- |
| Correct answer, correct location | +1 |
| "not found in this filing" | 0 |
| Correct answer, wrong location | 0 |
| Confidently wrong answer | −1 |

Accepts either runner's output layout, and writes per-question detail to `data/eval-scores.json`.

### How correctness is decided

**Bare figures** (gold answer ≤ 10 words containing a digit — e.g. `"$1577.00"`, `"24.26"`, `"1.9%"`) are checked arithmetically. Comparison is relative (default 2%) and scale-aware, so a model answering `8,738` in millions satisfies a gold answer of `$8.70` billion.

**Prose answers** (the `domain-relevant` questions, which argue a conclusion) cannot be checked arithmetically. They are reported as `unjudged` and scored 0 unless `--judge` is passed, which grades them with the chat model on substantive agreement. Always report the judged and unjudged counts together — an unjudged question is missing data, not a zero.

**Location** must match `evidence_page_num` exactly by default. `--page-tolerance 1` measures what the residual ±1 parser offset costs; the gap between the two runs is the value left in better page alignment.
