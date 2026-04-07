"""
app.py
──────
Integritas CME Outcomes Harmonizer
Streamlit Cloud entry point.

Architecture:
  - Upload files → engine.process() → AnalyticsResult
  - All computation in engine module, never in UI layer
  - Session state keyed by file hashes (no state bleed between programs)
"""

import streamlit as st
import os
import sys
import tempfile
import hashlib
from pathlib import Path

# Add engine to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import process
from engine.version import VERSION, ENGINE_NAME

st.set_page_config(
    page_title="CME Outcomes Harmonizer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        border-left: 4px solid #2E75B6;
        margin-bottom: 8px;
        cursor: pointer;
    }
    .metric-card:hover { background: #e8f0fe; }
    .vendor-tag {
        background: #2E75B6;
        color: white;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 12px;
        margin-right: 4px;
    }
    .flag-warning {
        background: #fff3cd;
        border-left: 4px solid #ffc107;
        padding: 8px 12px;
        border-radius: 4px;
        margin: 4px 0;
    }
    .flag-error {
        background: #f8d7da;
        border-left: 4px solid #dc3545;
        padding: 8px 12px;
        border-radius: 4px;
        margin: 4px 0;
    }
    .audit-mono {
        font-family: 'Courier New', monospace;
        font-size: 13px;
        background: #f8f9fa;
        padding: 12px;
        border-radius: 4px;
        white-space: pre-wrap;
    }
</style>
""", unsafe_allow_html=True)


def _save_upload(uploaded_file) -> str:
    """Save an uploaded file to a temp location and return the path."""
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(uploaded_file.read())
        return f.name


def _session_key(file_paths: list[str]) -> str:
    """Generate a cache key from file contents."""
    combined = b"".join(
        open(p, "rb").read() for p in file_paths if os.path.exists(p)
    )
    return hashlib.sha256(combined).hexdigest()[:16]


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://via.placeholder.com/200x60?text=Integritas", width=200)
    st.markdown(f"**{ENGINE_NAME}**  \nv{VERSION}")
    st.divider()

    st.markdown("### Upload Files")
    key_file    = st.file_uploader("📋 Answer Key (.xlsx)", type=["xlsx"],
                                    key="key_upload")
    data_files  = st.file_uploader("📂 Data Files (.xlsx)", type=["xlsx"],
                                    accept_multiple_files=True, key="data_upload")

    st.divider()
    program_name = st.text_input("Program Name", placeholder="e.g. LAI PrEP Journey 2025")

    run_btn   = st.button("▶ Run Analysis", type="primary", use_container_width=True)
    clear_btn = st.button("🗑 Clear & Reset", use_container_width=True)

    if clear_btn:
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.divider()
    st.markdown("##### Quick Guide")
    st.markdown("""
- Upload your **answer key** first
- Upload **1+ data files** (Nexus + Exchange)
- Engine auto-detects format
- Click **Run Analysis**
- Click any metric for full audit detail
    """)


# ── Main content ──────────────────────────────────────────────────────────────
st.title("📊 CME Outcomes Harmonizer")

if not run_btn and "result" not in st.session_state:
    st.info(
        "👈 Upload your answer key and data files in the sidebar, "
        "then click **Run Analysis**."
    )
    st.markdown("""
    #### Supported formats
    | Format | Detection |
    |--------|-----------|
    | **Nexus** | Sheets: Pre, PreNon, Post, Eval, Follow Up |
    | **ExchangeCME** | Single 'Worksheet' sheet with section markers |
    | **Unknown** | Auto-detected — engine tries both parsers |

    #### What you get
    - CIRCLE framework metrics with full audit trail
    - Knowledge gains (pre/post) with per-vendor breakdown
    - Competence shifts (Likert) with dynamic scale detection
    - Evaluation metrics, behavior changes, barriers
    - Downloadable PDF report + Excel audit workbook
    """)
    st.stop()

# ── Run engine ────────────────────────────────────────────────────────────────
if run_btn:
    if not data_files:
        st.error("Please upload at least one data file.")
        st.stop()

    with st.spinner("Processing..."):
        # Save files
        temp_paths = []
        key_path = None

        if key_file:
            key_path = _save_upload(key_file)

        for df in data_files:
            temp_paths.append(_save_upload(df))

        # Check cache
        all_paths = ([key_path] if key_path else []) + temp_paths
        cache_key = _session_key(all_paths)

        if cache_key != st.session_state.get("cache_key"):
            result = process(
                key_file=key_path or "",
                data_files=temp_paths,
                program_name=program_name or "",
            )
            st.session_state["result"]    = result
            st.session_state["cache_key"] = cache_key
        else:
            result = st.session_state["result"]

result = st.session_state.get("result")
if not result:
    st.stop()

# ── Validation flags ──────────────────────────────────────────────────────────
if result.validation_flags:
    with st.expander(f"⚠ {len(result.validation_flags)} Validation Flag(s)", expanded=True):
        for flag in result.validation_flags:
            st.markdown(f'<div class="flag-warning">{flag}</div>', unsafe_allow_html=True)

if result.warnings:
    with st.expander(f"ℹ {len(result.warnings)} Warning(s)"):
        for w in result.warnings:
            st.markdown(f'<div class="flag-warning">{w}</div>', unsafe_allow_html=True)

# ── Program header ────────────────────────────────────────────────────────────
st.markdown(f"## {result.program_name}")
vendor_html = " ".join(f'<span class="vendor-tag">{v}</span>'
                        for v in result.vendors.keys())
st.markdown(vendor_html, unsafe_allow_html=True)
st.caption(f"Computed {result.computed_at[:10]} · Engine v{result.engine_version}")

st.divider()

# ── CIRCLE metrics row ────────────────────────────────────────────────────────
st.markdown("### CIRCLE Framework")
cols = st.columns(5)
circle_metrics = [
    ("Total Learners",     result.total,           "n"),
    ("With Post-Test",     result.with_post,        "n"),
    ("With Evaluation",    result.with_eval,         "n"),
    ("Follow-Up",          result.with_followup,    "n"),
    ("Completion Rate",
     f"{result.with_post/result.total*100:.1f}%" if result.total > 0 else "—",
     "%"),
]
for col, (label, value, unit) in zip(cols, circle_metrics):
    with col:
        st.metric(label, value)

st.divider()

# ── Knowledge Gains ───────────────────────────────────────────────────────────
st.markdown("### Knowledge Gains — Pre vs Post")

if not result.kq_results:
    st.warning("No knowledge question results computed.")
else:
    for kq in result.kq_results:
        with st.expander(
            f"**{kq.question_text[:90]}{'...' if len(kq.question_text)>90 else ''}**  "
            f"{'↑ +' if kq.gain_pp and kq.gain_pp > 0 else ''}"
            f"{abs(kq.gain_pp*100):.0f}pp" if kq.gain_pp else "",
            expanded=False
        ):
            # Summary row
            c1, c2, c3 = st.columns(3)
            c1.metric("Pre %", f"{kq.pre_pct*100:.1f}%" if kq.pre_pct else "—",
                      delta=None)
            c2.metric("Post %", f"{kq.post_pct*100:.1f}%" if kq.post_pct else "—")
            c3.metric("Gain", f"+{kq.gain_pp*100:.0f}pp" if kq.gain_pp else "—")

            # What it means
            st.markdown("**What it measures**")
            st.markdown(
                "Percentage of learners who selected the correct answer "
                "before (PRE) and after (POST) the activity. "
                "Measures Knowledge (Moore Level 2)."
            )

            # Calculation detail
            st.markdown("**Actual Calculation**")
            calc_text = ""
            if kq.pre_pct is not None:
                calc_text += (f"PRE: {kq.pre_correct} correct ÷ {kq.pre_n} responses "
                              f"= {kq.pre_pct*100:.4f}% → rounds to {kq.pre_pct*100:.0f}%\n")
            if kq.post_pct is not None:
                calc_text += (f"POST: {kq.post_correct} correct ÷ {kq.post_n} responses "
                              f"= {kq.post_pct*100:.4f}% → rounds to {kq.post_pct*100:.0f}%\n")
            if kq.gain_pp is not None:
                calc_text += f"Δ = {kq.post_pct*100:.1f}% − {kq.pre_pct*100:.1f}% = {kq.gain_pp*100:+.0f}pp\n"
            calc_text += f"✓ Correct answer: {kq.correct_answer}"
            st.code(calc_text, language=None)

            # Source breakdown
            st.markdown("**Data Source Breakdown**")
            breakdown_rows = []
            for b in kq.vendor_breakdown:
                breakdown_rows.append({
                    "Source": b["vendor"],
                    "Pre Resp": b["pre_n"],
                    "Pre %✓": f"{b['pre_pct']*100:.1f}%" if b["pre_pct"] else "—",
                    "Post Resp": b["post_n"],
                    "Post %✓": f"{b['post_pct']*100:.1f}%" if b["post_pct"] else "—",
                    "Δ (pp)": (f"{(b['post_pct']-b['pre_pct'])*100:+.0f}pp"
                               if b.get("post_pct") and b.get("pre_pct") else "—"),
                })
            if breakdown_rows:
                import pandas as pd
                st.dataframe(pd.DataFrame(breakdown_rows), hide_index=True,
                             use_container_width=True)

st.divider()

# ── Competence Shifts ─────────────────────────────────────────────────────────
st.markdown("### Competence Shifts (Likert 1–5)")

likert_with_post = [l for l in result.likert_results if l.has_post]
likert_pre_only  = [l for l in result.likert_results if not l.has_post]

if likert_with_post:
    for lr in likert_with_post:
        with st.expander(
            f"**{lr.label[:70]}**  "
            f"{lr.pre_mean:.2f} → {lr.post_mean:.2f}  "
            f"(+{lr.delta:.2f})" if lr.delta else f"**{lr.label[:70]}**"
        ):
            c1, c2, c3 = st.columns(3)
            c1.metric("Pre Mean", f"{lr.pre_mean:.2f}" if lr.pre_mean else "—",
                      help=f"n={lr.pre_n}")
            c2.metric("Post Mean", f"{lr.post_mean:.2f}" if lr.post_mean else "—",
                      help=f"n={lr.post_n}")
            c3.metric("Delta", f"+{lr.delta:.2f}" if lr.delta else "—")

            st.markdown("**Actual Calculation**")
            calc = ""
            if lr.pre_mean:
                calc += f"Pre mean: {lr.pre_sum:.1f} ÷ {lr.pre_n} responses = {lr.pre_mean:.4f}\n"
            if lr.post_mean:
                calc += f"Post mean: {lr.post_sum:.1f} ÷ {lr.post_n} responses = {lr.post_mean:.4f}\n"
            if lr.delta:
                calc += f"Delta = Post − Pre = {lr.delta:+.4f} pts\nScale: 1 = lowest, 5 = highest"
            st.code(calc, language=None)

            if lr.vendor_breakdown:
                st.markdown("**Data Source Breakdown**")
                import pandas as pd
                rows = []
                for b in lr.vendor_breakdown:
                    rows.append({
                        "Source": b["vendor"],
                        "Pre n": b["pre_n"],
                        "Pre Sum": b.get("pre_sum", "—"),
                        "Pre Mean": f"{b['pre_mean']:.2f}" if b.get("pre_mean") else "—",
                        "Post n": b["post_n"],
                        "Post Mean": f"{b['post_mean']:.2f}" if b.get("post_mean") else "—",
                    })
                st.dataframe(pd.DataFrame(rows), hide_index=True,
                             use_container_width=True)

if likert_pre_only:
    st.markdown("#### Baseline Measures (Pre Only)")
    for lr in likert_pre_only:
        st.markdown(
            f"**{lr.label[:70]}** — Pre mean: {lr.pre_mean:.2f} (n={lr.pre_n})"
        )

st.divider()

# ── Eval metrics ──────────────────────────────────────────────────────────────
st.markdown("### Evaluation Outcomes")
er = result.eval_result
if er:
    cols = st.columns(4)
    cols[0].metric("Intent to Change",
                   f"{er.intent_pct*100:.0f}%" if er.intent_pct else "—",
                   help=f"{er.intent_yes}/{er.intent_denom}")
    cols[1].metric("Would Recommend",
                   f"{er.recommend_pct*100:.0f}%" if er.recommend_pct else "—",
                   help=f"{er.recommend_yes}/{er.recommend_denom}")
    cols[2].metric("Bias-Free",
                   f"{er.bias_free_pct*100:.0f}%" if er.bias_free_pct else "—",
                   help=f"{er.bias_free_yes}/{er.bias_free_denom}")
    cols[3].metric("Content New",
                   f"{er.content_new_pct:.0f}%" if er.content_new_pct else "—",
                   help=f"n={er.content_new_n}")

st.divider()

# ── Processing log ────────────────────────────────────────────────────────────
with st.expander("🔍 Processing Log", expanded=False):
    st.markdown('<div class="audit-mono">' +
                "\n".join(result.inference_log) + "</div>",
                unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.caption(f"Integritas CME Outcomes Engine v{VERSION} · "
           f"File hashes: {result.file_hashes}")
