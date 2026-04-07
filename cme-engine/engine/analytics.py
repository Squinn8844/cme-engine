"""
analytics.py
────────────
Compute all CME outcomes metrics from a unified pool of Respondent objects.

Key principles:
  - ALL metrics computed from unified pool, never from per-vendor aggregates
  - Per-vendor breakdowns stored alongside combined for transparency
  - Opt-out responses excluded from Likert numeric pooling
  - Every computation accompanied by audit trail data
"""

from __future__ import annotations
from collections import defaultdict
from typing import Optional
import datetime

from .models import (Respondent, KQResult, LikertResult, EvalResult,
                     AnalyticsResult)
from .normalizer import normalize, answers_match
from .key_parser import ParsedKey
from .version import VERSION

# Keywords for detecting eval question types
INTENT_KEYWORDS    = ["intend", "change my practice", "modify", "plan to change"]
RECOMMEND_KEYWORDS = ["recommend"]
BIAS_KEYWORDS      = ["bias", "commercial", "free of"]
CONTENT_NEW_KEYWORDS = ["new to you", "percentage", "% of the"]
FOLLOWUP_CHANGE_KEYWORDS = ["did you make", "changed", "my practice was reinforced",
                              "made changes"]


def _pct(n: int, d: int) -> Optional[float]:
    return n / d if d > 0 else None


