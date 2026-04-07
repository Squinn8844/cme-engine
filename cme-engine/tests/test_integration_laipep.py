"""
test_integration_laipep.py
──────────────────────────
Full integration test for LAI PrEP program.
All expected values verified from raw data audit.
These are the regression tests — any engine change must pass all assertions.
"""

import pytest
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import process

# Paths to fixture files (anonymized copies of real data)
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "LAIPrEP")
KEY_FILE  = os.path.join(FIXTURES, "LAI_KEY.xlsx")
NEXUS_FILE = os.path.join(FIXTURES, "NEXUS_LAIPrEP.xlsx")
EXCME_FILE = os.path.join(FIXTURES, "ExchangeCME_LAIPrEP.xlsx")


@pytest.fixture(scope="module")
def result():
    """Run the engine once for all tests in this module."""
    if not all(os.path.exists(f) for f in [KEY_FILE, NEXUS_FILE, EXCME_FILE]):
        pytest.skip("LAI PrEP fixture files not found — run anonymizer first")
    return process(
        key_file=KEY_FILE,
        data_files=[NEXUS_FILE, EXCME_FILE],
        program_name="LAI PrEP Journey"
    )


class TestRespondentCounts:
    def test_total_learners(self, result):
        assert result.total == 1215, f"Expected 1215, got {result.total}"

    def test_with_post(self, result):
        assert result.with_post == 225, f"Expected 225, got {result.with_post}"

    def test_with_eval(self, result):
        assert result.with_eval >= 221, f"Expected >=221, got {result.with_eval}"

    def test_with_followup(self, result):
        assert result.with_followup == 18

    def test_pre_only(self, result):
        assert result.pre_only == 990

    def test_vendor_counts(self, result):
        assert "Nexus" in result.vendors
        assert result.vendors["Nexus"] == 1093
        excme_key = [k for k in result.vendors if "Exchange" in k or "LAI" in k]
        assert len(excme_key) == 1
        assert result.vendors[excme_key[0]] == 122


class TestKnowledgeQuestions:
    def test_kq_count(self, result):
        assert len(result.kq_results) == 4, f"Expected 4 KQs, got {len(result.kq_results)}"

    def test_kq1_shared_decision_making(self, result):
        # When using shared decision-making...
        kq = next((q for q in result.kq_results
                   if "shared decision" in q.question_text.lower()), None)
        assert kq is not None, "KQ1 (shared decision making) not found"
        assert kq.pre_n == 1215, f"KQ1 pre n: expected 1215, got {kq.pre_n}"
        assert kq.pre_correct == pytest.approx(553, abs=5)
        assert kq.pre_pct == pytest.approx(0.455, abs=0.01)
        assert kq.post_n == 225
        assert kq.post_correct == pytest.approx(205, abs=5)
        assert kq.post_pct == pytest.approx(0.911, abs=0.01)

    def test_kq2_jordan_lab_tests(self, result):
        kq = next((q for q in result.kq_results
                   if "jordan" in q.question_text.lower()), None)
        assert kq is not None, "KQ2 (Jordan lab tests) not found"
        assert kq.pre_n == 1215
        assert kq.pre_pct == pytest.approx(0.328, abs=0.01)
        assert kq.post_n == 225
        assert kq.post_pct == pytest.approx(0.867, abs=0.01)

    def test_kq3_cab_lai_exception(self, result):
        kq = next((q for q in result.kq_results
                   if "except" in q.question_text.lower()), None)
        assert kq is not None, "KQ3 (CAB LAI exception) not found"
        assert kq.pre_n == 1215
        assert kq.pre_pct == pytest.approx(0.342, abs=0.01)
        assert kq.post_n == 225
        assert kq.post_pct == pytest.approx(0.893, abs=0.01)

    def test_kq4_discontinuation(self, result):
        kq = next((q for q in result.kq_results
                   if "discontinue" in q.question_text.lower()), None)
        assert kq is not None, "KQ4 (discontinuation) not found"
        assert kq.pre_n == 1215
        assert kq.pre_pct == pytest.approx(0.321, abs=0.01)
        assert kq.post_n == 225
        assert kq.post_pct == pytest.approx(0.889, abs=0.01)
        assert "hiv-1 rna" in kq.correct_answer.lower() or \
               "rna assay" in kq.correct_answer.lower(), \
               f"KQ4 wrong correct answer: {kq.correct_answer}"

    def test_post_counts_not_identical(self, result):
        """Regression: post correct counts must not all be the same number."""
        post_kqs = [q for q in result.kq_results if q.post_n > 0]
        if len(post_kqs) >= 2:
            post_corrects = [q.post_correct for q in post_kqs]
            assert len(set(post_corrects)) > 1, \
                f"All post correct counts identical ({post_corrects[0]}) — score reuse bug"

    def test_vendor_breakdown_present(self, result):
        """Every KQ must have per-vendor breakdown."""
        for kq in result.kq_results:
            assert len(kq.vendor_breakdown) >= 1
            for b in kq.vendor_breakdown:
                assert "vendor" in b
                assert "pre_n" in b
                assert "post_n" in b

    def test_both_vendors_in_kq_pre(self, result):
        """Both vendors must contribute to combined KQ pre pool."""
        for kq in result.kq_results:
            vendors_with_pre = [b["vendor"] for b in kq.vendor_breakdown
                                if b["pre_n"] > 0]
            assert len(vendors_with_pre) >= 2, \
                f"KQ '{kq.question_id}' only has {len(vendors_with_pre)} vendor(s) in pre"


class TestLikert:
    def test_familiarity_pre(self, result):
        fam = next((l for l in result.likert_results
                    if "familiar" in l.label.lower()), None)
        assert fam is not None, "Familiarity Likert not found"
        assert fam.pre_n == pytest.approx(1215, abs=10)
        assert fam.pre_mean == pytest.approx(2.47, abs=0.05)

    def test_familiarity_post(self, result):
        fam = next((l for l in result.likert_results
                    if "familiar" in l.label.lower()), None)
        assert fam is not None
        assert fam.post_n == pytest.approx(225, abs=10)
        assert fam.post_mean == pytest.approx(3.95, abs=0.05)
        assert fam.delta == pytest.approx(1.48, abs=0.05)

    def test_confidence_pre(self, result):
        conf = next((l for l in result.likert_results
                     if "confident" in l.label.lower()), None)
        assert conf is not None, "Confidence Likert not found"
        assert conf.pre_n == pytest.approx(1158, abs=10)
        assert conf.pre_mean == pytest.approx(2.51, abs=0.05)

    def test_confidence_post(self, result):
        conf = next((l for l in result.likert_results
                     if "confident" in l.label.lower()), None)
        assert conf is not None
        assert conf.post_n == pytest.approx(210, abs=10)
        assert conf.post_mean == pytest.approx(3.97, abs=0.05)


class TestEvalMetrics:
    def test_intent_to_change(self, result):
        er = result.eval_result
        assert er is not None
        assert er.intent_pct == pytest.approx(0.83, abs=0.02)

    def test_recommend(self, result):
        er = result.eval_result
        assert er.recommend_pct == pytest.approx(0.97, abs=0.02)

    def test_bias_free(self, result):
        er = result.eval_result
        assert er.bias_free_pct == pytest.approx(0.98, abs=0.02)


class TestValidation:
    def test_no_critical_validation_flags(self, result):
        """No validation flags should fire for a clean dataset."""
        critical = [f for f in result.validation_flags if "⚠" in f]
        assert len(critical) == 0, \
            f"Unexpected validation flags:\n" + "\n".join(critical)
