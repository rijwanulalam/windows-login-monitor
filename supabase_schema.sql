-- Run this once in Supabase: SQL Editor -> New query -> Run

create table if not exists login_event_counts (
    id            bigint generated always as identity primary key,
    machine_name  text        not null,   -- computer name, e.g. "RIJWAN-PC"
    event_id      integer     not null,   -- e.g. 4624
    event_name    text,                   -- e.g. "Successful logon"
    event_date    date        not null,   -- the day being counted
    count         integer     not null default 0,
    collected_at  timestamptz not null default now(),

    -- One row per machine + event + day. The collector's upsert relies on this.
    unique (machine_name, event_id, event_date)
);

-- Security: turn on Row Level Security.
-- The collector uses the service_role key (kept only on the Windows PC), which bypasses RLS.
-- The dashboard uses the anon key, which can only READ.
alter table login_event_counts enable row level security;

create policy "Dashboard can read counts"
    on login_event_counts
    for select
    to anon
    using (true);
