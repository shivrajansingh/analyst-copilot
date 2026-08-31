# Data

| File | Role |
|------|------|
| `practice-questions.jsonl` | Original 136 labeled questions (answer key) |
| `questions-by-doc.json` | Grouped eval input: `[{doc_path, questions}]` |
| `planner-cases.jsonl` | Labelled messages for the planner's classification, scored by `scripts/examples/plan.py --suite` |
| `questions-by-doc-results.json` | Answers from `scripts/examples/run_all_questions.py` (gitignored) |
| `eval-results.json` | Flat model outputs from `scripts/eval/run_practice.py` (gitignored) |

Regenerate the grouped file:

```bash
PYTHONPATH=src python scripts/examples/build_questions_by_doc.py
```
