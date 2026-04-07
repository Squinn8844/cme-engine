"""
validator.py
────────────
Post-computation validation.
Runs consistency checks on AnalyticsResult before it reaches the UI.
All issues logged as validation_flags — never silently fail.
"""

from __future__ import annotations
from .models import AnalyticsResult


def validate(result: AnalyticsResult) -> AnalyticsResult:
    """
    Run all validation checks and populate result.validation_flags.
    Returns the same result object with flags added.
    """
    flags = []

    # ── 1. Post KQ correct counts all identical ───────────────────────────────
    post_kqs = [q for q in result.kq_results if q.post_n > 0]
    if len(post_kqs) >= 2:
        post_corrects = [q.post_correct for q in post_kqs]
        if len(set(post_corrects)) == 1 and post_corrects[0] > 0:
            flags.append(
                f"⚠ All {len(post_kqs)} KQ post correct counts are identical "
                f"({post_corrects[0]}/{post_kqs[0].post_n}). "
                f"Possible post column reuse bug — verify each KQ has a distinct post column."
            )

    # ── 2. Vendor excluded from combined KQ pool ──────────────────────────────
    if len(result.vendors) > 1:
        for kq in result.kq_results:
            vendors_in_pre  = {b["vendor"] for b in kq.vendor_breakdown if b["pre_n"] > 0}
            vendors_in_post = {b["vendor"] for b in kq.vendor_breakdown if b["post_n"] > 0}
            for vname in result.vendors:
                if vname not in vendors_in_pre:
                    flags.append(
                        f"⚠ Vendor '{vname}' contributed 0 pre responses to KQ '{kq.question_id}'. "
                        f"Check correct answer encoding for this vendor's data."
                    )
                if kq.post_n > 0 and vname not in vendors_in_post:
                    flags.append(
                        f"⚠ Vendor '{vname}' contributed 0 post responses to KQ '{kq.question_id}'."
                    )

    # ── 3. Likert post n exceeds eval count ───────────────────────────────────
    for lr in result.likert_results:
        if lr.post_n > result.with_eval:
            flags.append(
                f"⚠ Likert '{lr.label[:40]}' post n={lr.post_n} "
                f"exceeds eval count={result.with_eval}. "
                f"Post Likert may be reading from wrong sheet."
            )

    # ── 4. Likert mean out of bounds ──────────────────────────────────────────
    for lr in result.likert_results:
        if lr.pre_mean is not None and not (1.0 <= lr.pre_mean <= 5.0):
            flags.append(
                f"⚠ Likert '{lr.label[:40]}' pre mean={lr.pre_mean:.2f} "
                f"is outside expected 1–5 range. Check scale mapping."
            )
        if lr.post_mean is not None and not (1.0 <= lr.post_mean <= 5.0):
            flags.append(
                f"⚠ Likert '{lr.label[:40]}' post mean={lr.post_mean:.2f} "
                f"is outside expected 1–5 range."
            )

    # ── 5. KQ pre n vs total respondents ─────────────────────────────────────
    for kq in result.kq_results:
        if kq.pre_n > result.total:
            flags.append(
                f"⚠ KQ '{kq.question_id}' pre n={kq.pre_n} "
                f"exceeds total respondents={result.total}. Possible double-counting."
            )

    # ── 6. Post n exceeds with_post count ────────────────────────────────────
    for kq in result.kq_results:
        if kq.post_n > result.with_post:
            flags.append(
                f"⚠ KQ '{kq.question_id}' post n={kq.post_n} "
                f"exceeds with_post={result.with_post}."
            )

    # ── 7. Total sanity check ─────────────────────────────────────────────────
    vendor_sum = sum(result.vendors.values())
    if vendor_sum != result.total:
        flags.append(
            f"⚠ Vendor counts sum ({vendor_sum}) ≠ total ({result.total}). "
            f"Possible duplicate respondent IDs across vendors."
        )

    # ── 8. No post data at all ────────────────────────────────────────────────
    if result.with_post == 0:
        flags.append(
            "⚠ No matched pre/post respondents found. "
            "Verify Post sheet IDs match Pre sheet IDs, "
            "or that Exchange POST section columns are non-null."
        )

    # ── 9. Eval metrics denom > eval respondents ──────────────────────────────
    if result.eval_result:
        er = result.eval_result
        actual_eval = result.with_eval
        for metric, denom in [
            ("intent", er.intent_denom),
            ("recommend", er.recommend_denom),
            ("bias_free", er.bias_free_denom),
        ]:
            if denom > actual_eval:
                flags.append(
                    f"⚠ Eval metric '{metric}' denom={denom} "
                    f"exceeds eval respondents={actual_eval}."
                )

    result.validation_flags = flags

    if flags:
        result.inference_log.append(
            f"Validation: {len(flags)} flag(s) — review before reporting"
        )
    else:
        result.inference_log.append("Validation: all checks passed ✓")

    return result
