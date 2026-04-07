"""
normalizer.py
─────────────
Normalize any string before comparison.
Handles every encoding issue observed across all three programs:
  - En-dash / em-dash variants (U+2013, U+2014, mojibake â€", â\x80\x93)
  - Curly quotes → straight quotes
  - HTML entities
  - UTF-8 mojibake sequences
  - Trailing/leading whitespace
  - Collapsed internal whitespace
  - Excel .1 duplicate column suffix
"""

import re
import html


# ── Opt-out phrases ──────────────────────────────────────────────────────────
# Responses matching these should be excluded from Likert numeric pooling.
OPT_OUT_PATTERNS = [
    r"i do not manage patients",
    r"i do not have contact",
    r"i do not provide care",
    r"not applicable",
    r"i am not engaged",
    r"does not apply",
    r"n/a",
]

_OPT_OUT_RE = re.compile(
    "|".join(OPT_OUT_PATTERNS), re.IGNORECASE
)


def normalize(s: str) -> str:
    """
    Normalize a string for comparison.
    Apply this to BOTH sides before any equality check.
    """
    if s is None:
        return ""
    s = str(s)

    # 1. Decode HTML entities (&amp; &lt; &nbsp; etc)
    s = html.unescape(s)

    # 2. Decode common UTF-8 mojibake sequences
    #    These appear when UTF-8 bytes are misread as Latin-1
    mojibake = [
        ("\u00e2\u0080\u0093", "-"),   # en-dash mojibake
        ("\u00e2\u0080\u0094", "-"),   # em-dash mojibake
        ("\u00e2\u0080\x93",   "-"),   # en-dash mojibake variant
        ("\u00e2\u0080\x94",   "-"),   # em-dash mojibake variant
        ("\u00e2\u0080\x98",   "'"),   # left single quote mojibake
        ("\u00e2\u0080\x99",   "'"),   # right single quote mojibake
        ("\u00e2\u0080\x9c",   '"'),   # left double quote mojibake
        ("\u00e2\u0080\x9d",   '"'),   # right double quote mojibake
        ("\u00c3\u00a9",       "e"),   # e-acute mojibake
        ("\u00c3\u00a8",       "e"),   # e-grave mojibake
        ("\u00c3\u00bc",       "u"),   # u-umlaut mojibake
        ("\u00c2\u00b5",       "u"),   # micro sign mojibake
        ("\u00e2\u0089\u00a5", ">="),  # ≥ mojibake
        ("\u00e2\u0089\u00a4", "<="),  # ≤ mojibake
    ]
    for bad, good in mojibake:
        s = s.replace(bad, good)

    # 3. Normalize all dash variants to plain hyphen
    s = s.replace("\u2013", "-")   # en-dash
    s = s.replace("\u2014", "-")   # em-dash
    s = s.replace("\u2012", "-")   # figure dash
    s = s.replace("\u2015", "-")   # horizontal bar
    s = s.replace("\u00ad", "-")   # soft hyphen

    # 4. Normalize quote variants to straight quotes
    s = s.replace("\u2018", "'").replace("\u2019", "'")   # curly single
    s = s.replace("\u201c", '"').replace("\u201d", '"')   # curly double
    s = s.replace("\u00ab", '"').replace("\u00bb", '"')   # guillemets

    # 5. Normalize whitespace
    s = s.strip()
    s = re.sub(r"\s+", " ", s)

    # 6. Lowercase for comparison
    s = s.lower()

    return s


def normalize_col_name(col: str) -> str:
    """
    Normalize a column header name.
    Strips Excel's .1 .2 etc duplicate suffixes.
    """
    col = str(col).strip()
    col = re.sub(r"\._x000d_\n", " ", col)   # Excel carriage return encoding
    col = re.sub(r"\s+", " ", col)
    col = re.sub(r"\.\d+$", "", col)          # Remove .1 .2 suffix
    return col.strip()


def is_opt_out(s: str) -> bool:
    """
    Return True if this response value is an opt-out
    (should be excluded from Likert numeric pooling).
    """
    if not s or str(s).strip().lower() in ("", "nan", "none"):
        return False
    return bool(_OPT_OUT_RE.search(str(s)))


def strip_correct_marker(s: str) -> str:
    """
    Remove the leading '* ' marker from a correct answer string.
    '* Ask the patient...' → 'Ask the patient...'
    """
    s = str(s).strip()
    if s.startswith("* "):
        return s[2:].strip()
    if s.startswith("*"):
        return s[1:].strip()
    return s


def answers_match(a: str, b: str) -> bool:
    """
    Return True if two answer strings match after normalization.
    """
    return normalize(a) == normalize(b)
