-- Contact-form storage is server-only: browsers never receive a Supabase key.
-- Apply through the Supabase migration workflow, not the SQL editor by hand.

begin;

create extension if not exists pgcrypto;

create table if not exists public.contact_submissions (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(btrim(name)) > 0),
  email text not null check (char_length(btrim(email)) > 0),
  company text,
  created_at timestamptz not null default now()
);

create index if not exists contact_submissions_created_at_idx
  on public.contact_submissions (created_at desc);

alter table public.contact_submissions enable row level security;

revoke all on table public.contact_submissions from anon, authenticated;
grant select, insert on table public.contact_submissions to service_role;

commit;
