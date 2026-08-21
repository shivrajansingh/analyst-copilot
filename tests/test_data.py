import json

from analyst_copilot.config.settings import get_settings
from analyst_copilot.data import group_questions_by_doc, load_practice_records


def test_resolve_user_filing_path_accepts_relative_and_stem():
    from analyst_copilot.data import resolve_user_filing_path

    by_rel = resolve_user_filing_path("filings/3M_2018_10K.htm")
    by_stem = resolve_user_filing_path("3M_2018_10K")
    assert by_rel.name == "3M_2018_10K.htm"
    assert by_stem == by_rel


def test_group_questions_by_doc():
    records = load_practice_records()
    grouped = group_questions_by_doc(records)
    assert len(records) == 136
    assert len(grouped) == 78
    assert all("doc_path" in row and "questions" in row for row in grouped)
    first = grouped[0]
    assert first["doc_path"].startswith("filings/")
    assert first["doc_path"].endswith(".htm")
    assert isinstance(first["questions"], list) and first["questions"]
    total_questions = sum(len(row["questions"]) for row in grouped)
    assert total_questions == 136


def test_questions_by_doc_file_if_present():
    path = get_settings().data_dir / "questions-by-doc.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[0]["doc_path"]
    assert payload[0]["questions"]