def compute(
    respondents: list[Respondent],
    parsed_key: ParsedKey,
    program_name: str = "Unknown Program",
    file_hashes: dict = None,
) -> AnalyticsResult:
    """
    Compute all analytics from the unified respondent pool.

    Args:
        respondents: all respondents from all vendors combined
        parsed_key: parsed key with questions and correct answers
        program_name: display name for the program
        file_hashes: {filename: sha256} for audit trail

    Returns:
        AnalyticsResult with all metrics and audit data
    """
    log: list[str] = []
    warnings: list[str] = []

    result = AnalyticsResult(
        program_name=program_name,
        engine_version=VERSION,
        file_hashes=file_hashes or {},
        computed_at=datetime.datetime.utcnow().isoformat() + "Z",
    )

    if not respondents:
        warnings.append("No respondents — cannot compute analytics.")
        result.warnings = warnings
        return result

    # ── Respondent counts ─────────────────────────────────────────────────────
    result.total       = len(respondents)
    result.with_post   = sum(1 for r in respondents if r.has_post)
    result.with_eval   = sum(1 for r in respondents if r.has_eval)
    result.with_followup = sum(1 for r in respondents if r.has_followup)
    result.pre_only    = result.total - result.with_post

    # Vendor counts
    vendor_counts = defaultdict(int)
    for r in respondents:
        vendor_counts[r.vendor] += 1
    result.vendors = dict(vendor_counts)

    log.append(
        f"Pool: {result.total} total, {result.with_post} with_post, "
        f"{result.with_eval} with_eval, {result.with_followup} with_followup"
    )
    log.append(f"Vendors: {result.vendors}")

    # ── Knowledge questions ───────────────────────────────────────────────────
    kq_results = []

    for q in parsed_key.knowledge_questions:
        pre_by_vendor  = defaultdict(lambda: {"n": 0, "correct": 0})
        post_by_vendor = defaultdict(lambda: {"n": 0, "correct": 0})

        for r in respondents:
            v = r.vendor

            # Pre
            if q.id in r.pre_kq:
                pre_by_vendor[v]["n"] += 1
                if answers_match(r.pre_kq[q.id], q.correct_answer):
                    pre_by_vendor[v]["correct"] += 1

            # Post
            if q.id in r.post_kq:
                post_by_vendor[v]["n"] += 1
                if answers_match(r.post_kq[q.id], q.correct_answer):
                    post_by_vendor[v]["correct"] += 1

        # Combined totals
        pre_n       = sum(v["n"] for v in pre_by_vendor.values())
        pre_correct = sum(v["correct"] for v in pre_by_vendor.values())
        post_n      = sum(v["n"] for v in post_by_vendor.values())
        post_correct = sum(v["correct"] for v in post_by_vendor.values())

        # Per-vendor breakdown
        all_vendors = sorted(set(list(pre_by_vendor.keys()) + list(post_by_vendor.keys())))
        breakdown = []
        for vname in all_vendors:
            pre_v  = pre_by_vendor[vname]
            post_v = post_by_vendor[vname]
            breakdown.append({
                "vendor":        vname,
                "pre_n":         pre_v["n"],
                "pre_correct":   pre_v["correct"],
                "pre_pct":       _pct(pre_v["correct"], pre_v["n"]),
                "post_n":        post_v["n"],
                "post_correct":  post_v["correct"],
                "post_pct":      _pct(post_v["correct"], post_v["n"]),
            })

        kqr = KQResult(
            question_id=q.id,
            question_text=q.text,
            correct_answer=q.correct_answer,
            section="both" if post_n > 0 else "pre",
            pre_n=pre_n,
            pre_correct=pre_correct,
            post_n=post_n,
            post_correct=post_correct,
            vendor_breakdown=breakdown,
        )
        kq_results.append(kqr)

        log.append(
            f"KQ {q.id}: PRE {pre_correct}/{pre_n} "
            f"({_pct(pre_correct,pre_n):.1%} if pre_n else 'n/a'), "
            f"POST {post_correct}/{post_n} "
            f"({_pct(post_correct,post_n):.1%} if post_n else 'n/a')"
        )

    result.kq_results = kq_results

    # ── Likert measures ───────────────────────────────────────────────────────
    # Collect all Likert keys across all respondents
    all_pre_likert_keys  = set()
    all_post_likert_keys = set()
    for r in respondents:
        all_pre_likert_keys.update(r.pre_likert.keys())
        all_post_likert_keys.update(r.post_likert.keys())

    log.append(f"Likert pre keys found: {list(all_pre_likert_keys)[:5]}")
    log.append(f"Likert post keys found: {list(all_post_likert_keys)[:5]}")

    likert_results = []

    # Match pre and post Likert by normalized label similarity
    matched_pairs = _match_likert_pairs(all_pre_likert_keys, all_post_likert_keys)
    all_pre_keys_used = set()

    for pre_key, post_key in matched_pairs:
        pre_scores_by_vendor  = defaultdict(list)
        post_scores_by_vendor = defaultdict(list)

        for r in respondents:
            if pre_key in r.pre_likert:
                pre_scores_by_vendor[r.vendor].append(r.pre_likert[pre_key])
            if post_key and post_key in r.post_likert:
                post_scores_by_vendor[r.vendor].append(r.post_likert[post_key])

        pre_all  = [s for scores in pre_scores_by_vendor.values() for s in scores]
        post_all = [s for scores in post_scores_by_vendor.values() for s in scores]

        # Per-vendor breakdown
        all_vendors = sorted(set(
            list(pre_scores_by_vendor.keys()) + list(post_scores_by_vendor.keys())
        ))
        breakdown = []
        for vname in all_vendors:
            pre_v  = pre_scores_by_vendor[vname]
            post_v = post_scores_by_vendor[vname]
            breakdown.append({
                "vendor":    vname,
                "pre_n":     len(pre_v),
                "pre_sum":   sum(pre_v),
                "pre_mean":  sum(pre_v)/len(pre_v) if pre_v else None,
                "post_n":    len(post_v),
                "post_sum":  sum(post_v),
                "post_mean": sum(post_v)/len(post_v) if post_v else None,
            })

        # Detect scale type from key name
        scale_type = _infer_scale_type(pre_key)

        lr = LikertResult(
            question_id=pre_key,
            label=pre_key[:80],
            scale_family="detected",
            scale_type=scale_type,
            pre_n=len(pre_all),
            pre_sum=sum(pre_all),
            post_n=len(post_all),
            post_sum=sum(post_all),
            has_post=len(post_all) > 0,
            vendor_breakdown=breakdown,
        )
        likert_results.append(lr)
        all_pre_keys_used.add(pre_key)
        log.append(
            f"Likert '{pre_key[:40]}': "
            f"pre={lr.pre_mean:.2f} (n={lr.pre_n}), "
            f"post={lr.post_mean:.2f} (n={lr.post_n})" if lr.post_mean else
            f"Likert '{pre_key[:40]}': pre={lr.pre_mean:.2f} (n={lr.pre_n}), no post"
        )

    # Add pre-only Likert (no matching post)
    for pre_key in all_pre_likert_keys - all_pre_keys_used:
        scores = [r.pre_likert[pre_key] for r in respondents if pre_key in r.pre_likert]
        if not scores:
            continue
        lr = LikertResult(
            question_id=pre_key,
            label=pre_key[:80],
            scale_family="detected",
            scale_type=_infer_scale_type(pre_key),
            pre_n=len(scores),
            pre_sum=sum(scores),
            post_n=0,
            post_sum=0.0,
            has_post=False,
        )
        likert_results.append(lr)
        log.append(f"Likert pre-only '{pre_key[:40]}': mean={lr.pre_mean:.2f} (n={lr.pre_n})")

    result.likert_results = likert_results

    # ── Eval metrics ──────────────────────────────────────────────────────────
    eval_result = _compute_eval(respondents, log)
    result.eval_result = eval_result

    # ── Behavior changes and barriers ────────────────────────────────────────
    result.behavior_changes = _compute_freq_items(
        respondents, "behavior", log
    )
    result.barriers = _compute_freq_items(respondents, "barrier", log)
    result.followup_changes = _compute_followup(respondents, log)

    result.warnings  = warnings
    result.inference_log = log

    return result


