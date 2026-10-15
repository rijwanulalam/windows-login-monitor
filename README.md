# Windows Login Monitor

Reads login events from the Windows Security log, counts them per day per event ID,
saves the results to files and Supabase (against the machine name), and shows them
in a Streamlit dashboard with an event ID dropdown.

## How it flows

```
Security log ──► events_raw.csv ──► daily_counts.csv / .txt ──► chart_<id>.png
   (step 1)         (step 2 reads it back)    (step 3)            (step 4)
                                     │
                                     └──► Supabase (step 5) ──► dashboard.py
```

## Event IDs collected

| ID   | Meaning                          |
|------|----------------------------------|
| 4624 | Successful logon                 |
| 4625 | Failed logon                     |
| 4634 | Logoff                           |
| 4647 | User-initiated logoff            |
| 4648 | Logon with explicit credentials  |
| 4672 | Admin (special privileges) logon |
| 4740 | Account locked out               |
| 4800 | Workstation locked               |
| 4801 | Workstation unlocked             |

4800/4801 only appear if "Audit Other Logon/Logoff Events" is enabled
(`auditpol /set /subcategory:"Other Logon/Logoff Events" /success:enable /failure:enable`).

## Setup

1. **Supabase** – run `supabase_schema.sql` in the SQL Editor.
2. **Install** – `pip install -r requirements.txt`
3. **Keys** – copy `.env.example` to `.env`, add your URL and **service_role** key.
4. **Test once** – open an *Administrator* terminal and run `python collector.py`.
   Check the `output` folder.
5. **Task Scheduler** – edit the `PYTHON=` line in `run_collector.bat`
   (use `where python` to find it), then right-click `setup_task_scheduler.bat` →
   *Run as administrator*. It runs every hour as SYSTEM.
6. **Dashboard** – `streamlit run dashboard.py`

## Deploying the dashboard to Streamlit Cloud

Push to GitHub (`.env` and `output/` are git-ignored), deploy `dashboard.py`, and add
these to the app's Secrets – using the **anon** key, which is read-only thanks to RLS:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-anon-key"
```

## Useful commands

```bat
schtasks /Query /TN "WindowsLoginMonitor"    :: check the task
schtasks /Run   /TN "WindowsLoginMonitor"    :: run it now
schtasks /Delete /TN "WindowsLoginMonitor" /F :: remove it
```
