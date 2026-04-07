"""
parsers/exchange.py
───────────────────
Parse ExchangeCME Worksheet exports into Respondent records.

Format: single sheet 'Worksheet' with multi-row header:
  Row 0: Admin column headers (Activity, Email, Name, etc.)
  Row 1: Section markers — scan for PRE, POST, EVAL/EVALUATION, FOLLOW
  Row 2: Question text for each column
  Row 3+: Data rows

Key behaviors:
  - Section markers may appear in ANY order (EVAL before PRE in some programs)
  - A respondent record is created for every data row with ANY pre column non-null
  - has_post = True if any post section KQ column is non-null
  - has_eval = True if any eval section column is non-null
  - Temporal markers in POST section: 'WILL YOU NOW' = post-Likert
  - Temporal markers in EVAL section: 'ARE YOU NOW' = post-Likert
"""

from __future__ import annotations
import pandas as pd
from typing import Optional
from ..normalizer import normalize, normalize_col_name, is_opt_out
from ..column_mapper import map_columns
from ..scale_detector import apply_scale, detect_scale
from ..key_parser import ParsedKey
from ..models import Respondent

# Section marker strings to detect (normalized)
SECTION_MARKERS = {
    "pre": ["pre", "pre-test", "pretest"],
    "post": ["post", "post-test", "posttest"],
    "eval": ["evaluation", "eval", "post-activity"],
    "followup": ["follow-up", "follow up", "followup", "follow"],
}

POST_TEMPORAL = ["are you now", "will you now", "you now",
                 "after participating", "after completing"]
PRE_TEMPORAL  = ["are you currently", "do you currently", "currently"]


def _detect_sections(df_raw: pd.DataFrame) -> dict:
    """
    Scan all rows for section markers.
    Returns {section_name: start_col_index}.
    Handles any order of sections.
    """
    sections = {}

    # Scan every row (not just row 1) to be robust
    for row_idx in range(min(5, len(df_raw))):
        row = df_raw.iloc[row_idx]
        for col_idx, val in enumerate(row):
            if pd.isna(val):
                continue
            norm_val = normalize(str(val)).strip()
            for section, markers in SECTION_MARKERS.items():
                if norm_val in markers and section not in sections:
                    sections[section] = (row_idx, col_idx)

    return sections


