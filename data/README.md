# Data

| File | Role |
|------|------|
| `practice-questions.jsonl` | Original 136 labeled questions (answer key) |
| `questions-by-doc.json` | Grouped eval input: `[{doc_path, questions}]` |
| `eval-results.json` | Model outputs from `scripts/eval/run_practice.py` (gitignored) |

Regenerate the grouped file:

```bash
PYTHONPATH=src python scripts/examples/build_questions_by_doc.py
```
