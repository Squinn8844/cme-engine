"""
test_scale_detector.py — Unit tests for Likert scale detection.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.scale_detector import detect_scale, apply_scale


class TestDetectScale:
    def test_confidence_a(self):
        vals = ["Not at all confident", "Not very confident", "Neutral",
                "Somewhat confident", "Very confident"]
        r = detect_scale(vals)
        assert r is not None
        assert r.family == "CONFIDENCE_A"
        assert r.scale_type == "confidence"
        assert not r.inferred

    def test_confidence_b_il33(self):
        """IL33 uses a different confidence scale."""
        vals = ["Not confident", "Somewhat confident", "Moderately confident",
                "Very confident", "Extremely confident"]
        r = detect_scale(vals)
        assert r is not None
        assert r.family == "CONFIDENCE_B"
        assert r.mapping["Not confident"] == 1
        assert r.mapping["Extremely confident"] == 5

    def test_familiarity_a(self):
        vals = ["Not at all familiar", "Not very familiar", "Neutral",
                "Somewhat familiar", "Very familiar"]
        r = detect_scale(vals)
        assert r is not None
        assert r.family == "FAMILIARITY_A"

    def test_familiarity_b(self):
        vals = ["Not familiar", "Somewhat familiar", "Moderately familiar",
                "Very familiar", "Extremely familiar"]
        r = detect_scale(vals)
        assert r is not None
        assert r.family == "FAMILIARITY_B"

    def test_frequency_a(self):
        vals = ["Never", "25% of the time", "50% of the time",
                "75% of the time", "100% of the time"]
        r = detect_scale(vals)
        assert r is not None
        assert r.family == "FREQUENCY_A"
        assert r.mapping["Never"] == 1
        assert r.mapping["100% of the time"] == 5

    def test_agreement_a(self):
        vals = ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
        r = detect_scale(vals)
        assert r is not None
        assert r.scale_type == "agreement"

    def test_partial_match_above_threshold(self):
        """Should match even if some responses are missing."""
        vals = ["Somewhat confident", "Very confident", "Moderately confident"]
        r = detect_scale(vals)
        assert r is not None  # 3/5 = 60% = at threshold

    def test_no_match_demographics(self):
        """Demographic/KQ columns should not be detected as Likert."""
        vals = ["MD/DO", "NP", "PA", "RN", "PharmD", "Other"]
        r = detect_scale(vals)
        assert r is None

    def test_opt_out_excluded(self):
        """Opt-out responses should not prevent scale detection."""
        vals = ["Not at all confident", "Not very confident", "Neutral",
                "Somewhat confident", "Very confident",
                "I do not manage patients who are at risk of acquiring HIV."]
        r = detect_scale(vals)
        assert r is not None
        assert r.family == "CONFIDENCE_A"
        assert "I do not manage patients who are at risk of acquiring HIV." \
               not in r.mapping

    def test_empty_returns_none(self):
        assert detect_scale([]) is None

    def test_single_value_returns_none(self):
        assert detect_scale(["Yes"]) is None


class TestApplyScale:
    def test_maps_correctly(self):
        vals = ["Not confident", "Somewhat confident", "Moderately confident",
                "Very confident", "Extremely confident"]
        scale = detect_scale(vals)
        assert apply_scale("Not confident", scale) == 1
        assert apply_scale("Extremely confident", scale) == 5

    def test_opt_out_returns_none(self):
        vals = ["Not at all confident", "Not very confident", "Neutral",
                "Somewhat confident", "Very confident"]
        scale = detect_scale(vals)
        assert apply_scale("I do not manage patients", scale) is None

    def test_unmapped_returns_none(self):
        vals = ["Not confident", "Somewhat confident", "Moderately confident",
                "Very confident", "Extremely confident"]
        scale = detect_scale(vals)
        assert apply_scale("Something else entirely", scale) is None