def parse_exchange(
    filepath: str,
    parsed_key: ParsedKey,
    log: list[str],
    warnings: list[str],
    vendor_name: str = None,
) -> list[Respondent]:
    """
    Parse an ExchangeCME Worksheet file into Respondent records.
    """
    try:
        xl = pd.ExcelFile(filepath)
    except Exception as e:
        warnings.append(f"Cannot open Exchange file: {e}")
        return []

    # Find the worksheet
    ws_name = None
    for name in xl.sheet_names:
        if name.strip().lower() in ("worksheet", "data", "responses"):
            ws_name = name
            break
    if ws_name is None:
        ws_name = xl.sheet_names[0]  # Fall back to first sheet
        log.append(f"Exchange: no 'Worksheet' sheet found, using '{ws_name}'")

    df_raw = pd.read_excel(xl, sheet_name=ws_name, header=None)
    log.append(f"Exchange: sheet '{ws_name}', shape={df_raw.shape}")

    if vendor_name is None:
        # Derive vendor name from activity name in row 0
        try:
            activity = str(df_raw.iloc[1, 0]).strip()
            vendor_name = activity if activity not in ("nan", "") else "ExchangeCME"
        except Exception:
            vendor_name = "ExchangeCME"

    # ── Detect section boundaries ─────────────────────────────────────────────
    raw_sections = _detect_sections(df_raw)
    log.append(f"Exchange: sections detected: "
               f"{[(s, f'row={r},col={c}') for s,(r,c) in raw_sections.items()]}")

    if "pre" not in raw_sections and "post" not in raw_sections:
        warnings.append(
            "Exchange file: no PRE or POST section markers found. "
            "Verify row 2 contains 'PRE', 'POST', 'EVALUATION' markers."
        )

    # ── Find question text row and data start row ─────────────────────────────
    # Question text is in the row AFTER the last section marker row
    if raw_sections:
        marker_rows = [r for r, c in raw_sections.values()]
        question_row = max(marker_rows) + 1
    else:
        question_row = 2  # Default assumption

    data_start = question_row + 1
    log.append(f"Exchange: question_row={question_row}, data_start={data_start}")

    # ── Extract column ranges per section ─────────────────────────────────────
    # Sort sections by column index
    section_cols = sorted(
        [(s, c) for s, (r, c) in raw_sections.items()],
        key=lambda x: x[1]
    )
    # Build col ranges: section → (start_col, end_col)
    col_ranges = {}
    n_cols = df_raw.shape[1]
    for i, (section, start_col) in enumerate(section_cols):
        end_col = section_cols[i+1][1] if i+1 < len(section_cols) else n_cols
        col_ranges[section] = (start_col, end_col)
        log.append(f"Exchange: section '{section}' cols {start_col}–{end_col-1}")

    # Admin cols = everything before first section marker
    admin_end = section_cols[0][1] if section_cols else n_cols

    # ── Extract question text for each column ─────────────────────────────────
    q_texts = {}
    for col_idx in range(n_cols):
        val = df_raw.iloc[question_row, col_idx] if question_row < len(df_raw) else None
        if pd.notna(val) and str(val).strip() not in ("", "nan"):
            q_texts[col_idx] = normalize_col_name(str(val).strip())

    # ── Build section dataframes ──────────────────────────────────────────────
    data_rows = df_raw.iloc[data_start:].reset_index(drop=True)

    def section_df(section: str) -> Optional[pd.DataFrame]:
        if section not in col_ranges:
            return None
        start, end = col_ranges[section]
        sub = data_rows.iloc[:, start:end].copy()
        # Apply question text as column names
        new_cols = []
        for i, original_col in enumerate(range(start, end)):
            new_cols.append(q_texts.get(original_col, f"col_{original_col}"))
        sub.columns = new_cols
        return sub

    pre_df   = section_df("pre")
    post_df  = section_df("post")
    eval_df  = section_df("eval")
    fu_df    = section_df("followup")

    # ── Map pre KQ and Likert columns ─────────────────────────────────────────
    pre_mapping = None
    if pre_df is not None and len(data_rows) > 0:
        pre_mapping = map_columns(
            pre_df,
            knowledge_questions=parsed_key.knowledge_questions,
            sheet_name="Exchange_PRE",
            id_col_hint=-1,   # No ID in section
            section="pre",
        )
        log.extend([f"Exchange PRE: {line}" for line in pre_mapping.inference_log])
        warnings.extend(pre_mapping.warnings)

    # ── Map post KQ columns ───────────────────────────────────────────────────
    post_mapping = None
    if post_df is not None and len(data_rows) > 0:
        post_mapping = map_columns(
            post_df,
            knowledge_questions=parsed_key.knowledge_questions,
            sheet_name="Exchange_POST",
            id_col_hint=-1,
            section="post",
        )
        log.extend([f"Exchange POST: {line}" for line in post_mapping.inference_log])
        warnings.extend(post_mapping.warnings)

    # ── Detect post-Likert in POST and EVAL sections ──────────────────────────
    post_likert_map = {}   # {col_name: scale}

    for df_section, section_name in [(post_df, "POST"), (eval_df, "EVAL")]:
        if df_section is None:
            continue
        for col_name in df_section.columns:
            norm_col = col_name.lower()
            is_post_l = any(m in norm_col for m in POST_TEMPORAL)
            is_post_l = is_post_l or ("now" in norm_col and section_name == "EVAL")
            if not is_post_l:
                continue
            series = df_section[col_name].dropna()
            if len(series) == 0:
                continue
            scale = detect_scale(series.astype(str).unique().tolist())
            if scale:
                post_likert_map[col_name] = scale
                log.append(f"Exchange {section_name} post-Likert: "
                           f"'{col_name[:50]}' → {scale.family}")

    # ── Detect pre-Likert in PRE section ──────────────────────────────────────
    pre_likert_map = {}   # {col_name: scale}
    if pre_mapping:
        for col_idx, cm in pre_mapping.likert_cols.items():
            if cm.scale:
                pre_likert_map[cm.col_name] = cm.scale

    # ── Build respondent records ──────────────────────────────────────────────
    respondents = []

    # Admin columns: email or token as ID
    id_col_idx = None
    for i in range(min(15, admin_end)):
        col_name = normalize_col_name(str(df_raw.iloc[0, i])).lower() \
                   if 0 < len(df_raw) else ""
        if any(x in col_name for x in ["email", "token", "id"]):
            id_col_idx = i
            log.append(f"Exchange: ID from admin col[{i}] '{col_name}'")
            break
    if id_col_idx is None:
        id_col_idx = 1   # Default: email is usually col 1

    for row_idx, row in data_rows.iterrows():
        # Get ID
        rid_raw = row.iloc[id_col_idx] if id_col_idx < len(row) else f"exc_{row_idx}"
        rid = str(rid_raw).strip() if pd.notna(rid_raw) else f"exc_{row_idx}"

        # Pre KQ responses
        pre_kq = {}
        if pre_mapping and pre_df is not None:
            pre_row = pre_df.iloc[row_idx]
            for qid, col_idx in pre_mapping.kq_cols.items():
                val = pre_row.iloc[col_idx]
                if pd.notna(val) and str(val).strip() not in ("", "nan"):
                    pre_kq[qid] = str(val).strip()

        # Pre Likert
        pre_likert = {}
        if pre_df is not None:
            pre_row = pre_df.iloc[row_idx]
            for col_name, scale in pre_likert_map.items():
                if col_name in pre_df.columns:
                    val = pre_row[col_name]
                    if pd.notna(val) and not is_opt_out(str(val)):
                        score = apply_scale(str(val).strip(), scale)
                        if score is not None:
                            pre_likert[col_name] = score

        # Post KQ responses
        post_kq = {}
        if post_mapping and post_df is not None:
            post_row = post_df.iloc[row_idx]
            for qid, col_idx in post_mapping.kq_cols.items():
                val = post_row.iloc[col_idx]
                if pd.notna(val) and str(val).strip() not in ("", "nan"):
                    post_kq[qid] = str(val).strip()

        # Post Likert
        post_likert = {}
        for df_src in [post_df, eval_df]:
            if df_src is None:
                continue
            src_row = df_src.iloc[row_idx]
            for col_name, scale in post_likert_map.items():
                if col_name in df_src.columns:
                    val = src_row[col_name]
                    if pd.notna(val) and not is_opt_out(str(val)):
                        score = apply_scale(str(val).strip(), scale)
                        if score is not None:
                            post_likert[col_name] = score

        # Eval data
        eval_data = {}
        if eval_df is not None:
            eval_row = eval_df.iloc[row_idx]
            for col_name in eval_df.columns:
                val = eval_row[col_name]
                if pd.notna(val):
                    eval_data[col_name] = str(val).strip()

        # Determine has_pre / has_post / has_eval
        has_pre = len(pre_kq) > 0 or len(pre_likert) > 0
        if not has_pre:
            # Check any pre column non-null
            if pre_df is not None:
                has_pre = pre_df.iloc[row_idx].notna().any()

        has_post = len(post_kq) > 0
        has_eval = len(eval_data) > 0

        if not has_pre and not has_post and not has_eval:
            continue  # Skip completely empty rows

        r = Respondent(
            id=rid,
            vendor=vendor_name,
            has_pre=has_pre,
            has_post=has_post,
            has_eval=has_eval,
            has_followup=False,
            pre_kq=pre_kq,
            post_kq=post_kq,
            pre_likert=pre_likert,
            post_likert=post_likert,
            eval_data=eval_data,
        )
        respondents.append(r)

    log.append(f"Exchange '{vendor_name}': built {len(respondents)} records "
               f"({sum(1 for r in respondents if r.has_post)} with post, "
               f"{sum(1 for r in respondents if r.has_eval)} with eval)")

    return respondents
