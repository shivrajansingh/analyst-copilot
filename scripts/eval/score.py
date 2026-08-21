#!/usr/bin/env python3
"""
Score model answers against the practice key using the challenge rubric.

    Correct answer, correct location   +1
    "not found in this filing"          0
    Correct answer, wrong location      0
    Confidently wrong answer           -1

Usage:
    PYTHONPATH=src python scripts/eval/score.py
    PYTHONPATH=src python scripts/eval/score.py --results data/eval-results.json
    PYTHONPATH=src python scripts/eval/score.py --judge      # LLM-judge prose answers
    PYTHONPATH=src python scripts/eval/score.py --page-tolerance 1

Reads either results layout:
    [{"doc_path", "questions": [{"question", "answer": {...}}]}]     (run_all_questions)
    [{"doc", "question", "answer": {...}}]                            (run_practice)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from analyst_copilot.config.settings import get_settings  # noqa: E402

# Gold answers are quoted to varying precision ("$8.70" for 8,738 million), so
# comparison is relative, and allows for unit rescaling between the two.
DEFAULT_REL_TOL = 0.02
SCALES = (1.0, 1e3, 1e-3, 1e6, 1e-6, 1e9, 1e-9)

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
# A gold answer this short that carries a digit is a bare figure, not an argument.
PROSE_WORD_THRESHOLD = 10


# --------------------------------------------------------------------------- #
# numeric comparison
# --------------------------------------------------------------------------- #
def numbers_in(text: str) -> List[float]:
    """Pull comparable magnitudes out of free text, ignoring sign."""
    values: List[float] = []
    for match in _NUMBER.finditer(text or ""):
        token = match.group(0).replace(",", "")
        try:
            values.append(abs(float(token)))
        except ValueError:
            continue
    return values


def _looks_like_year(value: float) -> bool:
    return value.is_integer() and 1900 <= value <= 2100


def headline_value(gold_values: List[float]) -> float:
    """
    The figure a gold answer is actually asserting.

    Naively taking the first number breaks on golds that lead with the fiscal
    year -- "Pepsico's restructuring costs in FY2022 amounted to $411 million"
    would be checked against 2022, which any answer about FY2022 satisfies, so a
    wrong figure would score as correct. Drop year-like values when the answer
    carries a real figure as well.
    """
    if len(gold_values) > 1:
        non_years = [v for v in gold_values if not _looks_like_year(v)]
        if non_years:
            return non_years[0]
    return gold_values[0]


def numeric_match(gold_text: str, model_text: str, rel_tol: float) -> Optional[bool]:
    """
    True/False when the gold answer's figure is decidable, None when gold has none.

    Scale factors let "8,738" (millions) satisfy a gold answer of "$8.70" billion.
    """
    gold_values = numbers_in(gold_text)
    if not gold_values:
        return None
    model_values = numbers_in(model_text)
    if not model_values:
        return False

    target = headline_value(gold_values)
    for scale in SCALES:
        scaled = target * scale
        if scaled == 0:
            continue
        for value in model_values:
            if abs(value - scaled) <= rel_tol * abs(scaled):
                return True
    if target == 0.0 and any(v == 0.0 for v in model_values):
        return True
    return False


def gold_is_bare_figure(record: Dict[str, Any]) -> bool:
    """Whether the gold answer can be checked arithmetically rather than read."""
    answer = str(record.get("answer") or "").strip()
    if not re.search(r"\d", answer):
        return False
    return len(answer.split()) <= PROSE_WORD_THRESHOLD


# --------------------------------------------------------------------------- #
# LLM judge for prose answers
# --------------------------------------------------------------------------- #
JUDGE_SYSTEM = """You grade a financial analyst assistant against a reference answer.

Decide whether the candidate answer conveys the same substantive conclusion and
the same key figures as the reference. Wording, ordering and extra supporting
detail do not matter. A different direction (up vs down, yes vs no) or a
materially different figure is incorrect.

