"""The rubric scorer's own grading decisions."""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "eval"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from score import gold_is_bare_figure, headline_value, numbers_in, numeric_match


def test_bare_figures_are_graded_arithmetically():
    for answer in ("$1577.00", "24.26", "1.9%", "$8.70", "8,738 million", "approximately 65"):
        assert gold_is_bare_figure({"answer": answer}) is True, answer


def test_short_prose_is_not_graded_arithmetically():
    """Grading these numerically scores a correct answer -1 for omitting the figure."""
    for answer in (
        "The consumer segment shrunk by 0.9% organically.",
        "In 2022, AMD brought in the most cashflow from Operations",
        "Corporate. Its net revenue was -$473 million.",
        "No. Verizon's debt decreased by $229 million.",
    ):
        assert gold_is_bare_figure({"answer": answer}) is False, answer


def test_answers_without_a_figure_are_prose():
    assert gold_is_bare_figure({"answer": "Yes, the company is profitable."}) is False


def test_numeric_match_allows_unit_rescaling():
    assert numeric_match("$8.70", "8,738 million", 0.02) is True
    assert numeric_match("$1577.00", "1,577", 0.02) is True
    assert numeric_match("$1577.00", "3,193", 0.02) is False


def test_headline_value_skips_the_fiscal_year():
    assert headline_value(numbers_in("Pepsico's FY2022 costs were $411 million")) == 411.0
