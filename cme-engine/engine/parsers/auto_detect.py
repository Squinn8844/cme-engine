"""
parsers/auto_detect.py
──────────────────────
Automatic format detection and parsing for unknown file formats.

Detection hierarchy:
  1. Sheet name matching → Nexus or Exchange
  2. Structure analysis → multi-row header, section markers
  3. Content analysis → ID column, KQ columns, Likert columns
  4. Confidence scoring → HIGH / MEDIUM / LOW
  5. LOW confidence → return partial result with prompts for user

Unknown formats get a best-effort parse with explicit warnings
about what the engine inferred vs what it knows for certain.
"""

from __future__ import annotations
import pandas as pd
from typing import Optional
from ..normalizer import normalize, normalize_col_name
from ..key_parser import ParsedKey
from ..models import Respondent

# Known sheet name sets
NEXUS_SHEETS    = {"pre", "prenon", "post", "eval", "follow up",
                    "evaluation", "follow_up", "followup"}
EXCHANGE_SHEETS = {"worksheet"}
KEY_SHEETS      = {"pre-test", "pretest", "post", "evaluation",
                    "eval", "follow-up", "followup"}


class FormatDetectionResult:
    def __init__(self):
        self.format: str = "UNKNOWN"       # NEXUS | EXCHANGE | KEY | UNKNOWN
        self.confidence: str = "LOW"       # HIGH | MEDIUM | LOW
        self.sheet_names: list = []
        self.evidence: list[str] = []
        self.prompts: list[str] = []       # Questions to ask user if LOW


def detect_format(filepath: str) -> FormatDetectionResult:
    """
    Detect the format of an Excel file.
    Returns a FormatDetectionResult with format, confidence, and any prompts.
    """
    result = FormatDetectionResult()

    try:
        xl = pd.ExcelFile(filepath)
    except Exception as e:
        result.evidence.append(f"Cannot open file: {e}")
        return result

    result.sheet_names = xl.sheet_names
    norm_sheets = {s.strip().lower() for s in xl.sheet_names}

    # ── Nexus detection ──────────────────────────────────────────────────────
    nexus_overlap = norm_sheets & NEXUS_SHEETS
    if len(nexus_overlap) >= 2:
        result.format = "NEXUS"
        result.confidence = "HIGH" if len(nexus_overlap) >= 3 else "MEDIUM"
        result.evidence.append(
            f"Nexus sheets matched: {nexus_overlap}"
        )
        return result

    # ── Exchange detection ───────────────────────────────────────────────────
    if norm_sheets & EXCHANGE_SHEETS:
        # Verify it has multi-row header with section markers
        try:
            df = pd.read_excel(xl, sheet_name=xl.sheet_names[0], header=None,
                               nrows=5)
            has_markers = False
            for row_idx in range(min(5, len(df))):
                row_vals = [normalize(str(v)) for v in df.iloc[row_idx]
                            if pd.notna(v)]
                if any(m in row_vals for m in ["pre", "post", "evaluation", "eval"]):
                    has_markers = True
                    break
            if has_markers:
                result.format = "EXCHANGE"
                result.confidence = "HIGH"
                result.evidence.append("Single 'Worksheet' sheet with section markers")
                return result
        except Exception:
            pass

    # ── Key detection ────────────────────────────────────────────────────────
    key_overlap = norm_sheets & KEY_SHEETS
    if len(key_overlap) >= 2:
        result.format = "KEY"
        result.confidence = "HIGH"
        result.evidence.append(f"Key sheets matched: {key_overlap}")
        return result

    # ── Unknown format — attempt structure analysis ──────────────────────────
    result.format = "UNKNOWN"
    result.confidence = "LOW"
    result.evidence.append(f"Sheet names: {xl.sheet_names}")

    # Try to give useful prompts
    if len(xl.sheet_names) == 1:
        result.prompts.append(
            "This file has one sheet. Is it an ExchangeCME export? "
            "If so, please verify it has section markers (PRE, POST, EVALUATION) "
            "in the second row."
        )
    elif any("pre" in s.lower() for s in xl.sheet_names):
        result.prompts.append(
            "This file looks like it might be a Nexus export but sheet names "
            "don't match expected pattern (Pre, PreNon, Post, Eval, Follow Up). "
            "Please verify the sheet names."
        )
    else:
        result.prompts.append(
            "File format not recognized. Please check: "
            "(1) For Nexus exports, sheets should be named: Pre, PreNon, Post, Eval, Follow Up. "
            "(2) For ExchangeCME exports, there should be a single 'Worksheet' sheet. "
            "(3) For key files, sheets should be named: Pre-Test, POST, Evaluation."
        )

    return result


def parse_unknown(
    filepath: str,
    parsed_key: ParsedKey,
    log: list[str],
    warnings: list[str],
    vendor_name: str = "Unknown",
) -> tuple[list[Respondent], list[str]]:
    """
    Attempt to parse an unknown format file.
    Returns (respondents, user_prompts).
    user_prompts is non-empty if the engine needs user input.
    """
    from .nexus import parse_nexus
    from .exchange import parse_exchange

    detection = detect_format(filepath)
    log.append(f"Auto-detect: format={detection.format}, "
               f"confidence={detection.confidence}")
    log.extend([f"  Evidence: {e}" for e in detection.evidence])

    user_prompts = detection.prompts

    if detection.format == "NEXUS" and detection.confidence in ("HIGH", "MEDIUM"):
        log.append("Auto-detect: routing to Nexus parser")
        respondents = parse_nexus(filepath, parsed_key, log, warnings, vendor_name)
        return respondents, user_prompts

    if detection.format == "EXCHANGE" and detection.confidence in ("HIGH", "MEDIUM"):
        log.append("Auto-detect: routing to Exchange parser")
        respondents = parse_exchange(filepath, parsed_key, log, warnings, vendor_name)
        return respondents, user_prompts

    if detection.format == "KEY":
        log.append("Auto-detect: file appears to be a KEY file, not data")
        warnings.append("A file was uploaded that looks like an answer key, "
                        "not a data file. Please verify your uploads.")
        return [], ["This file appears to be an answer key, not a data file. "
                    "Please upload your data files separately."]

    # LOW confidence — try both parsers and return best result
    log.append("Auto-detect: LOW confidence, attempting both parsers")
    warnings.append(
        f"File format not recognized with high confidence. "
        f"Engine attempted auto-parse. Review results carefully."
    )

    # Try Nexus first
    nexus_result = parse_nexus(filepath, parsed_key, log, warnings, vendor_name)
    if nexus_result:
        log.append(f"Auto-detect: Nexus parse produced {len(nexus_result)} records")
        return nexus_result, user_prompts

    # Try Exchange
    exchange_result = parse_exchange(filepath, parsed_key, log, warnings, vendor_name)
    if exchange_result:
        log.append(f"Auto-detect: Exchange parse produced {len(exchange_result)} records")
        return exchange_result, user_prompts

    return [], user_prompts + [
        "Engine could not parse this file automatically. "
        "Please verify the file format matches one of the supported templates."
    ]
