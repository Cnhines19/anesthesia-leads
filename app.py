"""
Anesthesia Staffing Lead Finder — Streamlit UI
Run with: streamlit run app.py
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time

from lead_finder import find_leads, save_to_csv


st.set_page_config(
    page_title="Anesthesia Staffing Lead Finder",
    page_icon="🏥",
    layout="wide",
)

st.title("🏥 Anesthesia Staffing Lead Finder")
st.markdown(
    "Find and rank accredited surgery centers near a target zip code. "
    "Built for an MBA Generative AI course — uses an agentic Claude pipeline to "
    "discover facilities, verify accreditation across AAAHC / Joint Commission / QUAD A, "
    "detect existing anesthesia partnerships, and rank by lead warmth."
)

# ---------- Sidebar: Inputs ----------

with st.sidebar:
    st.header("Search Parameters")
    zip_code = st.text_input("Zip code", value="94507", max_chars=5)
    radius = st.selectbox("Radius (miles)", options=[5, 10, 15], index=1)

    st.divider()
    st.caption(
        "⏱ Expected runtime: 8–15 min depending on radius.\n\n"
        "💲 Each run uses Claude + web search; cost is typically $1–3 per zip."
    )

    run_button = st.button("🔎 Find Leads", type="primary", use_container_width=True)

# ---------- Sidebar: Prior runs ----------

with st.sidebar:
    st.divider()
    st.subheader("Previous results")
    if os.path.exists("results"):
        csv_files = sorted(
            [f for f in os.listdir("results") if f.endswith(".csv")],
            reverse=True
        )
        if csv_files:
            selected_prior = st.selectbox("Load a previous run", options=["(none)"] + csv_files)
        else:
            selected_prior = "(none)"
            st.caption("No prior results yet.")
    else:
        selected_prior = "(none)"

# ---------- Main panel ----------

def display_results(df: pd.DataFrame, zip_code: str, radius: int):
    """Render results table + summary cards."""
    if df.empty:
        st.warning("No facilities returned.")
        return

    total = len(df)
    confirmed = int((df["overall_confidence"] == "confirmed").sum()) if "overall_confidence" in df else 0
    likely = int((df["overall_confidence"] == "likely").sum()) if "overall_confidence" in df else 0
    flagged = 0
    if "has_anesthesia_director" in df:
        flagged += int((df["has_anesthesia_director"] == True).sum())
    if "has_named_anesthesia_group" in df:
        flagged += int((df["has_named_anesthesia_group"] == True).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total leads", total)
    c2.metric("Confirmed accreditation", confirmed)
    c3.metric("Likely accreditation", likely)
    c4.metric("Anesthesia signals", flagged, help="Facilities flagged with existing anesthesia director or group")

    st.divider()

    display_cols = [
        "warmth_score", "name", "city", "state", "distance_miles",
        "accreditation_summary", "services",
        "phone", "website",
        "has_anesthesia_director", "has_named_anesthesia_group",
        "anesthesia_partner_name", "anesthesia_quote",
        "evidence",
    ]
    available = [c for c in display_cols if c in df.columns]
    extra = [c for c in df.columns if c not in available]
    show_df = df[available + extra]

    st.dataframe(
        show_df,
        width="stretch",
        height=600,
        hide_index=True,
        column_config={
            "warmth_score": st.column_config.NumberColumn("Warmth", format="%d"),
            "distance_miles": st.column_config.NumberColumn("Miles", format="%.1f"),
            "website": st.column_config.LinkColumn("Website"),
            "has_anesthesia_director": st.column_config.CheckboxColumn("Anes Director?"),
            "has_named_anesthesia_group": st.column_config.CheckboxColumn("Anes Group?"),
        },
    )

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.download_button(
        label="⬇ Download CSV",
        data=csv_bytes,
        file_name=f"leads_{zip_code}_{radius}mi_{timestamp}.csv",
        mime="text/csv",
    )


# ---------- Action: new search (button click wins over a stale prior selection) ----------

if run_button:
    if not zip_code or len(zip_code) != 5 or not zip_code.isdigit():
        st.error("Please enter a valid 5-digit zip code.")
        st.stop()

    progress_box = st.empty()
    with progress_box.container():
        st.info(
            f"🔎 Running 5-stage agent pipeline on **{zip_code}** within **{radius} miles**. "
            "Watch your Terminal for live progress (stages 1, 1.5, 3, 2, 4). "
            "Stay on this tab — when the run finishes the results will appear below."
        )

    start = time.time()
    try:
        leads = find_leads(zip_code, radius)
    except Exception as e:
        st.error(f"Pipeline failed: {e}")
        st.stop()

    elapsed = time.time() - start
    progress_box.empty()

    save_to_csv(leads, zip_code, radius)

    st.success(f"✅ Done in {elapsed/60:.1f} minutes — found {len(leads)} facilities.")

    df = pd.DataFrame(leads)
    if "warmth_score" in df:
        df = df.sort_values("warmth_score", ascending=False, na_position="last")
    display_results(df, zip_code, radius)

elif selected_prior != "(none)":
    df = pd.read_csv(f"results/{selected_prior}")
    st.info(f"Showing previously saved results: `{selected_prior}`")
    display_results(df, zip_code, radius)

else:
    st.markdown(
        """
        ### How to use
        1. Enter a target zip code (e.g., 94507, 75205, 92647)
        2. Choose a search radius
        3. Click **Find Leads**
        4. Wait while the agent runs through 5 stages
        5. Sort by Warmth, export to CSV, or load a previous run

        ### What you'll get
        - A ranked list of nearby surgery centers
        - Accreditation status across all three major bodies (AAAHC, Joint Commission, QUAD A)
        - Detected anesthesia partnerships (with the exact quote from the website for human review)
        - A 0–100 warmth score so the hottest leads sit at the top
        """
    )
    