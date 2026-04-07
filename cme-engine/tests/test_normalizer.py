"""
test_normalizer.py — Unit tests for string normalization.
Every encoding issue we've ever hit has a test here.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.normalizer import normalize, answers_match, is_opt_out, strip_correct_marker


class TestNormalize:
    def test_basic_strip(self):
        assert normalize("  hello  ") == "hello"

    def test_lowercase(self):
        assert normalize("Ask The Patient") == "ask the patient"

    def test_en_dash(self):
        # This is the bug that caused KQ1 4% on IL33
        nexus_val = "IL-33 initiates both type 2 and non\u2013type 2 inflammatory responses"
        exc_val   = "IL-33 initiates both type 2 and non\u00e2\u0080\u0093type 2 inflammatory responses"
        assert normalize(nexus_val) == normalize(exc_val)

    def test_mojibake_en_dash(self):
        assert normalize("non\u00e2\u0080\u0093type") == "non-type"

    def test_curly_quotes(self):
        assert normalize("\u201chello\u201d") == '"hello"'

    def test_html_entities(self):
        assert normalize("&amp;") == "&"
        assert normalize("&lt;b&gt;") == "<b>"

    def test_collapse_whitespace(self):
        assert normalize("hello   world") == "hello world"

    def test_excel_carriage_return(self):
        # Excel sometimes embeds \r\n in cell values
        assert normalize("hello\r\nworld") == "hello world"

    def test_unicode_fraction(self):
        # µ character in IL33 data
        assert normalize("100 cells/\u00b5L") == normalize("100 cells/µl")

    def test_empty_string(self):
        assert normalize("") == ""

    def test_none(self):
        assert normalize(None) == ""


class TestAnswersMatch:
    def test_exact_match(self):
        assert answers_match(
            "Ask the patient what factors matter most to them.",
            "Ask the patient what factors matter most to them."
        )

    def test_case_insensitive(self):
        assert answers_match(
            "ask the patient what factors matter most to them.",
            "Ask the patient what factors matter most to them."
        )

    def test_en_dash_variant(self):
        # The exact IL33 KQ1 encoding issue
        assert answers_match(
            "IL-33 initiates both type 2 and non\u2013type 2 inflammatory responses",
            "IL-33 initiates both type 2 and non\u00e2\u0080\u0093type 2 inflammatory responses"
        )

    def test_no_match(self):
        assert not answers_match("Option A", "Option B")

    def test_whitespace_difference(self):
        assert answers_match("hello world", "hello  world")


class TestIsOptOut:
    def test_do_not_manage(self):
        assert is_opt_out("I do not manage patients who are at risk of acquiring HIV.")

    def test_do_not_have_contact(self):
        assert is_opt_out("I do not have contact with patients/clients who are at risk of HIV infection.")

    def test_do_not_provide_care(self):
        assert is_opt_out("I do not provide care for patients who are sexually active.")

    def test_valid_response(self):
        assert not is_opt_out("Ask the patient what factors matter most to them.")

    def test_very_confident(self):
        assert not is_opt_out("Very confident")

    def test_empty(self):
        assert not is_opt_out("")


class TestStripCorrectMarker:
    def test_star_space(self):
        assert strip_correct_marker("* Ask the patient what factors matter most to them.") == \
               "Ask the patient what factors matter most to them."

    def test_star_no_space(self):
        assert strip_correct_marker("*Answer") == "Answer"

    def test_no_marker(self):
        assert strip_correct_marker("Answer") == "Answer"

    def test_preserves_content(self):
        long = "* HIV-1 RNA assay every 3 months for 12 months"
        assert strip_correct_marker(long) == "HIV-1 RNA assay every 3 months for 12 months"
