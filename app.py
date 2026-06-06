"""Matic compensation benchmarking tool — Streamlit UI.

Run with:  .venv/bin/streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from comp_engine.export import to_excel, to_html
from comp_engine.h1b import query_h1b
from comp_engine.internal import load_team_comp
from comp_engine.levels import FUNCTIONS, LEVELS
from comp_engine.market import fetch_market
from comp_engine.peers import PEERS
from comp_engine.recommend import recommend
from comp_engine.resume import fetch_url as _fetch_url


@st.cache_data(show_spinner=False, ttl=300)
def cached_fetch_url(url: str):
    """Cache the URL fetch so LinkedIn doesn't get hammered on every Streamlit re-run."""
    return _fetch_url(url)

st.set_page_config(page_title="Matic Comp Benchmarking", page_icon="🤖", layout="wide")

st.title("Matic — Offer Comp Benchmarking")
st.caption(
    "Suggests base / equity / sign-on for a candidate by blending your current team's "
    "comp, live peer job postings, BLS wage data, H1B/LCA filings, and Series-A "
    "robotics heuristics. Equity & sign-on lean on internal data and heuristics — "
    "treat as guidance, not market truth."
)

# ---------------- Sidebar: data sources ----------------
with st.sidebar:
    st.header("1. Current team comp")
    st.write("Upload an anonymized CSV. Download the template if you need the format.")
    with open("data/team_comp_template.csv", "rb") as f:
        st.download_button("⬇️ Download CSV template", f, "team_comp_template.csv", "text/csv")
    uploaded = st.file_uploader("Upload team_comp.csv", type=["csv"])

    team_df = None
    if uploaded is not None:
        try:
            team_df = load_team_comp(uploaded)
            # Show what data columns were found.
            has_equity = (
                ("equity_grant_value" in team_df.columns and team_df["equity_grant_value"].notna().any())
                or ("equity_pct" in team_df.columns and team_df["equity_pct"].notna().any())
            )
            has_signon = "sign_on_bonus" in team_df.columns and team_df["sign_on_bonus"].notna().any()
            status = f"Loaded {len(team_df)} rows"
            status += f" · equity: {'✓' if has_equity else '✗'}"
            status += f" · sign-on: {'✓' if has_signon else '✗'}"
            st.success(status)
            levels_in_csv = sorted(team_df["level"].unique().tolist())
            st.caption(f"Columns: {', '.join(team_df.columns.tolist())}")
            st.caption(f"Levels in CSV: {', '.join(str(l) for l in levels_in_csv)}")
            with st.expander("Preview"):
                st.dataframe(team_df, use_container_width=True)
        except ValueError as e:
            st.error(str(e))

    st.divider()
    st.header("2. Market data sources")
    st.caption(f"**Live peer postings:** {len(PEERS)} companies (Greenhouse / Lever / Ashby)")
    st.caption("**H1B/LCA filings:** DOL disclosure data (first run downloads ~200MB, then cached)")
    st.caption("**BLS wage floor:** bundled government data (no download needed)")
    st.caption("All three sources are included automatically in every recommendation.")

# ---------------- LinkedIn / Resume URL ----------------
st.header("Candidate")

resume_data = None
profile_url = st.text_input(
    "LinkedIn or resume URL (optional)",
    placeholder="https://linkedin.com/in/janedoe  or  https://example.com/resume.pdf",
    help="Paste a LinkedIn profile URL or a link to a resume. We'll extract name, title, experience, and prior companies to pre-fill the form below.",
)