Return JSON only: {"correct": boolean, "reason": string}"""


def judge_prose(client, question: str, gold: str, candidate: str) -> Tuple[Optional[bool], str]:
    prompt = (
        f"Question:\n{question}\n\n"
        f"Reference answer:\n{gold}\n\n"
        f"Candidate answer:\n{candidate}\n\n"
        "Return JSON only."
    )
    try:
        raw = client.complete(
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=2048,
        )
    except Exception as exc:  # judging must never abort a scoring run
        return None, f"judge_error:{exc}"

    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, "judge_unparseable"
    return bool(payload.get("correct")), str(payload.get("reason") or "")[:300]


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def load_gold() -> Dict[Tuple[str, str], Dict[str, Any]]:
    path = get_settings().data_dir / "practice-questions.jsonl"
    gold: Dict[Tuple[str, str], Dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                record = json.loads(line)
                gold[(record["doc_name"], record["question"])] = record
    return gold


def load_results(path: Path) -> List[Dict[str, Any]]:
    """Flatten either results layout into {doc_name, question, answer} rows."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: List[Dict[str, Any]] = []
    for entry in payload:
        if "questions" in entry:
            doc_name = Path(entry["doc_path"]).stem
            for item in entry["questions"]:
                rows.append(
                    {
                        "doc_name": doc_name,
                        "question": item["question"],
                        "answer": item.get("answer"),
                    }
                )
        else:
            rows.append(
                {
                    "doc_name": Path(entry["doc"]).stem,
                    "question": entry["question"],
                    "answer": entry.get("answer"),
                }
            )
    return rows


def gold_pages(record: Dict[str, Any]) -> Set[int]:
    return {
        ev["evidence_page_num"]
        for ev in record.get("evidence", [])
        if ev.get("evidence_page_num") is not None
    }


def page_is_correct(page: Optional[int], gold: Set[int], tolerance: int) -> bool:
    if page is None or not gold:
        return False
    return any(abs(page - g) <= tolerance for g in gold)


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def score_run(
    rows: Sequence[Dict[str, Any]],
    gold_by_key: Dict[Tuple[str, str], Dict[str, Any]],
    rel_tol: float,
    page_tolerance: int,
    judge_client=None,
) -> Tuple[List[Dict[str, Any]], Counter]:
    scored: List[Dict[str, Any]] = []
    tally: Counter = Counter()

    for row in rows:
        record = gold_by_key.get((row["doc_name"], row["question"]))
        answer = row.get("answer")

        if record is None:
            tally["not_in_key"] += 1
            continue
        if answer is None:
            tally["not_run"] += 1
            continue

        tally["evaluated"] += 1
        pages = gold_pages(record)

        if not answer.get("found"):
            tally["abstained"] += 1
            scored.append(
                {
                    **{k: row[k] for k in ("doc_name", "question")},
                    "outcome": "abstained",
                    "score": 0,
                    "gold_answer": record["answer"],
                    "model_answer": answer.get("text"),
                    "gold_pages": sorted(pages),
                    "model_page": answer.get("page"),
                    "abstention_reason": answer.get("abstention_reason"),
                }
            )
            continue

        model_text = str(answer.get("text") or "")
        location_ok = page_is_correct(answer.get("page"), pages, page_tolerance)

        if gold_is_bare_figure(record):
            correct = numeric_match(record["answer"], model_text, rel_tol)
            basis = "numeric"
            note = ""
        else:
            correct, basis, note = None, "prose", ""
            if judge_client is not None:
                correct, note = judge_prose(
                    judge_client, row["question"], record["answer"], model_text
                )
                basis = "llm_judge"

        if correct is None:
            outcome, score = "unjudged", 0
            tally["unjudged"] += 1
        elif correct and location_ok:
            outcome, score = "correct_with_location", 1
            tally["plus_one"] += 1
        elif correct:
            outcome, score = "correct_wrong_location", 0
            tally["correct_wrong_location"] += 1
        else:
            outcome, score = "confidently_wrong", -1
            tally["minus_one"] += 1

        scored.append(
            {
                **{k: row[k] for k in ("doc_name", "question")},
                "outcome": outcome,
                "score": score,
                "basis": basis,
                "gold_answer": record["answer"],
                "model_answer": model_text,
                "gold_pages": sorted(pages),
                "model_page": answer.get("page"),
                "location_ok": location_ok,
                "note": note,
            }
        )

    return scored, tally


