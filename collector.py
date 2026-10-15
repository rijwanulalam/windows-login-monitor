"""
collector.py
============
Reads login-related events from the Windows Security log and then:

  Step 1  Writes every matching event to          output/events_raw.csv
  Step 2  Reads that file back and counts events per day, per event ID
  Step 3  Writes the daily totals to              output/daily_counts.csv
                                           and    output/daily_counts.txt  ("Day 1 | 28/09 => 60")
  Step 4  Draws one bar chart per event ID        output/chart_<event_id>.png
  Step 5  Uploads the daily totals to Supabase, stored against this machine's name

Must run as Administrator (the Security log is protected).
Task Scheduler runs it automatically as SYSTEM - see setup_task_scheduler.bat.
"""

import csv
import os
import socket
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw charts to files only - there is no screen under Task Scheduler
import matplotlib.pyplot as plt
import pywintypes
import win32evtlog  # part of pywin32
from dotenv import load_dotenv
from supabase import create_client


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# Always work relative to this file, NOT the current folder.
# Task Scheduler starts programs in C:\Windows\System32, so relative paths would break.
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

RAW_FILE = OUTPUT_DIR / "events_raw.csv"
DAILY_CSV = OUTPUT_DIR / "daily_counts.csv"
DAILY_TXT = OUTPUT_DIR / "daily_counts.txt"

# How many days back to read each run.
DAYS_TO_READ = 7

# The login-related event IDs we care about, with a plain-English name for each.
LOGIN_EVENTS = {
    4624: "Successful logon",
    4625: "Failed logon",
    4634: "Logoff",
    4647: "User-initiated logoff",
    4648: "Logon with explicit credentials",
    4672: "Admin (special privileges) logon",
    4740: "Account locked out",
    4800: "Workstation locked",
    4801: "Workstation unlocked",
}

# Supabase table that stores the daily totals.
SUPABASE_TABLE = "login_event_counts"

# The computer's name - this is the "key" each row is saved against in Supabase.
MACHINE_NAME = socket.gethostname()

# Windows event XML lives inside this namespace; ElementTree needs it to find tags.
NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}


# ---------------------------------------------------------------------------
# Step 1: read events from the Windows Security log
# ---------------------------------------------------------------------------

def build_query(days: int) -> str:
    """
    Build an XPath filter so Windows only hands us the events we want.
    Filtering inside Windows is far faster than reading the whole log in Python.
    """
    id_filter = " or ".join(f"EventID={event_id}" for event_id in LOGIN_EVENTS)
    milliseconds = days * 24 * 60 * 60 * 1000
    return f"*[System[({id_filter}) and TimeCreated[timediff(@SystemTime) <= {milliseconds}]]]"


