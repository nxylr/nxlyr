-- 008 r3: durable record of what the bot promised on a call.
-- A row means "the bot took this booking or callback request".
-- alert_sent_at set means "a human alert was delivered".
-- Both are needed before the bot may say it is booked or passed on.
-- superseded_at set means "a later booking on the same call replaced this one";
-- the row is kept for the record. null means live.
-- Server-only: browsers never receive a Supabase key. Run in the Supabase SQL Editor.
-- Does not touch the existing public.commitments table.

begin;

create extension if not exists pgcrypto;

create table if not exists public.call_commitments (
  id               uuid primary key default gen_random_uuid(),
  created_at       timestamptz not null default now(),
  kind             text not null default 'site_visit'
                     check (kind in ('site_visit', 'callback_request')),
  project_slug     text not null,                      -- 'nxlyr-demo' (bot.py KB_PROJECT_SLUG)
  call_sid         text not null,                      -- Exotel CallSid; the only call identifier the bot has
  visit_date       date,                               -- IST calendar date the caller asked for (site_visit only)
  visit_time       time,                               -- IST wall-clock time the caller asked for (site_visit only)
  notes            text check (notes is null or char_length(notes) <= 500),
                                                       -- site_visit: caller's note; callback_request: reason and summary
  phone_normalized text check (phone_normalized is null or phone_normalized ~ '^\+91[6-9][0-9]{9}$'),
                                                       -- the lead's number, or null if the code could not tell which Exotel field held it
  alert_sent_at    timestamptz,                        -- null = row exists but nobody was told (the caller was told "not confirmed" / "couldn't pass that on")
  superseded_at    timestamptz,                        -- null = live; set when a later booking on the same call replaced this one
  constraint site_visit_needs_when
    check (kind <> 'site_visit' or (visit_date is not null and visit_time is not null)),
  constraint superseded_only_site_visit
    check (superseded_at is null or kind = 'site_visit'),
  -- a retry of the same booking updates this row instead of adding a second one
  constraint call_commitments_retry_key unique (call_sid, kind, visit_date, visit_time)
);

create index if not exists call_commitments_created_at_idx
  on public.call_commitments (created_at desc);

create index if not exists call_commitments_unalerted_idx
  on public.call_commitments (created_at desc)
  where alert_sent_at is null and superseded_at is null;

alter table public.call_commitments enable row level security;

revoke all on table public.call_commitments from anon, authenticated;
grant select, insert, update on table public.call_commitments to service_role;

commit;