if profile_url:
    with st.spinner("Fetching profile…"):
        resume_data = cached_fetch_url(profile_url)

    if resume_data.source == "error":
        st.warning(resume_data.raw_text)
    else:
        # Show whatever we could extract — some fields will be None, that's fine.
        has_any = any([resume_data.name, resume_data.title, resume_data.location,
                       resume_data.companies, resume_data.skills, resume_data.education])
        if has_any:
            cols = st.columns([1, 1, 1])
            with cols[0]:
                if resume_data.name:
                    st.markdown(f"**Name:** {resume_data.name}")
                if resume_data.title:
                    st.markdown(f"**Detected title:** {resume_data.title}")
                if resume_data.years_experience:
                    st.markdown(f"**~Years experience:** {resume_data.years_experience:.0f}")
            with cols[1]:
                if resume_data.location:
                    st.markdown(f"**Location:** {resume_data.location}")
                if resume_data.companies:
                    st.markdown(f"**Prior companies:** {', '.join(resume_data.companies[:6])}")
            with cols[2]:
                if resume_data.skills:
                    st.markdown(f"**Skills:** {', '.join(resume_data.skills[:10])}")
                if resume_data.education:
                    st.markdown(f"**Education:** {resume_data.education[0]}")
        elif resume_data.source == "linkedin":
            st.caption(
                "LinkedIn limited what we could pull automatically. "
                "Fill in the fields below manually."
            )

        if resume_data.raw_text and len(resume_data.raw_text) > 200:
            with st.expander("Full extracted text"):
                st.text(resume_data.raw_text[:5000])
                if len(resume_data.raw_text) > 5000:
                    st.caption(f"(Showing first 5,000 of {len(resume_data.raw_text):,} characters)")

# Use resume data as defaults. Leave blank when we can't confidently extract.
default_title = resume_data.title if (resume_data and resume_data.title) else ""
default_yoe = resume_data.years_experience if (resume_data and resume_data.years_experience) else 0.0
default_location = resume_data.location if (resume_data and resume_data.location) else ""
default_name = resume_data.name if (resume_data and resume_data.name) else ""
default_background = ""
if resume_data:
    parts = []
    if resume_data.companies:
        parts.append(f"Prior companies: {', '.join(resume_data.companies)}")
    if resume_data.education:
        parts.append(f"Education: {resume_data.education[0]}")
    if resume_data.skills:
        parts.append(f"Key skills: {', '.join(resume_data.skills[:8])}")
    default_background = "\n".join(parts)

# ---------------- Candidate form ----------------
c1, c2, c3 = st.columns(3)
with c1:
    title = st.text_input("Title", default_title)
    yoe = st.number_input("Years of experience", min_value=0.0, max_value=40.0,
                           value=default_yoe, step=0.5)
with c2:
    location = st.text_input("Location (hiring for)", default_location)
    fn_options = ["(auto-detect)"] + FUNCTIONS
    fn_choice = st.selectbox("Function", fn_options, index=0)
with c3:
    level_options = ["(auto-detect)"] + [lv.code for lv in LEVELS]
    level_choice = st.selectbox("Level", level_options, index=0)
    candidate_name = st.text_input("Candidate name (for export)", default_name)
    background = st.text_area("Background notes (optional)", value=default_background,
                              height=80,
                              placeholder="Prior companies, standout signals, competing offers…")

function = None if fn_choice == "(auto-detect)" else fn_choice
level_override = None if level_choice == "(auto-detect)" else level_choice

