"""
parsers/nexus.py
────────────────
Parse Nexus platform Excel exports into Respondent records.

Expected sheets: Pre, PreNon, Post, Eval, Follow Up
All sheets optional except Pre/PreNon (at least one required).

Key behaviors:
  - Builds a respondent record for EVERY row in Pre and PreNon
  - has_post = True only if ID appears in Post sheet
  - has_eval = True only if ID appears in Eval sheet
  - Post-Likert read from Eval sheet ONLY (never from Post sheet)
  - Post sheet contains ONLY knowledge question columns
  - Temporal marker detection: 'NOW' / 'WILL YOU NOW' = post-Likert
"""

from __future__ import annotations
import pandas as pd
from typing import Optional
from ..normalizer import normalize, normalize_col_name, is_opt_out
from ..column_mapper import map_columns, SheetMapping
from ..scale_detector import apply_scale, detect_scale
from ..key_parser import ParsedKey, Question
from ..models import Respondent

# Temporal markers that identify post-Likert columns in Eval sheet
POST_TEMPORAL_MARKERS = [
    "are you now", "will you now", "you now",
    "after participating", "after completing", "after this activity",
    "following this", "following completion",
]

PRE_TEMPORAL_MARKERS = [
    "are you currently", "do you currently", "currently",
]


def _is_post_likert_col(col_name: str) -> bool:
    norm = col_name.lower()
    return any(m in norm for m in POST_TEMPORAL_MARKERS)


def _is_pre_likert_col(col_name: str) -> bool:
    norm = col_name.lower()
    return any(m in norm for m in PRE_TEMPORAL_MARKERS)


def _read_sheet(xl: pd.ExcelFile, candidates: list[str]) -> Optional[pd.DataFrame]:
    """Try to read a sheet by any of the candidate names."""
    for name in candidates:
        for sheet in xl.sheet_names:
            if sheet.strip().lower() == name.lower():
                return pd.read_excel(xl, sheet_name=sheet)
    return None


