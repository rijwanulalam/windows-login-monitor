"""
dashboard.py
============
Streamlit dashboard for the Windows login monitor.

Pick a machine and an event ID from the dropdowns and the chart and table
update to show that event's count per day.

Run locally:   streamlit run dashboard.py
"""

import os

import altair as alt  # ships with Streamlit, no extra install needed
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

SUPABASE_TABLE = "login_event_counts"

st.set_page_config(page_title="Windows Login Monitor", page_icon="🔐", layout="wide")


# ---------------------------------------------------------------------------
# Connecting to Supabase
# ---------------------------------------------------------------------------

def get_setting(name: str) -> str | None:
    """
    Look for a setting in Streamlit secrets first (used on Streamlit Cloud),
    then fall back to a local .env file (used on your own PC).
    """
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass  # no secrets.toml file - that's fine when running locally
    return os.getenv(name)


@st.cache_resource
def get_client():
    """Create the Supabase client once and reuse it."""
    load_dotenv()
    url = get_setting("SUPABASE_URL")
    key = get_setting("SUPABASE_KEY")
    if not url or not key:
        st.error("Add SUPABASE_URL and SUPABASE_KEY to .env (local) or Streamlit secrets (cloud).")
        st.stop()
    return create_client(url, key)


@st.cache_data(ttl=300)  # re-download at most every 5 minutes
def load_data() -> pd.DataFrame:
    """Download all daily totals from Supabase into a DataFrame."""
    response = get_client().table(SUPABASE_TABLE).select("*").execute()
    data = pd.DataFrame(response.data)
    if not data.empty:
        data["event_date"] = pd.to_datetime(data["event_date"])
    return data


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("Windows login monitor")

data = load_data()

if data.empty:
    st.info("No data yet. Run collector.py on a Windows machine (as Administrator) to upload the first counts.")
    st.stop()

# --- Sidebar: the two dropdowns ------------------------------------------

with st.sidebar:
    st.header("Filters")

    machines = sorted(data["machine_name"].unique())
    machine = st.selectbox("Machine", machines)

    # Only offer event IDs that this machine actually has rows for.
    machine_data = data[data["machine_name"] == machine]
    event_names = (
        machine_data[["event_id", "event_name"]]
        .drop_duplicates()
        .set_index("event_id")["event_name"]
        .to_dict()
    )
    event_id = st.selectbox(
        "Event ID",
        sorted(event_names),
        format_func=lambda eid: f"{eid} – {event_names[eid]}",  # shows "4624 – Successful logon"
    )

    if st.button("Refresh data"):
        load_data.clear()
        st.rerun()

# --- Data for the selected machine + event ID -----------------------------

view = (
    machine_data[machine_data["event_id"] == event_id]
    .sort_values("event_date")
    .reset_index(drop=True)
)
view["day_label"] = view["event_date"].dt.strftime("%d/%m")
view["day_number"] = range(1, len(view) + 1)

st.subheader(f"{event_id} – {event_names[event_id]} on {machine}")

# --- Headline numbers -------------------------------------------------------

total = int(view["count"].sum())
busiest = view.loc[view["count"].idxmax()]
last_update = pd.to_datetime(view["collected_at"]).max()

col1, col2, col3 = st.columns(3)
col1.metric("Total in period", total)
col2.metric("Busiest day", f"{busiest['day_label']} ({int(busiest['count'])})")
col3.metric("Last collected", last_update.tz_convert("Australia/Sydney").strftime("%d/%m %H:%M"))

# --- Bar chart --------------------------------------------------------------
# sort=None keeps the days in date order (otherwise "01/10" would come before "28/09").

chart = (
    alt.Chart(view)
    .mark_bar()
    .encode(
        x=alt.X("day_label:N", sort=None, title="Day"),
        y=alt.Y("count:Q", title="Number of events"),
        tooltip=[alt.Tooltip("day_label", title="Day"), alt.Tooltip("count", title="Events")],
    )
)
labels = chart.mark_text(dy=-8).encode(text="count:Q")  # number above each bar
st.altair_chart(chart + labels, use_container_width=True)

# --- Table in the same "Day 1 | 28/09 => 60" style ------------------------

st.dataframe(
    view[["day_number", "day_label", "count"]].rename(
        columns={"day_number": "Day", "day_label": "Date", "count": "Events"}
    ),
    hide_index=True,
    use_container_width=True,
)
