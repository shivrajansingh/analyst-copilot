"""Load and group practice questions by filing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from analyst_copilot.config.settings import get_settings


def practice_questions_path() -> Path:
    return get_settings().data_dir / "practice-questions.jsonl"


def questions_by_doc_path() -> Path:
    return get_settings().data_dir / "questions-by-doc.json"


def resolve_filing_path(doc_name: str) -> Path:
    """Map a practice `doc_name` to a file under filings/."""
    settings = get_settings()
    direct = settings.filings_dir / f"{doc_name}.htm"
    if direct.exists():
        return direct
    for path in settings.filings_dir.glob("*.htm"):
        if path.stem.lower() == doc_name.lower():
            return path
    raise FileNotFoundError(f"No filing found for document: {doc_name}")


def resolve_user_filing_path(doc_path: str) -> Path:
    """Resolve a CLI path, filename, or doc stem to an existing filing file."""
    settings = get_settings()
    raw = Path(doc_path).expanduser()
    candidates = [
        raw,
        settings.project_root / raw,
        settings.filings_dir / raw.name,
    ]
    if raw.suffix == "":
        candidates.append(settings.filings_dir / f"{raw.name}.htm")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return resolve_filing_path(raw.stem)


def load_practice_records(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    source = path or practice_questions_path()
    records: List[Dict[str, Any]] = []
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def group_questions_by_doc(records: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    Build [{doc_path, questions}] from practice JSONL.

    Questions stay in file order. Multiple questions for the same filing
    are grouped under one object.
    """
    settings = get_settings()
    rows = records if records is not None else load_practice_records()
    grouped: List[Dict[str, Any]] = []
    index_by_path: Dict[str, int] = {}

    for record in rows:
        filing = resolve_filing_path(record["doc_name"])
        doc_path = str(filing.relative_to(settings.project_root))
        if doc_path not in index_by_path:
            index_by_path[doc_path] = len(grouped)
            grouped.append({"doc_path": doc_path, "questions": []})
        grouped[index_by_path[doc_path]]["questions"].append(record["question"])

    return grouped


def write_questions_by_doc(destination: Optional[Path] = None) -> Path:
    target = destination or questions_by_doc_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = group_questions_by_doc()
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def load_questions_by_doc(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    source = path or questions_by_doc_path()
    return json.loads(source.read_text(encoding="utf-8"))