def _match_likert_pairs(
    pre_keys: set, post_keys: set
) -> list[tuple[str, Optional[str]]]:
    """
    Match pre-Likert keys to post-Likert keys by normalized label similarity.
    Returns list of (pre_key, post_key_or_None).
    """
    pairs = []
    used_post = set()

    for pre_key in sorted(pre_keys):
        pre_norm = normalize(pre_key)
        # Strip temporal markers for matching
        pre_base = _strip_temporal(pre_norm)

        best_post = None
        best_score = 0.0

        for post_key in post_keys:
            if post_key in used_post:
                continue
            post_base = _strip_temporal(normalize(post_key))

            # Token overlap similarity
            pre_tokens = set(pre_base.split())
            post_tokens = set(post_base.split())
            if not pre_tokens:
                continue
            overlap = len(pre_tokens & post_tokens) / len(pre_tokens)

            if overlap > best_score and overlap >= 0.5:
                best_score = overlap
                best_post = post_key

        pairs.append((pre_key, best_post))
        if best_post:
            used_post.add(best_post)

    return pairs


def _strip_temporal(s: str) -> str:
    """Remove temporal markers from a normalized string for matching."""
    for marker in ["are you currently", "do you currently", "currently",
                    "are you now", "will you now", "you now",
                    "after participating", "after completing"]:
        s = s.replace(marker, "")
    return s.strip()


def _infer_scale_type(key: str) -> str:
    """Infer the scale type from the question label."""
    norm = key.lower()
    if "confident" in norm or "confidence" in norm:
        return "confidence"
    if "familiar" in norm or "familiarity" in norm:
        return "familiarity"
    if "frequent" in norm or "often" in norm or "discuss" in norm:
        return "frequency"
    if "agree" in norm or "intend" in norm:
        return "agreement"
    if "likely" in norm or "adopt" in norm:
        return "likelihood"
    return "unknown"


