"""
key_parser.py
─────────────
Parse an answer key Excel file into Question objects.
The key is the single source of truth for the engine.

Key file format:
  Sheets: Pre-Test (or Pre), POST (or Post), Evaluation, Follow-Up (optional)
  Columns: rowid, Questionnaire, Type, Score, Orientation, Sort,
           Question text, Answers, Unnamed:8..Unnamed:12 (answer options)

Rules:
  - Score == 1  → type='knowledge', correct_answer extracted (marked with '* ')
  - Score == 0  → type='likert' or 'demographic' or 'open'
  - correct_answer ONLY extracted for Score=1 rows — never for Score=0
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
from .normalizer import normalize, strip_correct_marker


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Question:
    id: str                          # Unique: "pre_q1", "post_q2", etc.
    rowid: Optional[int]             # Original rowid from key
    text: str                        # Full question text
    type: str                        # 'knowledge' | 'likert' | 'demographic' | 'open'
    correct_answer: Optional[str]    # Only for type='knowledge'
    correct_answer_norm: Optional[str]  # Normalized version for matching
    section: str                     # 'pre' | 'post' | 'eval' | 'followup'
    sort_order: int                  # Display order
    all_answers: list[str] = field(default_factory=list)  # All answer options

    def __repr__(self):
        ca = f" ✓={self.correct_answer[:30]}..." if self.correct_answer else ""
        return f"Question({self.id}, type={self.type}{ca})"


@dataclass
class ParsedKey:
    pre_questions: list[Question]
    post_questions: list[Question]
    eval_questions: list[Question]
    followup_questions: list[Question]
    all_questions: list[Question]
    knowledge_questions: list[Question]   # Score=1 only
    warnings: list[str]

    @property
    def correct_answers(self) -> list[str]:
        """All correct answer strings (normalized) for KQ column scanning."""
        return [q.correct_answer_norm for q in self.knowledge_questions
                if q.correct_answer_norm]


# ── Sheet name variants ───────────────────────────────────────────────────────

SECTION_ALIASES = {
    "pre": ["pre-test", "pre_test", "pretest", "pre"],
    "post": ["post", "post-test", "post_test", "posttest"],
    "eval": ["evaluation", "eval", "post-activity", "postactivity"],
    "followup": ["follow-up", "follow up", "followup", "follow_up", "fu"],
}


def _find_sheet(sheetnames: list[str], section: str) -> Optional[str]:
    """Find the sheet name for a given section, case-insensitive."""
    aliases = SECTION_ALIASES.get(section, [])
    for name in sheetnames:
        if name.strip().lower() in aliases:
            return name
    return None


# ── Answer extraction ─────────────────────────────────────────────────────────

def _extract_answers(row: pd.Series) -> tuple[Optional[str], list[str]]:
    """
    Extract all answer options and identify the correct one (marked with '* ').
    Returns (correct_answer_or_None, all_answers_list).

    CRITICAL: Only return a correct answer if Score == 1.
    Score == 0 questions may have '* ' on first option as display default —
    this is NOT a correct answer marker.
    """
    score = row.get("Score", 0)
    answers = []
    correct = None

    # Collect all answer columns
    answer_cols = ["Answers"] + [c for c in row.index
                                  if str(c).startswith("Unnamed:")]
    for col in answer_cols:
        val = row.get(col)
        if pd.isna(val) or str(val).strip() in ("", "nan", "NaN"):
            continue
        val_str = str(val).strip()
        answers.append(val_str)

        # Only extract correct answer for Score=1
        if score == 1 and val_str.startswith("* "):
            correct = strip_correct_marker(val_str)

    return correct, answers


# ── Question type inference ───────────────────────────────────────────────────

_OPEN_TYPES = {"text", "textarea", "open", "free"}

def _infer_type(row: pd.Series, correct_answer: Optional[str]) -> str:
    score = int(row.get("Score", 0))
    q_type = str(row.get("Type", "")).strip().lower()

    if score == 1:
        return "knowledge"
    if q_type in _OPEN_TYPES:
        return "open"

    # Check if answers look ordinal/gradated (Likert)
    answers_col = row.get("Answers", "")
    if pd.notna(answers_col):
        ans = str(answers_col).lower()
        likert_hints = ["confident", "familiar", "agree", "likely",
                        "frequently", "often", "never", "always",
                        "satisfied", "neutral"]
        if any(h in ans for h in likert_hints):
            return "likert"

    return "demographic"


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_key(filepath: str) -> ParsedKey:
    """
    Parse a key Excel file and return a ParsedKey object.

    Args:
        filepath: path to the key .xlsx file

    Returns:
        ParsedKey with all questions categorized
    """
    warnings = []

    try:
        xl = pd.ExcelFile(filepath)
    except Exception as e:
        raise ValueError(f"Cannot open key file: {e}")

    sheetnames = xl.sheet_names
    sections_found = []

    all_questions = []

    for section in ["pre", "post", "eval", "followup"]:
        sheet_name = _find_sheet(sheetnames, section)
        if sheet_name is None:
            if section in ("pre", "post"):
                warnings.append(f"Key missing {section} sheet — "
                                 f"searched: {SECTION_ALIASES[section]}")
            continue

        sections_found.append(section)

        try:
            df = pd.read_excel(filepath, sheet_name=sheet_name)
        except Exception as e:
            warnings.append(f"Cannot read key sheet '{sheet_name}': {e}")
            continue

        # Validate expected columns
        if "Score" not in df.columns:
            warnings.append(f"Key sheet '{sheet_name}' missing 'Score' column")
            continue
        if "Question text" not in df.columns:
            warnings.append(f"Key sheet '{sheet_name}' missing 'Question text' column")
            continue

        for idx, row in df.iterrows():
            q_text = str(row.get("Question text", "")).strip()
            if not q_text or q_text.lower() in ("nan", "none", ""):
                continue

            correct, all_answers = _extract_answers(row)
            q_type = _infer_type(row, correct)

            sort = int(row.get("Sort", idx))
            rowid = row.get("rowid", None)
            q_id = f"{section}_q{sort}"

            q = Question(
                id=q_id,
                rowid=int(rowid) if pd.notna(rowid) else None,
                text=q_text,
                type=q_type,
                correct_answer=correct,
                correct_answer_norm=normalize(correct) if correct else None,
                section=section,
                sort_order=sort,
                all_answers=all_answers,
            )
            all_questions.append(q)

    # Validate: at least some knowledge questions
    knowledge_qs = [q for q in all_questions if q.type == "knowledge"]
    if not knowledge_qs:
        warnings.append("No knowledge questions (Score=1) found in key file. "
                        "Verify Score column values.")

    # Check for duplicate correct answers (would cause ambiguous column mapping)
    ca_norms = [q.correct_answer_norm for q in knowledge_qs
                if q.correct_answer_norm]
    if len(ca_norms) != len(set(ca_norms)):
        warnings.append("Duplicate correct answers found in key — "
                        "column mapping may be ambiguous.")

    def get_section(s):
        return [q for q in all_questions if q.section == s]

    return ParsedKey(
        pre_questions=get_section("pre"),
        post_questions=get_section("post"),
        eval_questions=get_section("eval"),
        followup_questions=get_section("followup"),
        all_questions=all_questions,
        knowledge_questions=knowledge_qs,
        warnings=warnings,
    )