if st.button("Generate recommendation", type="primary"):

    # --- Fetch live data sources (always included) ---
    from comp_engine.market import clean_title_for_search
    search_phrase = clean_title_for_search(title)
    loc_filter = location.split()[0] if location else None
    with st.spinner(f"Pulling postings from {len(PEERS)} peers…"):
        market = fetch_market(search_phrase, location_filter=loc_filter, candidate_yoe=yoe)
    st.toast(f"Market: {len(market.postings)} matching postings, "
             f"{len(market.with_salary)} with salary.")

    # Use the full title as a single phrase so "Mechanical Engineer" doesn't
    # match every "Software Engineer" filing just because "Engineer" is shared.
    kw_h1b = [title.strip()]
    with st.spinner("Querying H1B/LCA data (first run may take 1-2 min to download)…"):
        h1b = query_h1b(title_keywords=kw_h1b, location=location)
    if h1b.error:
        st.warning(f"H1B lookup issue: {h1b.error}")
    else:
        st.toast(f"H1B: {h1b.n_total} filings matched.")

    # --- Generate recommendation ---
    rec = recommend(
        title=title,
        years_experience=yoe,
        location=location,
        function=function,
        team_df=team_df,
        market=market,
        h1b=h1b,
        level_override=level_override,
    )

    # --- Display results ---
    st.divider()
    top = st.columns([1, 1, 1, 1])
    top[0].metric("Level", f"{rec.level_code} · {rec.level_name}")
    top[1].metric("Base target", f"${rec.base_target:,}", f"${rec.base_low:,}–${rec.base_high:,}")
    if rec.equity_grant_value:
        top[2].metric("Equity (grant value)", f"${rec.equity_grant_value:,}")
    elif rec.internal_equity_pct_median is not None:
        top[2].metric(
            "Equity (ownership)",
            f"{rec.internal_equity_pct_median:.3f}%",
            f"{rec.internal_equity_pct_p25:.3f}–{rec.internal_equity_pct_p75:.3f}%",
        )
    else:
        top[2].metric("Equity (ownership)", f"{rec.equity_pct_low:.2f}–{rec.equity_pct_high:.2f}%")
    top[3].metric("Sign-on", f"${rec.signon_target:,}")

    st.info(f"**Confidence:** {rec.confidence}")

    # --- Data sources summary ---
    src_parts = []
    if rec.internal_n:
        src_parts.append(f"{rec.internal_n} internal teammates")
    if rec.market_n:
        src_parts.append(f"{rec.market_n} peer postings")
    if rec.h1b_n:
        src_parts.append(f"{rec.h1b_n} H1B filings")
    if rec.bls_floor:
        src_parts.append("BLS wage floor")
    if src_parts:
        st.caption("Data sources: " + " · ".join(src_parts))

    # --- Reasoning + offer summary ---
    lcol, rcol = st.columns([3, 2])
    with lcol:
        st.subheader("How we got here")
        for r in rec.reasoning:
            st.markdown(f"- {r}")
    with rcol:
        st.subheader("Offer summary")
        st.dataframe(
            pd.DataFrame(
                {
                    "Component": ["Base (low)", "Base (target)", "Base (high)", "Sign-on"],
                    "Amount": [
                        f"${rec.base_low:,}",
                        f"${rec.base_target:,}",
                        f"${rec.base_high:,}",
                        f"${rec.signon_target:,}",
                    ],
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

        # --- Export buttons ---
        st.subheader("Export")
        xl_bytes = to_excel(rec, candidate_name)
        html_str = to_html(rec, candidate_name)
        ex1, ex2 = st.columns(2)
        with ex1:
            st.download_button(
                "📊 Download .xlsx",
                xl_bytes,
                f"offer_{candidate_name.replace(' ', '_').lower()}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with ex2:
            st.download_button(
                "📄 Download .html (print to PDF)",
                html_str,
                f"offer_{candidate_name.replace(' ', '_').lower()}.html",
                "text/html",
            )

    # --- Peer postings table ---
    if market and market.with_salary:
        st.subheader("Peer postings with disclosed ranges")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Company": p.company,
                        "Title": p.title,
                        "Match": {"exact": "✓ exact", "related": "~ related", "broad": "~ broad"}.get(p.match_type, "~"),
                        "Location": p.location,
                        "Low": f"${p.salary_low:,}",
                        "High": f"${p.salary_high:,}",
                        "YOE Req": f"{p.yoe_required}+" if p.yoe_required else "—",
                        "Link": p.url,
                    }
                    for p in market.with_salary
                ]
            ),
            hide_index=True,
            use_container_width=True,
            column_config={"Link": st.column_config.LinkColumn()},
        )
    if market and market.errors:
        with st.expander(f"Peers skipped ({len(market.errors)})"):
            st.write(", ".join(market.errors))

    # --- H1B detail table ---
    if h1b and h1b.records:
        st.subheader(f"H1B/LCA filings ({h1b.n_total} total)")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Employer": r.employer,
                        "Title": r.title,
                        "City": r.city,
                        "State": r.state,
                        "Wage": f"${r.wage_low:,}",
                    }
                    for r in h1b.records[:50]
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        if h1b.n_total > 50:
            st.caption(f"Showing first 50 of {h1b.n_total} records.")
