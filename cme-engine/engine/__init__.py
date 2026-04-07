"""
engine/__init__.py
──────────────────
Public API for the CME Outcomes Engine.

Usage:
    from engine import process

    result = process(
        key_file="path/to/key.xlsx",
        data_files=["path/to/nexus.xlsx", "path/to/exchange.xlsx"],
        program_name="LAI PrEP Journey"
    )
"""

from __future__ import annotations
import hashlib
import os
from typing import Optional

from .key_parser import parse_key
from .parsers.auto_detect import detect_format
from .parsers.nexus import parse_nexus
from .parsers.exchange import parse_exchange
from .parsers.auto_detect import parse_unknown
from .analytics import compute
from .validator import validate
from .models import AnalyticsResult
from .version import VERSION


def _file_hash(filepath: str) -> str:
    """Compute SHA-256 hash of a file for cache keying."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]  # First 16 chars sufficient for cache key


def process(
    key_file: str,
    data_files: list[str],
    program_name: str = "",
    vendor_name_overrides: dict = None,
) -> AnalyticsResult:
    """
    Process a CME program from raw data files.

    Args:
        key_file: path to answer key Excel file
        data_files: list of data file paths (Nexus, Exchange, or unknown)
        program_name: display name for the program
        vendor_name_overrides: {filepath: "Custom Vendor Name"}

    Returns:
        AnalyticsResult with all metrics, warnings, and audit trail
    """
    log: list[str] = [f"Engine v{VERSION} — processing '{program_name}'"]
    warnings: list[str] = []
    user_prompts: list[str] = []

    # ── Parse key file ────────────────────────────────────────────────────────
    if not os.path.exists(key_file):
        warnings.append(f"Key file not found: {key_file}. "
                        "Running in keyless mode — reduced accuracy.")
        from .key_parser import ParsedKey
        parsed_key = ParsedKey([], [], [], [], [], [], [])
    else:
        try:
            parsed_key = parse_key(key_file)
            log.append(f"Key: {len(parsed_key.knowledge_questions)} KQs, "
                       f"{len(parsed_key.all_questions)} total questions")
            warnings.extend(parsed_key.warnings)
        except Exception as e:
            warnings.append(f"Key parse error: {e}")
            from .key_parser import ParsedKey
            parsed_key = ParsedKey([], [], [], [], [], [], [warnings[-1]])

    # ── Compute file hashes ───────────────────────────────────────────────────
    file_hashes = {}
    if os.path.exists(key_file):
        file_hashes[os.path.basename(key_file)] = _file_hash(key_file)
    for fp in data_files:
        if os.path.exists(fp):
            file_hashes[os.path.basename(fp)] = _file_hash(fp)

    # ── Parse data files ──────────────────────────────────────────────────────
    all_respondents = []

    for filepath in data_files:
        if not os.path.exists(filepath):
            warnings.append(f"Data file not found: {filepath}")
            continue

        basename = os.path.basename(filepath)
        vendor_name = (vendor_name_overrides or {}).get(filepath, None)

        detection = detect_format(filepath)
        log.append(f"File '{basename}': detected as {detection.format} "
                   f"(confidence={detection.confidence})")

        if detection.format == "NEXUS":
            respondents = parse_nexus(
                filepath, parsed_key, log, warnings,
                vendor_name=vendor_name or "Nexus"
            )
        elif detection.format == "EXCHANGE":
            respondents = parse_exchange(
                filepath, parsed_key, log, warnings,
                vendor_name=vendor_name  # None = auto-detect from file
            )
        elif detection.format == "KEY":
            warnings.append(f"File '{basename}' appears to be a key file — "
                            "skipping as data file.")
            continue
        else:
            respondents, prompts = parse_unknown(
                filepath, parsed_key, log, warnings,
                vendor_name=vendor_name or basename
            )
            user_prompts.extend(prompts)

        all_respondents.extend(respondents)
        log.append(f"File '{basename}': {len(respondents)} respondents loaded")

    if not all_respondents:
        warnings.append("No respondents loaded from any data file.")

    log.append(f"Total respondents: {len(all_respondents)}")

    # ── Compute analytics ─────────────────────────────────────────────────────
    if not program_name:
        program_name = os.path.basename(data_files[0]) if data_files else "Unknown"

    result = compute(
        respondents=all_respondents,
        parsed_key=parsed_key,
        program_name=program_name,
        file_hashes=file_hashes,
    )

    # ── Validate ──────────────────────────────────────────────────────────────
    result = validate(result)

    # Merge logs
    result.inference_log = log + result.inference_log
    result.warnings = warnings + result.warnings

    # Store user prompts if any
    if user_prompts:
        result.warnings.extend(
            [f"❓ {p}" for p in user_prompts]
        )

    return result
