"""
models.py
─────────
Core data models for respondent records and analytics output.
All analytics are computed from a unified pool of Respondent objects.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Respondent:
    """
    One respondent's complete record across all sections.
    Created by parsers; consumed by analytics.py.
    """
    id: str                        # Unique ID (from file)
    vendor: str                    # Vendor/platform name
    has_pre: bool = False
    has_post: bool = False
    has_eval: bool = False
    has_followup: bool = False

    # KQ responses: {question_id: raw_response_string}
    pre_kq: dict = field(default_factory=dict)
    post_kq: dict = field(default_factory=dict)

    # Likert responses: {question_id: numeric_score}
    # Numeric score already applied by parser using detected scale
    pre_likert: dict = field(default_factory=dict)
    post_likert: dict = field(default_factory=dict)

    # Eval responses (intent, recommend, bias, content_new, behaviors)
    eval_data: dict = field(default_factory=dict)
    followup_data: dict = field(default_factory=dict)


@dataclass
class KQResult:
    """Computed result for one knowledge question."""
    question_id: str
    question_text: str
    correct_answer: str
    section: str                  # 'pre' | 'post' | 'both'

    # Combined (all vendors)
    pre_n: int = 0
    pre_correct: int = 0
    post_n: int = 0
    post_correct: int = 0

    # Per-vendor breakdown
    vendor_breakdown: list = field(default_factory=list)
    # Each entry: {vendor, pre_n, pre_correct, post_n, post_correct}

    @property
    def pre_pct(self) -> Optional[float]:
        return self.pre_correct / self.pre_n if self.pre_n > 0 else None

    @property
    def post_pct(self) -> Optional[float]:
        return self.post_correct / self.post_n if self.post_n > 0 else None

    @property
    def gain_pp(self) -> Optional[float]:
        if self.pre_pct is not None and self.post_pct is not None:
            return self.post_pct - self.pre_pct
        return None

    @property
    def relative_gain_pct(self) -> Optional[float]:
        if self.gain_pp is not None and self.pre_pct and self.pre_pct > 0:
            return self.gain_pp / self.pre_pct
        return None


@dataclass
class LikertResult:
    """Computed result for one Likert measure."""
    question_id: str
    label: str                    # Display label (truncated question text)
    scale_family: str             # e.g. CONFIDENCE_A
    scale_type: str               # e.g. confidence

    pre_n: int = 0
    pre_sum: float = 0.0
    post_n: int = 0
    post_sum: float = 0.0

    has_post: bool = False        # True if post data exists

    vendor_breakdown: list = field(default_factory=list)

    @property
    def pre_mean(self) -> Optional[float]:
        return round(self.pre_sum / self.pre_n, 4) if self.pre_n > 0 else None

    @property
    def post_mean(self) -> Optional[float]:
        return round(self.post_sum / self.post_n, 4) if self.post_n > 0 else None

    @property
    def delta(self) -> Optional[float]:
        if self.pre_mean is not None and self.post_mean is not None:
            return round(self.post_mean - self.pre_mean, 4)
        return None


@dataclass
class EvalResult:
    """Computed evaluation survey metrics."""
    intent_yes: int = 0
    intent_denom: int = 0
    recommend_yes: int = 0
    recommend_denom: int = 0
    bias_free_yes: int = 0
    bias_free_denom: int = 0
    content_new_pct: Optional[float] = None
    content_new_n: int = 0
    vendor_breakdown: list = field(default_factory=list)

    @property
    def intent_pct(self) -> Optional[float]:
        return self.intent_yes / self.intent_denom if self.intent_denom > 0 else None

    @property
    def recommend_pct(self) -> Optional[float]:
        return self.recommend_yes / self.recommend_denom if self.recommend_denom > 0 else None

    @property
    def bias_free_pct(self) -> Optional[float]:
        return self.bias_free_yes / self.bias_free_denom if self.bias_free_denom > 0 else None


@dataclass
class AnalyticsResult:
    """
    Complete analytics output for one program.
    This is what the UI and report generator consume.
    """
    program_name: str
    engine_version: str
    file_hashes: dict              # {filename: sha256_hash}
    computed_at: str               # ISO timestamp

    # Respondent counts
    total: int = 0
    pre_only: int = 0
    with_post: int = 0
    with_eval: int = 0
    with_followup: int = 0

    # Vendor breakdown
    vendors: dict = field(default_factory=dict)  # {vendor_name: n}

    # Results
    kq_results: list[KQResult] = field(default_factory=list)
    likert_results: list[LikertResult] = field(default_factory=list)
    eval_result: Optional[EvalResult] = None

    # Behavior change and barriers
    behavior_changes: list = field(default_factory=list)
    barriers: list = field(default_factory=list)
    followup_changes: list = field(default_factory=list)

    # Quality
    warnings: list[str] = field(default_factory=list)
    validation_flags: list[str] = field(default_factory=list)
    inference_log: list[str] = field(default_factory=list)

    def get_kq(self, question_id: str) -> Optional[KQResult]:
        for q in self.kq_results:
            if q.question_id == question_id:
                return q
        return None

    def get_likert(self, scale_type: str) -> Optional[LikertResult]:
        for l in self.likert_results:
            if l.scale_type == scale_type:
                return l
        return None
