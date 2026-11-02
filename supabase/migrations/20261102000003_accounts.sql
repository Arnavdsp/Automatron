-- Accounts: anyone can sign up through Supabase Auth, and each person can see only
-- their own profile and their own sign-in history.
--
-- Credentials stay in auth.users, which Supabase manages and the Data API never
-- exposes; passwords are hashed by the auth server and never reach these tables.

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text not null default ''
    check (char_length(display_name) <= 80 and display_name !~ '[[:cntrl:]<>]'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- The profile is created by the database at signup, from the name the person
-- gave, with control characters and angle brackets stripped. Nobody inserts one
-- directly, so nobody can create a profile for someone else.
create function private.create_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    left(regexp_replace(coalesce(new.raw_user_meta_data ->> 'display_name', ''),
                        '[[:cntrl:]<>]', '', 'g'), 80)
  );
  return new;
end;
$$;

revoke all on function private.create_profile() from public, anon, authenticated;

create trigger on_auth_user_created_profile
  after insert on auth.users
  for each row execute function private.create_profile();

-- A record of each sign-in, readable by the person who signed in. The client
-- address is stored only as a keyed hash: enough to notice a sign-in from somewhere
-- new, not enough to recover where. Rows go when the account does.
create table public.sign_in_events (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  method text not null check (method in ('password', 'sign_up', 'link')),
  user_agent text not null default '' check (char_length(user_agent) <= 200),
  address_hash text not null check (address_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now()
);

create index sign_in_events_user_created_idx on public.sign_in_events (user_id, created_at desc);

revoke all on public.profiles, public.sign_in_events from anon, authenticated;
grant select, update (display_name, updated_at) on public.profiles to authenticated;
-- Insert and read only: a person cannot edit or erase their own history, and so
-- cannot hide a sign-in they did not make.
grant select, insert on public.sign_in_events to authenticated;

alter table public.profiles enable row level security;
alter table public.profiles force row level security;
alter table public.sign_in_events enable row level security;
alter table public.sign_in_events force row level security;

create policy "people read their own profile" on public.profiles
  for select to authenticated using (id = (select auth.uid()));
create policy "people rename themselves" on public.profiles
  for update to authenticated
  using (id = (select auth.uid())) with check (id = (select auth.uid()));

create policy "people read their own sign-ins" on public.sign_in_events
  for select to authenticated using (user_id = (select auth.uid()));
create policy "people record their own sign-ins" on public.sign_in_events
  for insert to authenticated with check (user_id = (select auth.uid()));