def report(scored: List[Dict[str, Any]], tally: Counter, page_tolerance: int) -> None:
    total = sum(item["score"] for item in scored)
    evaluated = tally["evaluated"]

    print("\n" + "=" * 66)
    print(f"RUBRIC SCORE: {total:+d}   over {evaluated} evaluated question(s)")
    print("=" * 66)
    print(f"  +1  correct answer, correct location : {tally['plus_one']}")
    print(f"   0  correct answer, wrong location   : {tally['correct_wrong_location']}")
    print(f"   0  abstained (not found)            : {tally['abstained']}")
    print(f"  -1  confidently wrong               : {tally['minus_one']}")
    if tally["unjudged"]:
        print(f"   ?  prose, not auto-judged           : {tally['unjudged']}  (use --judge)")
    if tally["not_run"]:
        print(f"      not yet run                     : {tally['not_run']}")
    if tally["not_in_key"]:
        print(f"      not in practice key             : {tally['not_in_key']}")

    answered = tally["plus_one"] + tally["correct_wrong_location"] + tally["minus_one"]
    if answered:
        correct = tally["plus_one"] + tally["correct_wrong_location"]
        print(f"\n  answer accuracy when it answers : {correct}/{answered} = {correct/answered:.0%}")
        if correct:
            print(
                f"  location accuracy when correct  : {tally['plus_one']}/{correct} "
                f"= {tally['plus_one']/correct:.0%}  (tolerance +-{page_tolerance})"
            )

    losses = [i for i in scored if i["score"] < 0]
    if losses:
        print(f"\n  --- {len(losses)} answer(s) costing -1 ---")
        for item in losses[:10]:
            print(f"   {item['doc_name']}: {item['question'][:64]}")
            print(f"      gold : {str(item['gold_answer'])[:80]}")
            print(f"      model: {str(item['model_answer'])[:80]}")

    near = [
        i
        for i in scored
        if i["outcome"] == "correct_wrong_location"
    ]
    if near:
        print(f"\n  --- {len(near)} right answer(s) losing the mark on location ---")
        for item in near[:10]:
            print(
                f"   {item['doc_name']}: cited {item['model_page']}, "
                f"gold {item['gold_pages']} | {item['question'][:48]}"
            )

    reasons = Counter(
        i.get("abstention_reason") or "unrecorded"
        for i in scored
        if i["outcome"] == "abstained"
    )
    if reasons:
        print("\n  --- why it abstained ---")
        for reason, count in reasons.most_common():
            print(f"   {count:3d}  {reason}")


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Score answers against the practice key.")
    parser.add_argument(
        "--results",
        type=Path,
        default=settings.data_dir / "questions-by-doc-results.json",
        help="Results JSON from a runner.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.data_dir / "eval-scores.json",
        help="Where to write the per-question scoring detail.",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Use the chat model to grade prose answers that cannot be checked numerically.",
    )
    parser.add_argument(
        "--rel-tol",
        type=float,
        default=DEFAULT_REL_TOL,
        help=f"Relative tolerance for numeric agreement (default {DEFAULT_REL_TOL}).",
    )
    parser.add_argument(
        "--page-tolerance",
        type=int,
        default=0,
        help="Allowed page offset when checking location (default 0 = exact).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.results.exists():
        raise SystemExit(f"No results file at {args.results}")

    gold_by_key = load_gold()
    rows = load_results(args.results)

    judge_client = None
    if args.judge:
        from analyst_copilot.llm import get_chat_client

        judge_client = get_chat_client()
        print(f"Judging prose answers with {judge_client.model_name}")

    scored, tally = score_run(
        rows,
        gold_by_key,
        rel_tol=args.rel_tol,
        page_tolerance=args.page_tolerance,
        judge_client=judge_client,
    )
    report(scored, tally, args.page_tolerance)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "results_file": str(args.results),
                "rel_tol": args.rel_tol,
                "page_tolerance": args.page_tolerance,
                "judged": bool(args.judge),
                "total_score": sum(item["score"] for item in scored),
                "tally": dict(tally),
                "items": scored,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
