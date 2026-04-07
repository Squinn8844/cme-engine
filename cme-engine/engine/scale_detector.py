"""
scale_detector.py
─────────────────
Detect which Likert scale family a column uses by matching
response labels against a library of known scale variants.
Requires >= 60% label overlap to match.
Falls back to ordinal inference if no match found.

All scale families are DATA, not code — adding a new variant
requires only adding an entry to SCALE_LIBRARY, no code changes.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from .normalizer import normalize, is_opt_out


# ── Scale library ─────────────────────────────────────────────────────────────
# Each entry: (family_name, scale_type, ordered_labels_low_to_high)
# Labels stored normalized (lowercase, plain ASCII).

SCALE_LIBRARY = [
    # ── Confidence ──
    ("CONFIDENCE_A", "confidence",
     ["not at all confident", "not very confident", "neutral",
      "somewhat confident", "very confident"]),

    ("CONFIDENCE_B", "confidence",
     ["not confident", "somewhat confident", "moderately confident",
      "very confident", "extremely confident"]),

    ("CONFIDENCE_C", "confidence",
     ["not at all", "slightly confident", "moderately confident",
      "very confident", "extremely confident"]),

    # ── Familiarity ──
    ("FAMILIARITY_A", "familiarity",
     ["not at all familiar", "not very familiar", "neutral",
      "somewhat familiar", "very familiar"]),

    ("FAMILIARITY_B", "familiarity",
     ["not familiar", "somewhat familiar", "moderately familiar",
      "very familiar", "extremely familiar"]),

    # ── Frequency ──
    ("FREQUENCY_A", "frequency",
     ["never", "25% of the time", "50% of the time",
      "75% of the time", "100% of the time"]),

    ("FREQUENCY_B", "frequency",
     ["never", "rarely", "sometimes", "often", "always"]),

    ("FREQUENCY_C", "frequency",
     ["never", "less than 25% of the time", "25-50% of the time",
      "51-75% of the time", "more than 75% of the time"]),

    # ── Agreement ──
    ("AGREEMENT_A", "agreement",
     ["strongly disagree", "disagree", "neutral",
      "agree", "strongly agree"]),

    ("AGREEMENT_B", "agreement",
     ["strongly disagree", "disagree", "somewhat agree",
      "agree", "strongly agree"]),

    ("AGREEMENT_C", "agreement",
     ["strongly disagree", "disagree", "neither agree nor disagree",
      "agree", "strongly agree"]),

    # ── Likelihood ──
    ("LIKELIHOOD_A", "likelihood",
     ["not likely", "somewhat likely", "likely",
      "very likely", "extremely likely"]),

    ("LIKELIHOOD_B", "likelihood",
     ["not at all likely", "unlikely", "neutral",
      "likely", "very likely"]),

    # ── Satisfaction ──
    ("SATISFACTION_A", "satisfaction",
     ["very dissatisfied", "dissatisfied", "neutral",
      "satisfied", "very satisfied"]),

    # ── Knowledge/Competence ──
    ("KNOWLEDGE_A", "knowledge",
     ["no knowledge", "minimal knowledge", "moderate knowledge",
      "good knowledge", "excellent knowledge"]),
]

# Minimum fraction of scale labels that must appear in the data
MATCH_THRESHOLD = 0.60

# Ordinal anchor words for fallback inference
ORDINAL_LOW  = {"not", "never", "none", "no", "low", "poor", "minimal",
                "strongly disagree", "not at all"}
ORDINAL_HIGH = {"very", "extremely", "always", "excellent", "strongly agree",
                "completely", "highly", "maximum", "fully"}


@dataclass
class ScaleResult:
    family: str           # e.g. "CONFIDENCE_A"
    scale_type: str       # e.g. "confidence"
    mapping: dict         # {original_label: numeric_value}
    confidence: float     # 0.0 – 1.0 overlap score
    inferred: bool        # True if ordinal inference used (no library match)


def detect_scale(values: list[str]) -> Optional[ScaleResult]:
    """
    Given a list of unique non-null response values from a column,
    return the best matching ScaleResult or None if no scale detected.

    Args:
        values: raw string values from the column (not yet normalized)

    Returns:
        ScaleResult with mapping {original_label → 1..N} or None
    """
    if not values:
        return None

    # Filter out opt-outs and nulls
    clean_vals = [v for v in values
                  if v and str(v).strip().lower() not in ("nan", "none", "")
                  and not is_opt_out(str(v))]
    if not clean_vals:
        return None

    norm_vals = {normalize(v): v for v in clean_vals}
    norm_set = set(norm_vals.keys())

    # ── Try library match ────────────────────────────────────────────────────
    best_family = None
    best_score = 0.0
    best_labels = None

    for family, scale_type, labels in SCALE_LIBRARY:
        label_set = set(labels)
        overlap = len(norm_set & label_set) / len(label_set)
        if overlap > best_score:
            best_score = overlap
            best_family = (family, scale_type)
            best_labels = labels

    if best_score >= MATCH_THRESHOLD and best_family and best_labels:
        # Build mapping: original_label → position (1-based)
        mapping = {}
        for norm_v, orig_v in norm_vals.items():
            for i, label in enumerate(best_labels, 1):
                if norm_v == label:
                    mapping[orig_v] = i
                    break
        if mapping:
            return ScaleResult(
                family=best_family[0],
                scale_type=best_family[1],
                mapping=mapping,
                confidence=best_score,
                inferred=False,
            )

    # ── Ordinal inference fallback ───────────────────────────────────────────
    # Try to infer ordering from anchor words
    inferred = _infer_ordinal(norm_vals)
    if inferred:
        return ScaleResult(
            family="INFERRED",
            scale_type="unknown",
            mapping=inferred,
            confidence=0.4,
            inferred=True,
        )

    return None


def _infer_ordinal(norm_vals: dict) -> Optional[dict]:
    """
    Attempt to infer a 1-N ordinal mapping from response values
    using anchor words at low and high ends.
    """
    norms = list(norm_vals.keys())
    if len(norms) < 2 or len(norms) > 7:
        return None

    # Score each value: negative = low anchor, positive = high anchor
    def score(s):
        words = set(s.lower().split())
        lo = sum(1 for w in ORDINAL_LOW if w in s)
        hi = sum(1 for w in ORDINAL_HIGH if w in s)
        return hi - lo

    scored = sorted(norms, key=score)
    # Check if we actually have low/high anchors
    if score(scored[0]) >= 0 and score(scored[-1]) <= 0:
        return None

    mapping = {}
    for i, norm_v in enumerate(scored, 1):
        orig_v = norm_vals[norm_v]
        mapping[orig_v] = i

    return mapping


def apply_scale(value: str, scale: ScaleResult) -> Optional[float]:
    """
    Convert a raw response string to its numeric value using the scale mapping.
    Returns None if the value is an opt-out or not in the mapping.
    """
    if not value or is_opt_out(str(value)):
        return None
    return scale.mapping.get(value)