def parse_nexus(
    filepath: str,
    parsed_key: ParsedKey,
    log: list[str],
    warnings: list[str],
    vendor_name: str = "Nexus",
) -> list[Respondent]:
    """
    Parse a Nexus Excel file into a list of Respondent records.

    Args:
        filepath: path to Nexus .xlsx file
        parsed_key: parsed key with knowledge questions
        log: inference log to append to
        warnings: warnings list to append to
        vendor_name: name to tag respondents with

    Returns:
        list of Respondent objects
    """
    try:
        xl = pd.ExcelFile(filepath)
    except Exception as e:
        warnings.append(f"Cannot open Nexus file: {e}")
        return []

    log.append(f"Nexus: sheets found: {xl.sheet_names}")

    # ── Load sheets ──────────────────────────────────────────────────────────
    df_pre    = _read_sheet(xl, ["Pre"])
    df_prenon = _read_sheet(xl, ["PreNon"])
    df_post   = _read_sheet(xl, ["Post"])
    df_eval   = _read_sheet(xl, ["Eval", "Evaluation"])
    df_fu     = _read_sheet(xl, ["Follow Up", "Follow_Up", "FollowUp", "FU"])

    if df_pre is None and df_prenon is None:
        warnings.append("Nexus file has neither Pre nor PreNon sheet — cannot parse.")
        return []

    # ── Build ID lookup sets ─────────────────────────────────────────────────
    def get_ids(df):
        if df is None or len(df) == 0:
            return set()
        return set(df.iloc[:, 0].astype(str).str.strip())

    post_ids    = get_ids(df_post)
    eval_ids    = get_ids(df_eval)
    fu_ids      = get_ids(df_fu)

    log.append(f"Nexus: Pre={len(df_pre) if df_pre is not None else 0}, "
               f"PreNon={len(df_prenon) if df_prenon is not None else 0}, "
               f"Post={len(post_ids)}, Eval={len(eval_ids)}, FU={len(fu_ids)}")

    # ── Map Pre columns ──────────────────────────────────────────────────────
    pre_df = pd.concat([df for df in [df_pre, df_prenon] if df is not None],
                       ignore_index=True)
    pre_mapping = map_columns(
        pre_df,
        knowledge_questions=parsed_key.knowledge_questions,
        sheet_name="Nexus_Pre",
        section="pre",
    )
    log.extend([f"Nexus Pre: {line}" for line in pre_mapping.inference_log])
    warnings.extend(pre_mapping.warnings)

    # ── Map Post columns ─────────────────────────────────────────────────────
    post_mapping = None
    if df_post is not None and len(df_post) > 0:
        post_mapping = map_columns(
            df_post,
            knowledge_questions=parsed_key.knowledge_questions,
            sheet_name="Nexus_Post",
            section="post",
        )
        log.extend([f"Nexus Post: {line}" for line in post_mapping.inference_log])
        warnings.extend(post_mapping.warnings)

    # ── Map Eval Likert columns ──────────────────────────────────────────────
    eval_likert_map = {}   # {col_index: (question_label, ScaleResult)}
    eval_pre_likert_map = {}  # pre-Likert from Eval (shouldn't exist but handle it)

    if df_eval is not None and len(df_eval) > 0:
        for i, col in enumerate(df_eval.columns):
            if i == 0:
                continue  # Skip ID column
            col_name = normalize_col_name(str(col))
            series = df_eval.iloc[:, i].dropna()
            if len(series) == 0:
                continue
            unique_vals = series.astype(str).unique().tolist()
            scale = detect_scale(unique_vals)
            if scale:
                if _is_post_likert_col(col_name):
                    eval_likert_map[i] = (col_name, scale)
                    log.append(f"Nexus Eval post-Likert col[{i}]: '{col_name[:50]}' "
                               f"→ {scale.family}")
                elif _is_pre_likert_col(col_name):
                    # Unusual but handle gracefully
                    eval_pre_likert_map[i] = (col_name, scale)
                    log.append(f"Nexus Eval pre-Likert (unusual) col[{i}]: "
                               f"'{col_name[:50]}' → {scale.family}")

    # ── Build post KQ lookup: {respondent_id: {question_id: response}} ───────
    post_kq_lookup = {}
    if df_post is not None and post_mapping:
        for _, row in df_post.iterrows():
            rid = str(row.iloc[0]).strip()
            kqs = {}
            for qid, col_idx in post_mapping.kq_cols.items():
                val = row.iloc[col_idx]
                if pd.notna(val):
                    kqs[qid] = str(val).strip()
            post_kq_lookup[rid] = kqs

    # ── Build eval lookup: {respondent_id: {col_idx: numeric_score}} ────────
    eval_likert_lookup = {}
    eval_other_lookup = {}
    if df_eval is not None:
        for _, row in df_eval.iterrows():
            rid = str(row.iloc[0]).strip()
            likert_scores = {}
            other = {}
            for i, (label, scale) in eval_likert_map.items():
                val = row.iloc[i]
                if pd.notna(val) and not is_opt_out(str(val)):
                    score = apply_scale(str(val).strip(), scale)
                    if score is not None:
                        likert_scores[label] = score
            # Also capture eval/demographic data for intent, recommend, bias
            for i, col in enumerate(df_eval.columns):
                if i == 0:
                    continue
                val = row.iloc[i]
                if pd.notna(val):
                    other[normalize_col_name(str(col))] = str(val).strip()
            eval_likert_lookup[rid] = likert_scores
            eval_other_lookup[rid] = other

    # ── Build follow-up lookup ────────────────────────────────────────────────
    fu_lookup = {}
    if df_fu is not None:
        for _, row in df_fu.iterrows():
            rid = str(row.iloc[0]).strip()
            data = {}
            for i, col in enumerate(df_fu.columns):
                if i == 0:
                    continue
                val = row.iloc[i]
                if pd.notna(val):
                    data[normalize_col_name(str(col))] = str(val).strip()
            fu_lookup[rid] = data

    # ── Build respondent records ──────────────────────────────────────────────
    respondents = []
    seen_ids = set()

    pre_frames = []
    if df_pre is not None:
        pre_frames.append((df_pre, True))    # (df, is_matched)
    if df_prenon is not None:
        pre_frames.append((df_prenon, False))

    for df_src, is_matched_source in pre_frames:
        for _, row in df_src.iterrows():
            rid = str(row.iloc[0]).strip()
            if rid in seen_ids:
                continue
            seen_ids.add(rid)

            # Pre KQ responses
            pre_kq = {}
            for qid, col_idx in pre_mapping.kq_cols.items():
                val = row.iloc[col_idx]
                if pd.notna(val):
                    pre_kq[qid] = str(val).strip()

            # Pre Likert responses
            pre_likert = {}
            for col_idx, cm in pre_mapping.likert_cols.items():
                if cm.scale:
                    val = row.iloc[col_idx]
                    if pd.notna(val) and not is_opt_out(str(val)):
                        score = apply_scale(str(val).strip(), cm.scale)
                        if score is not None:
                            col_label = cm.col_name
                            pre_likert[col_label] = score

            # Post data from lookups
            has_post = rid in post_ids
            has_eval = rid in eval_ids

            r = Respondent(
                id=rid,
                vendor=vendor_name,
                has_pre=True,
                has_post=has_post,
                has_eval=has_eval,
                has_followup=rid in fu_ids,
                pre_kq=pre_kq,
                post_kq=post_kq_lookup.get(rid, {}),
                pre_likert=pre_likert,
                post_likert=eval_likert_lookup.get(rid, {}),
                eval_data=eval_other_lookup.get(rid, {}),
                followup_data=fu_lookup.get(rid, {}),
            )
            respondents.append(r)

    log.append(f"Nexus: built {len(respondents)} respondent records "
               f"({sum(1 for r in respondents if r.has_post)} with post, "
               f"{sum(1 for r in respondents if r.has_eval)} with eval)")

    return respondents
