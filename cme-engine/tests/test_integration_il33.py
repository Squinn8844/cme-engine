"""
test_integration_il33.py
────────────────────────
Integration test for IL33 program.
Tests the hardest format challenges: different Likert scale labels,
Excel .1 duplicate column suffix, non-contiguous KQ columns.
"""

import pytest
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import process

FIXTURES  = os.path.join(os.path.dirname(__file__), "fixtures", "IL33")
KEY_FILE  = os.path.join(FIXTURES, "IL33_Key.xlsx")
NEXUS_FILE = os.path.join(FIXTURES, "IL33NEXUS.xlsx")
EXCME_FILE = os.path.join(FIXTURES, "IL33EXHDATA.xlsx")


@pytest.fixture(scope="module")
def result():
    if not all(os.path.exists(f) for f in [KEY_FILE, NEXUS_FILE, EXCME_FILE]):
        pytest.skip("IL33 fixture files not found")
    return process(
        key_file=KEY_FILE,
        data_files=[NEXUS_FILE, EXCME_FILE],
        program_name="IL33 COPD"
    )


class TestRespondentCounts:
    def test_total(self, result):
        assert result.total == 2121

    def test_with_post(self, result):
        assert result.with_post == 459

    def test_with_followup(self, result):
        assert result.with_followup == 30


class TestKnowledgeQuestions:
    def test_kq_count(self, result):
        assert len(result.kq_results) == 4

    def test_kq1_bio_function(self, result):
        kq = next((q for q in result.kq_results
                   if "biological function" in q.question_text.lower() or
                      "il-33" in q.question_text.lower() and "function" in q.question_text.lower()), None)
        assert kq is not None, "KQ1 bio function not found"
        assert kq.pre_n == pytest.approx(2120, abs=10)
        assert kq.pre_pct == pytest.approx(0.336, abs=0.015)
        assert kq.post_n == pytest.approx(459, abs=5)
        assert kq.post_pct == pytest.approx(0.924, abs=0.015)

    def test_kq2_st2(self, result):
        kq = next((q for q in result.kq_results
                   if "st2" in q.question_text.lower() or
                      "st2-independent" in q.question_text.lower()), None)
        assert kq is not None, "KQ2 ST2 not found"
        assert kq.pre_n == pytest.approx(2120, abs=10)
        assert kq.pre_pct == pytest.approx(0.318, abs=0.015)
        assert kq.post_n == pytest.approx(459, abs=5)
        assert kq.post_pct == pytest.approx(0.856, abs=0.015)

    def test_kq3_gene_variant_full_population(self, result):
        """
        Critical test: KQ3 (gene variant) exists in Nexus Pre col[8]
        with Excel .1 duplicate suffix. Must find full n=2120, not just ExcCME n=237.
        """
        kq = next((q for q in result.kq_results
                   if "gene variant" in q.question_text.lower() or
                      "truncated" in q.correct_answer.lower()), None)
        assert kq is not None, "KQ3 gene variant not found"
        assert kq.pre_n == pytest.approx(2120, abs=10), \
            f"KQ3 pre n={kq.pre_n} — expected 2120 (both vendors). " \
            f"If 237, Nexus col[8] was not matched (Excel .1 bug)."
        assert kq.post_n == pytest.approx(459, abs=5)

    def test_kq4_phase2(self, result):
        kq = next((q for q in result.kq_results
                   if "phase 2" in q.question_text.lower() or
                      "former smokers" in q.correct_answer.lower()), None)
        assert kq is not None, "KQ4 phase 2 not found"
        assert kq.pre_n == pytest.approx(2120, abs=10)
        assert kq.post_n == pytest.approx(459, abs=5)


class TestLikert:
    def test_confidence_scale_b_detected(self, result):
        """
        IL33 uses CONFIDENCE_B scale (Not confident / Somewhat / Moderately / Very / Extremely).
        Engine must detect this dynamically, not assume CONFIDENCE_A.
        """
        conf = next((l for l in result.likert_results
                     if "confident" in l.label.lower()), None)
        assert conf is not None, "Confidence Likert not found"
        # Key check: n should be ~2120 (both vendors), not 900 (Nexus only) or 109 (ExcCME post only)
        assert conf.pre_n == pytest.approx(2120, abs=20), \
            f"Confidence pre n={conf.pre_n} — expected ~2120. " \
            f"If 900, ExcCME pre excluded. If 1883, ExcCME pre excluded."
        assert conf.pre_mean == pytest.approx(2.62, abs=0.1)
        assert conf.post_n == pytest.approx(459, abs=15)
        assert conf.post_mean == pytest.approx(3.11, abs=0.1)

    def test_familiarity_scale_b_detected(self, result):
        fam = next((l for l in result.likert_results
                    if "familiar" in l.label.lower()), None)
        assert fam is not None, "Familiarity Likert not found"
        assert fam.pre_n == pytest.approx(2120, abs=20)
        assert fam.pre_mean == pytest.approx(2.54, abs=0.1)
        assert fam.post_n == pytest.approx(459, abs=15)
        assert fam.post_mean == pytest.approx(3.06, abs=0.1)

    def test_no_incorrect_scale_values(self, result):
        """No Likert mean should be > 5 (would indicate scale mapping bug)."""
        for lr in result.likert_results:
            if lr.pre_mean:
                assert lr.pre_mean <= 5.0, f"{lr.label}: pre_mean={lr.pre_mean} > 5"
            if lr.post_mean:
                assert lr.post_mean <= 5.0, f"{lr.label}: post_mean={lr.post_mean} > 5"
