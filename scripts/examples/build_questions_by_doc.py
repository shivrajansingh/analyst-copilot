"""Write data/questions-by-doc.json from practice-questions.jsonl."""

from __future__ import annotations

from analyst_copilot.data import write_questions_by_doc


def main() -> None:
    path = write_questions_by_doc()
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