def parse_event(xml_text: str) -> dict:
    """Turn one event's XML into a simple dictionary."""
    root = ET.fromstring(xml_text)

    event_id = int(root.find("e:System/e:EventID", NS).text)

    # Windows stores the time in UTC, like "2026-09-28T03:15:42.1234567Z".
    # We keep the first 19 characters and convert to this PC's local time,
    # so "28/09" means 28/09 in Sydney, not in London.
    raw_time = root.find("e:System/e:TimeCreated", NS).get("SystemTime")
    utc_time = datetime.strptime(raw_time[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    local_time = utc_time.astimezone()

    # Collect the named fields from <EventData> (TargetUserName, LogonType, ...).
    data_fields = {
        item.get("Name"): (item.text or "")
        for item in root.findall("e:EventData/e:Data", NS)
    }
    # Most login events name the account in TargetUserName; 4672 uses SubjectUserName.
    user = data_fields.get("TargetUserName") or data_fields.get("SubjectUserName") or ""

    return {
        "timestamp": local_time.strftime("%Y-%m-%d %H:%M:%S"),
        "date": local_time.strftime("%Y-%m-%d"),
        "event_id": event_id,
        "event_name": LOGIN_EVENTS.get(event_id, "Unknown"),
        "user": user,
    }


def read_events(days: int) -> list[dict]:
    """Read all matching events from the last `days` days, newest first."""
    query = build_query(days)
    flags = win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection

    try:
        handle = win32evtlog.EvtQuery("Security", flags, query)
    except pywintypes.error as error:
        print(f"Could not open the Security log: {error}")
        print("Run this script as Administrator (or via the scheduled task, which runs as SYSTEM).")
        sys.exit(1)

    events = []
    while True:
        batch = win32evtlog.EvtNext(handle, 200)  # read 200 events at a time
        if not batch:  # empty batch = no more events
            break
        for event_handle in batch:
            xml_text = win32evtlog.EvtRender(event_handle, win32evtlog.EvtRenderEventXml)
            events.append(parse_event(xml_text))

    return events


def write_raw_file(events: list[dict]) -> None:
    """Write every event we found to a CSV - one row per event."""
    columns = ["timestamp", "date", "event_id", "event_name", "user"]
    with open(RAW_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(events)
    print(f"Step 1: wrote {len(events)} events to {RAW_FILE.name}")


# ---------------------------------------------------------------------------
# Step 2: read the raw file back and count per day
# ---------------------------------------------------------------------------

def count_per_day(days: int) -> dict[int, dict[date, int]]:
    """
    Read events_raw.csv and build:
        { event_id: { day: count, ... }, ... }

    Every day in the window gets an entry, even if the count is 0,
    so the bar charts never have gaps.
    """
    today = date.today()
    all_days = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]  # oldest first

    # Start every event ID / day at zero.
    counts = {event_id: {day: 0 for day in all_days} for event_id in LOGIN_EVENTS}

    with open(RAW_FILE, newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            event_id = int(row["event_id"])
            day = date.fromisoformat(row["date"])
            if event_id in counts and day in counts[event_id]:
                counts[event_id][day] += 1

    print(f"Step 2: counted events across {days} days")
    return counts


# ---------------------------------------------------------------------------
# Step 3: write the daily totals to new files
# ---------------------------------------------------------------------------

def write_daily_files(counts: dict[int, dict[date, int]]) -> None:
    """Write the per-day totals as a CSV (for tools) and a TXT (for humans)."""

    # CSV version
    with open(DAILY_CSV, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["event_id", "event_name", "day_number", "date", "day_label", "count"])
        for event_id, per_day in counts.items():
            for day_number, (day, count) in enumerate(per_day.items(), start=1):
                writer.writerow([event_id, LOGIN_EVENTS[event_id], day_number,
                                 day.isoformat(), day.strftime("%d/%m"), count])

    # Human-readable version:  Day 1 | 28/09 => 60
    lines = [f"Machine: {MACHINE_NAME}",
             f"Generated: {datetime.now():%d/%m/%Y %H:%M}", ""]
    for event_id, per_day in counts.items():
        lines.append(f"{event_id} - {LOGIN_EVENTS[event_id]}  (total {sum(per_day.values())})")
        for day_number, (day, count) in enumerate(per_day.items(), start=1):
            lines.append(f"  Day {day_number} | {day:%d/%m} => {count}")
        lines.append("")

    DAILY_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Step 3: wrote {DAILY_CSV.name} and {DAILY_TXT.name}")


# ---------------------------------------------------------------------------
# Step 4: bar charts
# ---------------------------------------------------------------------------

def draw_charts(counts: dict[int, dict[date, int]]) -> None:
    """Save one bar chart per event ID."""
    for event_id, per_day in counts.items():
        labels = [day.strftime("%d/%m") for day in per_day]
        values = list(per_day.values())

        fig, ax = plt.subplots(figsize=(8, 4))
        bars = ax.bar(labels, values, color="#2b6cb0")
        ax.bar_label(bars)  # print the number on top of each bar
        ax.set_title(f"{event_id} - {LOGIN_EVENTS[event_id]}  ({MACHINE_NAME})")
        ax.set_xlabel("Day")
        ax.set_ylabel("Number of events")
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / f"chart_{event_id}.png")
        plt.close(fig)  # free memory - important when drawing many charts

    print(f"Step 4: saved {len(counts)} charts")


# ---------------------------------------------------------------------------
# Step 5: upload to Supabase
# ---------------------------------------------------------------------------

def upload_to_supabase(counts: dict[int, dict[date, int]]) -> None:
    """
    Save one row per (machine, event ID, day).

    We use upsert: if the row already exists it is updated, otherwise inserted.
    That means running the task every hour is safe - today's number just
    gets refreshed instead of duplicated.
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("Step 5: skipped - SUPABASE_URL / SUPABASE_KEY missing from .env")
        return

    collected_at = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "machine_name": MACHINE_NAME,
            "event_id": event_id,
            "event_name": LOGIN_EVENTS[event_id],
            "event_date": day.isoformat(),
            "count": count,
            "collected_at": collected_at,
        }
        for event_id, per_day in counts.items()
        for day, count in per_day.items()
    ]

    client = create_client(url, key)
    client.table(SUPABASE_TABLE).upsert(rows, on_conflict="machine_name,event_id,event_date").execute()
    print(f"Step 5: uploaded {len(rows)} rows to Supabase for {MACHINE_NAME}")


# ---------------------------------------------------------------------------
# Run everything in order
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv(BASE_DIR / ".env")  # load keys from the .env next to this file
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"--- Run started {datetime.now():%d/%m/%Y %H:%M:%S} on {MACHINE_NAME} ---")

    events = read_events(DAYS_TO_READ)      # Step 1 (read)
    write_raw_file(events)                  # Step 1 (write)
    counts = count_per_day(DAYS_TO_READ)    # Step 2 (reads the file back)
    write_daily_files(counts)               # Step 3
    draw_charts(counts)                     # Step 4
    upload_to_supabase(counts)              # Step 5

    print("--- Done ---\n")


if __name__ == "__main__":
    main()
