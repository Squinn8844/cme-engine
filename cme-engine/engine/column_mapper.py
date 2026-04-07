"""
column_mapper.py
────────────────
Correct-answer-first column discovery.
Works on ANY dataframe regardless of column positions or header text.

Algorithm:
  For each knowledge question Q (from key):
    For each column C in the dataframe:
      Count how many rows have normalize(cell) == normalize(Q.correct_answer)
      Score = match_count / non_null_count
    Column with highest score (above threshold) → mapped to Q

  For unmapped columns:
    Run scale detector on unique values
    If scale detected → Likert column
    Else → demographic / ignore

This approach is immune to:
  - Column position changes
  - Header text differences
  - Excel .1 duplicate suffixes
  - Non-contiguous KQ columns
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
from .normalizer import normalize, normalize_col_name
from .scale_detector import detect_scale, ScaleResult
from .key_parser import Question

# Minimum fraction of non-null values that must match for a KQ column assignment
KQ_MATCH_THRESHOLD = 0.05   # 5% — handles low pre-correct rates like IL33 KQ2 at 4%
KQ_MIN_MATCHES = 2           # Absolute minimum matches (prevents noise)


@dataclass
class ColumnMapping:
    """Result of mapping a single column."""
    col_index: int
    col_name: str
    mapping_type: str          # 'knowledge' | 'likert' | 'demographic' | 'id' | 'unknown'
    question_id: Optional[str] = None
    scale: Optional[ScaleResult] = None
    match_rate: float = 0.0
    match_count: int = 0
    confidence: str = "HIGH"   # HIGH | MEDIUM | LOW
    notes: str = ""


@dataclass
class SheetMapping:
    """All column mappings for a sheet."""
    sheet_name: str
    id_col: Optional[int]
    kq_cols: dict            # {question_id: col_index}
    likert_cols: dict        # {col_index: ColumnMapping}
    demographic_cols: list   # [col_index]
    unknown_cols: list       # [col_index]
    all_mappings: list       # [ColumnMapping]
    warnings: list[str] = field(default_factory=list)
    inference_log: list[str] = field(default_factory=list)


def map_columns(
    df: pd.DataFrame,
    knowledge_questions: list[Question],
    sheet_name: str = "",
    id_col_hint: int = 0,
    section: str = "pre",
) -> SheetMapping:
    """
    Map all columns in a dataframe to question types.

    Args:
        df: the dataframe to map
        knowledge_questions: Score=1 questions from key (for KQ scanning)
        sheet_name: name of sheet (for logging)
        id_col_hint: expected position of ID column (default 0)
        section: 'pre' | 'post' | 'eval' | 'followup'

    Returns:
        SheetMapping with all columns classified
    """
    warnings = []
    log = []
    all_mappings = []
    kq_cols = {}
    likert_cols = {}
    demographic_cols = []
    unknown_cols = []
    id_col = None

    n_rows = len(df)
    if n_rows == 0:
        return SheetMapping(sheet_name, None, {}, {}, [], [],
                            [], ["Empty dataframe"], [])

    # ── Step 1: Identify ID column ─────────────────────────────────────────
    for i, col in enumerate(df.columns):
        norm_name = normalize_col_name(str(col)).lower()
        if norm_name in ("id", "respondent_id", "respondentid", "userid",
                          "user_id", "token", "participant_id"):
            id_col = i
            log.append(f"ID column: col[{i}] '{col}'")
            break
    if id_col is None:
        id_col = id_col_hint
        log.append(f"ID column assumed at col[{id_col_hint}] (no explicit ID header found)")

    # ── Step 2: KQ column scanning ────────────────────────────────────────
    # For each knowledge question, find the column with highest match rate
    assigned_cols = {id_col}  # Columns already claimed

    for q in knowledge_questions:
        if not q.correct_answer_norm:
            continue

        best_col = None
        best_score = 0.0
        best_count = 0

        for i, col in enumerate(df.columns):
            if i in assigned_cols:
                continue

            series = df.iloc[:, i].dropna()
            if len(series) == 0:
                continue

            norm_series = series.apply(lambda x: normalize(str(x)))
            matches = (norm_series == q.correct_answer_norm).sum()
            score = matches / len(series)

            if matches >= KQ_MIN_MATCHES and score > best_score:
                best_score = score
                best_col = i
                best_count = int(matches)

        if best_col is not None and best_score >= KQ_MATCH_THRESHOLD:
            confidence = "HIGH" if best_score >= 0.20 else \
                         "MEDIUM" if best_score >= 0.08 else "LOW"
            m = ColumnMapping(
                col_index=best_col,
                col_name=normalize_col_name(str(df.columns[best_col])),
                mapping_type="knowledge",
                question_id=q.id,
                match_rate=round(best_score, 4),
                match_count=best_count,
                confidence=confidence,
                notes=f"correct answer: '{q.correct_answer[:50]}'"
            )
            kq_cols[q.id] = best_col
            assigned_cols.add(best_col)
            all_mappings.append(m)
            log.append(
                f"KQ col[{best_col}] → {q.id} "
                f"(match_rate={best_score:.1%}, n={best_count}, conf={confidence})"
            )
            if confidence == "LOW":
                warnings.append(
                    f"Low-confidence KQ mapping: col[{best_col}] → {q.id} "
                    f"({best_score:.1%} match rate). Verify correct answer encoding."
                )
        else:
            warnings.append(
                f"No column found for {q.id} "
                f"(correct_answer='{q.correct_answer}') in sheet '{sheet_name}'. "
                f"Check answer encoding in key vs data file."
            )
            log.append(f"KQ MISS: {q.id} — no column matched in '{sheet_name}'")

    # ── Step 3: Likert and demographic column detection ───────────────────
    for i, col in enumerate(df.columns):
        if i in assigned_cols:
            continue

        series = df.iloc[:, i].dropna()
        if len(series) == 0:
            unknown_cols.append(i)
            continue

        unique_vals = series.astype(str).unique().tolist()

        # Try scale detection
        scale = detect_scale(unique_vals)
        if scale:
            m = ColumnMapping(
                col_index=i,
                col_name=normalize_col_name(str(col)),
                mapping_type="likert",
                scale=scale,
                confidence="HIGH" if not scale.inferred else "LOW",
                notes=f"scale={scale.family} ({scale.scale_type}), "
                      f"confidence={scale.confidence:.0%}"
            )
            likert_cols[i] = m
            assigned_cols.add(i)
            all_mappings.append(m)
            log.append(
                f"Likert col[{i}] '{normalize_col_name(str(col))[:40]}' "
                f"→ {scale.family} ({'inferred' if scale.inferred else 'matched'})"
            )
            if scale.inferred:
                warnings.append(
                    f"Likert scale inferred (no library match) for col[{i}] "
                    f"'{normalize_col_name(str(col))[:40]}'. "
                    f"Verify scale assignment in processing log."
                )
        else:
            # Demographic or unknown
            n_unique = len(unique_vals)
            if n_unique <= 20:
                demographic_cols.append(i)
                m = ColumnMapping(
                    col_index=i,
                    col_name=normalize_col_name(str(col)),
                    mapping_type="demographic",
                )
                all_mappings.append(m)
                log.append(f"Demographic col[{i}] '{normalize_col_name(str(col))[:40]}'")
            else:
                unknown_cols.append(i)
                m = ColumnMapping(
                    col_index=i,
                    col_name=normalize_col_name(str(col)),
                    mapping_type="unknown",
                    notes=f"{n_unique} unique values"
                )
                all_mappings.append(m)
                log.append(f"Unknown col[{i}] '{normalize_col_name(str(col))[:40]}' "
                           f"({n_unique} unique vals)")

    return SheetMapping(
        sheet_name=sheet_name,
        id_col=id_col,
        kq_cols=kq_cols,
        likert_cols=likert_cols,
        demographic_cols=demographic_cols,
        unknown_cols=unknown_cols,
        all_mappings=all_mappings,
        warnings=warnings,
        inference_log=log,
    )
