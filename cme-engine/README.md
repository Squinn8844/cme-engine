# Integritas CME Outcomes Engine

A format-agnostic Python engine for processing CME/CE outcomes data across any vendor platform.

## Core Design Principles

- **Never assume column positions** — questions found by scanning for correct answer values
- **Never assume scale labels** — Likert scales detected dynamically from response data  
- **Never assume file structure** — formats auto-detected from sheet names and content
- **Always validate** — post-computation consistency checks flag anomalies before reporting
- **Always audit** — every inference decision logged for full transparency

## Supported Formats

| Format | Detection Method |
|--------|-----------------|
| **Nexus** | Sheets: Pre, PreNon, Post, Eval, Follow Up |
| **ExchangeCME** | Single Worksheet sheet with PRE/POST/EVAL section markers |
| **Unknown** | Auto-detect → try both parsers → prompt user if stuck |

## Quick Start

### Install

```bash
git clone https://github.com/your-org/cme-engine
cd cme-engine
pip install -r requirements.txt
```

### Run Streamlit App

```bash
streamlit run app/app.py
```

### Use Engine Directly

```python
from engine import process

result = process(
    key_file="path/to/LAI_KEY.xlsx",
    data_files=["path/to/NEXUS.xlsx", "path/to/Exchange.xlsx"],
    program_name="LAI PrEP Journey 2025"
)

print(f"Total learners: {result.total}")
print(f"With post-test: {result.with_post}")

for kq in result.kq_results:
    print(f"{kq.question_text[:60]}: {kq.pre_pct:.1%} → {kq.post_pct:.1%}")

for lr in result.likert_results:
    if lr.has_post:
        print(f"{lr.label[:50]}: {lr.pre_mean:.2f} → {lr.post_mean:.2f} (+{lr.delta:.2f})")
```

## Project Structure

```
cme-engine/
├── engine/
│   ├── __init__.py          # process() entry point
│   ├── version.py           # Version string
│   ├── normalizer.py        # String normalization (encoding, dashes, entities)
│   ├── scale_detector.py    # Dynamic Likert scale detection
│   ├── key_parser.py        # Answer key → Question objects
│   ├── column_mapper.py     # Correct-answer-first column discovery
│   ├── models.py            # Respondent, KQResult, LikertResult, etc.
│   ├── analytics.py         # Unified respondent pool computation
│   ├── validator.py         # Post-computation consistency checks
│   └── parsers/
│       ├── nexus.py         # Nexus format parser
│       ├── exchange.py      # ExchangeCME format parser
│       └── auto_detect.py   # Unknown format inference
├── tests/
│   ├── test_normalizer.py
│   ├── test_scale_detector.py
│   ├── test_integration_laipep.py   # Full regression test
│   ├── test_integration_il33.py     # Full regression test
│   ├── anonymize_fixtures.py        # PII stripper for test fixtures
│   └── fixtures/                    # Anonymized test data
├── app/
│   └── app.py               # Streamlit UI
├── config/
│   └── program_overrides.yaml
├── .github/workflows/
│   └── test.yml             # CI pipeline
└── requirements.txt
```

## Running Tests

```bash
# Unit tests only (no fixtures needed)
pytest tests/test_normalizer.py tests/test_scale_detector.py -v

# Integration tests (requires anonymized fixture files)
pytest tests/ -v

# With coverage
pytest tests/test_normalizer.py tests/test_scale_detector.py \
  --cov=engine --cov-report=html
```

## Creating Test Fixtures

Strip PII from real data files before committing:

```bash
python tests/anonymize_fixtures.py \
    --input_dir /path/to/real/data \
    --output_dir tests/fixtures/LAIPrEP \
    --program laipep
```

## Adding a New Vendor Format

1. Create `engine/parsers/your_format.py` implementing the same interface as `nexus.py`
2. Add format detection logic to `engine/parsers/auto_detect.py`
3. Write an integration test in `tests/test_integration_yourformat.py`
4. Add fixture files to `tests/fixtures/YourFormat/`

## Key File Format

The answer key Excel file requires:

| Column | Required | Description |
|--------|----------|-------------|
| `Question text` | ✓ | Full question text |
| `Score` | ✓ | 1 = knowledge (scored), 0 = Likert/demographic |
| `Answers` | ✓ | First answer option |
| `Sort` | ✓ | Display order |
| `Unnamed: 8`–`Unnamed: 12` | — | Additional answer options |

**Critical rule:** Only prefix the correct answer with `* ` (asterisk + space) for `Score=1` rows.
Never mark `Score=0` answers — the engine will treat them as correct answers.

## Supported Likert Scales

| Family | Labels |
|--------|--------|
| CONFIDENCE_A | Not at all confident → Very confident |
| CONFIDENCE_B | Not confident → Extremely confident (IL33 style) |
| FAMILIARITY_A | Not at all familiar → Very familiar |
| FAMILIARITY_B | Not familiar → Extremely familiar |
| FREQUENCY_A | Never → 100% of the time |
| FREQUENCY_B | Never → Always |
| AGREEMENT_A | Strongly Disagree → Strongly Agree |
| LIKELIHOOD_A | Not likely → Extremely likely |

Add new scale variants to `engine/scale_detector.py → SCALE_LIBRARY`.

## Deployment to Streamlit Cloud

1. Push repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo
4. Set main file path: `app/app.py`
5. Deploy

Auto-deploys on every push to `main`.

## Validation Flags

The engine checks for these issues after every computation:

| Flag | Meaning |
|------|---------|
| All post KQ counts identical | Possible post column reuse bug |
| Vendor excluded from KQ pool | One vendor not contributing to combined |
| Likert post n > eval count | Post Likert reading from wrong sheet |
| Likert mean out of 1–5 range | Scale mapping error |
| Vendor count sum ≠ total | Possible duplicate IDs |
| No matched pre/post | Post sheet IDs don't match Pre sheet IDs |

## License

Proprietary — Integritas Group. All rights reserved.
