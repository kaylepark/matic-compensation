"""Matic compensation benchmarking tool — Streamlit UI.

Run with:  .venv/bin/streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from comp_engine.internal import load_team_comp
from comp_engine.levels import FUNCTIONS, LEVELS, infer_function, infer_level
from comp_engine.market import fetch_market
from comp_engine.peers import PEERS
from comp_engine.recommend import recommend

st.set_page_config(page_title="Matic Comp Benchmarking", page_icon="🤖", layout="wide")

st.title("Matic — Offer Comp Benchmarking")
st.caption(
    "Suggests base / equity / sign-on for a candidate by blending your current team's "
    "comp, live peer job postings, and Series-A robotics heuristics. "
    "Equity & sign-on lean on internal data and heuristics — treat as guidance, not market truth."
)

# ---------------- Sidebar: team comp data ----------------
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
            st.success(f"Loaded {len(team_df)} rows.")
            with st.expander("Preview"):
                st.dataframe(team_df, use_container_width=True)
        except ValueError as e:
            st.error(str(e))

    st.divider()
    st.header("2. Live market data")
    use_market = st.checkbox("Pull live peer job postings", value=False)
    st.caption(f"{len(PEERS)} peer companies configured (Greenhouse / Lever).")

# ---------------- Main: candidate ----------------
st.header("Candidate")
c1, c2, c3 = st.columns(3)
with c1:
    title = st.text_input("Title", "Senior Software Engineer")
    yoe = st.number_input("Years of experience", min_value=0.0, max_value=40.0, value=7.0, step=0.5)
with c2:
    location = st.text_input("Location (hiring for)", "San Francisco CA")
    fn_options = ["(auto-detect)"] + FUNCTIONS
    fn_choice = st.selectbox("Function", fn_options, index=0)
with c3:
    level_options = ["(auto-detect)"] + [lv.code for lv in LEVELS]
    level_choice = st.selectbox("Level", level_options, index=0)
    background = st.text_area("Background notes (optional)", height=80,
                              placeholder="Prior companies, standout signals, competing offers…")

function = None if fn_choice == "(auto-detect)" else fn_choice
level_override = None if level_choice == "(auto-detect)" else level_choice

if st.button("Generate recommendation", type="primary"):
    market = None
    if use_market:
        kw = [w.lower() for w in title.split() if len(w) > 2]
        loc_filter = location.split()[0] if location else None
        with st.spinner(f"Pulling postings from {len(PEERS)} peers…"):
            market = fetch_market(kw, location_filter=loc_filter)
        st.toast(f"Market: {len(market.postings)} matching postings, "
                 f"{len(market.with_salary)} with salary.")

    rec = recommend(
        title=title,
        years_experience=yoe,
        location=location,
        function=function,
        team_df=team_df,
        market=market,
        level_override=level_override,
    )

    st.divider()
    top = st.columns([1, 1, 1, 1])
    top[0].metric("Level", f"{rec.level_code} · {rec.level_name}")
    top[1].metric("Base target", f"${rec.base_target:,}", f"${rec.base_low:,}–${rec.base_high:,}")
    if rec.equity_grant_value:
        top[2].metric("Equity (grant value)", f"${rec.equity_grant_value:,}")
    else:
        top[2].metric("Equity (ownership)", f"{rec.equity_pct_low:.2f}–{rec.equity_pct_high:.2f}%")
    top[3].metric("Sign-on", f"${rec.signon_target:,}")

    st.info(f"**Confidence:** {rec.confidence}")

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

    if market and market.with_salary:
        st.subheader("Peer postings with disclosed ranges")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Company": p.company,
                        "Title": p.title,
                        "Location": p.location,
                        "Low": f"${p.salary_low:,}",
                        "High": f"${p.salary_high:,}",
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