def _compute_eval(
    respondents: list[Respondent], log: list[str]
) -> EvalResult:
    """Compute evaluation survey metrics."""
    er = EvalResult()
    vendor_data = defaultdict(lambda: {
        "eval_n": 0, "intent_yes": 0, "intent_denom": 0,
        "recommend_yes": 0, "recommend_denom": 0,
        "bias_yes": 0, "bias_denom": 0,
        "cn_vals": [], "cn_n": 0,
    })

    agree_vals = {"agree", "strongly agree", "yes", "1", "true"}
    yes_vals   = {"yes", "1", "true", "agree", "strongly agree"}

    content_new_map = {
        "0-25%": 12.5, "0%-25%": 12.5, "less than 25%": 12.5,
        "26-50%": 37.5, "26%-50%": 37.5, "25-50%": 37.5,
        "51-75%": 62.5, "51%-75%": 62.5, "50-75%": 62.5,
        "76-100%": 87.5, "76%-100%": 87.5, "more than 75%": 87.5,
        "75-100%": 87.5, "100%": 100.0, "0%": 0.0,
    }

    for r in respondents:
        if not r.has_eval:
            continue
        v = r.vendor
        vendor_data[v]["eval_n"] += 1

        for col_name, val in r.eval_data.items():
            norm_col = col_name.lower()
            norm_val = val.lower().strip()

            # Intent to change
            if any(k in norm_col for k in INTENT_KEYWORDS):
                vendor_data[v]["intent_denom"] += 1
                if norm_val in agree_vals:
                    vendor_data[v]["intent_yes"] += 1

            # Recommend
            elif any(k in norm_col for k in RECOMMEND_KEYWORDS):
                vendor_data[v]["recommend_denom"] += 1
                if norm_val in yes_vals:
                    vendor_data[v]["recommend_yes"] += 1

            # Bias free
            elif any(k in norm_col for k in BIAS_KEYWORDS):
                vendor_data[v]["bias_denom"] += 1
                if norm_val in yes_vals:
                    vendor_data[v]["bias_yes"] += 1

            # Content new
            elif any(k in norm_col for k in CONTENT_NEW_KEYWORDS):
                mapped = content_new_map.get(norm_val)
                if mapped is None:
                    # Try numeric
                    try:
                        mapped = float(norm_val.replace("%", "").strip())
                    except Exception:
                        pass
                if mapped is not None:
                    vendor_data[v]["cn_vals"].append(mapped)
                    vendor_data[v]["cn_n"] += 1

    # Aggregate
    all_cn_vals = []
    breakdown = []
    for vname, d in vendor_data.items():
        er.intent_yes    += d["intent_yes"]
        er.intent_denom  += d["intent_denom"]
        er.recommend_yes += d["recommend_yes"]
        er.recommend_denom += d["recommend_denom"]
        er.bias_free_yes  += d["bias_yes"]
        er.bias_free_denom += d["bias_denom"]
        all_cn_vals.extend(d["cn_vals"])
        breakdown.append({
            "vendor":         vname,
            "eval_n":         d["eval_n"],
            "intent_yes":     d["intent_yes"],
            "intent_denom":   d["intent_denom"],
            "recommend_yes":  d["recommend_yes"],
            "recommend_denom": d["recommend_denom"],
            "bias_yes":       d["bias_yes"],
            "bias_denom":     d["bias_denom"],
        })

    if all_cn_vals:
        er.content_new_pct = sum(all_cn_vals) / len(all_cn_vals)
        er.content_new_n   = len(all_cn_vals)

    er.vendor_breakdown = breakdown

    log.append(
        f"Eval: intent={er.intent_yes}/{er.intent_denom}, "
        f"recommend={er.recommend_yes}/{er.recommend_denom}, "
        f"bias_free={er.bias_free_yes}/{er.bias_free_denom}, "
        f"content_new={er.content_new_pct:.1%} (n={er.content_new_n})"
        if er.content_new_pct else
        f"Eval: intent={er.intent_yes}/{er.intent_denom}"
    )

    return er


def _compute_freq_items(
    respondents: list[Respondent], item_type: str, log: list[str]
) -> list[dict]:
    """Count frequency of behavior change / barrier items."""
    counts = defaultdict(int)
    total_eval = sum(1 for r in respondents if r.has_eval)

    keywords = {
        "behavior": ["change", "implement", "incorporate", "adopt",
                     "discuss", "prescribe", "counsel", "use"],
        "barrier":  ["barrier", "lack", "limited", "difficulty",
                     "cost", "access", "formulary", "time"],
    }
    type_keywords = keywords.get(item_type, [])

    for r in respondents:
        if not r.has_eval:
            continue
        for col_name, val in r.eval_data.items():
            norm_col = col_name.lower()
            if any(k in norm_col for k in type_keywords):
                if val and str(val).strip().lower() not in ("nan", "", "none"):
                    counts[val] += 1

    if not counts:
        return []

    items = [
        {"label": label, "n": n,
         "pct": n / total_eval if total_eval > 0 else 0}
        for label, n in sorted(counts.items(), key=lambda x: -x[1])
        if n > 0
    ]
    return items[:25]  # Top 25


def _compute_followup(
    respondents: list[Respondent], log: list[str]
) -> list[dict]:
    """Compute follow-up behavior change items."""
    fu_respondents = [r for r in respondents if r.has_followup]
    if not fu_respondents:
        return []

    total_fu = len(fu_respondents)
    changed = sum(
        1 for r in fu_respondents
        if any(
            any(k in str(v).lower() for k in ["yes", "reinforced", "changed"])
            for v in r.followup_data.values()
        )
    )
    log.append(f"Follow-up: {changed}/{total_fu} made/reinforced changes")
    return [{"total": total_fu, "changed": changed,
             "pct": changed / total_fu if total_fu > 0 else 0}]
