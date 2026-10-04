-- Tenant boundary for Automatron's durable data.
--
-- Every table is protected by row-level security, forced so that it applies to
-- the table owner too. The application holds only the publishable key and acts
-- as the signed-in user, so the database itself refuses a cross-tenant read even
-- if a bug in the application asked for one. The service-role key is never
-- configured in the application.
--
-- Apply with `supabase db push`.

create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to authenticated;

-- ---------------------------------------------------------------------------
-- Organizations and membership
-- ---------------------------------------------------------------------------

create table public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 120),
  created_at timestamptz not null default now()
);

create table public.organization_members (
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  role text not null check (role in ('owner', 'member')),
  created_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

-- Policies look membership up by user on every row they check.
create index organization_members_user_idx on public.organization_members (user_id);

-- Security definer so a policy on organization_members can consult
-- organization_members without recursing into its own policy. The search path is
-- empty and every name is qualified, so a caller cannot shadow a table.
create function private.is_org_member(target_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.organization_members m
    where m.organization_id = target_org and m.user_id = (select auth.uid())
  );
$$;

create function private.is_org_owner(target_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.organization_members m
    where m.organization_id = target_org
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  );
$$;

-- A storage path's first segment is meant to be an organization id, but it is
-- whatever the uploader typed. A malformed one must deny, not raise.
create function private.try_uuid(value text)
returns uuid
language plpgsql
immutable
set search_path = ''
as $$
begin
  return value::uuid;
exception when invalid_text_representation then
  return null;
end;
$$;

revoke all on function private.is_org_member(uuid) from public, anon;
revoke all on function private.is_org_owner(uuid) from public, anon;
revoke all on function private.try_uuid(text) from public, anon;
grant execute on function private.is_org_member(uuid) to authenticated;
grant execute on function private.is_org_owner(uuid) to authenticated;
grant execute on function private.try_uuid(text) to authenticated;

-- Every new user gets a personal organization they own, so there is always one to
-- put their runs in, and nobody ever needs a privileged key to create it.
create function private.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  personal uuid;
begin
  insert into public.organizations (name)
  values (coalesce(nullif(split_part(new.email, '@', 1), ''), 'Personal'))
  returning id into personal;
  insert into public.organization_members (organization_id, user_id, role)
  values (personal, new.id, 'owner');
  return new;
end;
$$;

revoke all on function private.handle_new_user() from public, anon, authenticated;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function private.handle_new_user();

-- ---------------------------------------------------------------------------
-- Runs and their audit trail
-- ---------------------------------------------------------------------------

create table public.runs (
  id uuid primary key,
  organization_id uuid not null references public.organizations (id) on delete cascade,
  created_by uuid not null default auth.uid() references auth.users (id),
  sector text not null check (sector in ('space', 'quant', 'ecommerce', 'realestate')),
  workflow_id text not null check (char_length(workflow_id) <= 80),
  status text not null check (status in ('queued', 'running', 'awaiting_approval',
                                         'revising', 'approved', 'rejected', 'failed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- Lets the audit table require that an entry names its run's own organization.
  unique (id, organization_id)
);

create index runs_organization_created_idx on public.runs (organization_id, created_at desc);
create index runs_created_by_idx on public.runs (created_by);

create table public.audit_entries (
  id bigint generated always as identity primary key,
  run_id uuid not null,
  organization_id uuid not null,
  actor uuid not null default auth.uid() references auth.users (id),
  payload jsonb not null,
  prev_hash text not null check (prev_hash ~ '^[0-9a-f]{64}$'),
  hash text not null check (hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  -- An entry cannot claim a run from one organization while filing itself under
  -- another, which is how it would otherwise become readable to the wrong tenant.
  -- Restrict rather than cascade: entries are append-only, so a run that has been
  -- decided keeps its record, and so does the organization that owns it.
  foreign key (run_id, organization_id)
    references public.runs (id, organization_id) on delete restrict
);

create index audit_entries_run_idx on public.audit_entries (run_id, id);
create index audit_entries_organization_idx on public.audit_entries (organization_id);
create index audit_entries_actor_idx on public.audit_entries (actor);

-- The audit trail is append-only for everyone, the table owner included. A policy
-- alone would leave a privileged connection able to rewrite history.
create function private.forbid_audit_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'audit entries are append-only';
end;
$$;

create trigger audit_entries_append_only
  before update or delete on public.audit_entries
  for each row execute function private.forbid_audit_mutation();

-- ---------------------------------------------------------------------------
-- Privileges: the API roles get exactly the verbs the policies below expect
-- ---------------------------------------------------------------------------

revoke all on public.organizations, public.organization_members, public.runs,
  public.audit_entries from anon, authenticated;

grant select, update (name) on public.organizations to authenticated;
grant select, insert, delete on public.organization_members to authenticated;
grant select, insert, update (status, updated_at) on public.runs to authenticated;
grant select, insert on public.audit_entries to authenticated;

-- ---------------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------------

alter table public.organizations enable row level security;
alter table public.organizations force row level security;
alter table public.organization_members enable row level security;
alter table public.organization_members force row level security;
alter table public.runs enable row level security;
alter table public.runs force row level security;
alter table public.audit_entries enable row level security;
alter table public.audit_entries force row level security;

create policy "members read their organizations" on public.organizations
  for select to authenticated using (private.is_org_member(id));
create policy "owners rename their organizations" on public.organizations
  for update to authenticated
  using (private.is_org_owner(id)) with check (private.is_org_owner(id));

create policy "members read their organization's membership" on public.organization_members
  for select to authenticated using (private.is_org_member(organization_id));
create policy "owners add members" on public.organization_members
  for insert to authenticated with check (private.is_org_owner(organization_id));
-- An owner cannot remove themselves, so an organization is never left ownerless
-- by accident.
create policy "owners remove other members" on public.organization_members
  for delete to authenticated
  using (private.is_org_owner(organization_id) and user_id <> (select auth.uid()));

create policy "members read their organization's runs" on public.runs
  for select to authenticated using (private.is_org_member(organization_id));
create policy "members start runs in their organizations" on public.runs
  for insert to authenticated
  with check (created_by = (select auth.uid()) and private.is_org_member(organization_id));
create policy "the creator updates a run's status" on public.runs
  for update to authenticated
  using (created_by = (select auth.uid()))
  with check (created_by = (select auth.uid()) and private.is_org_member(organization_id));

create policy "members read their organization's audit trail" on public.audit_entries
  for select to authenticated using (private.is_org_member(organization_id));
create policy "members append to their organization's audit trail" on public.audit_entries
  for insert to authenticated
  with check (actor = (select auth.uid()) and private.is_org_member(organization_id));

-- ---------------------------------------------------------------------------
-- Uploaded files: private bucket, paths <organization_id>/<run_id>/<file_id>
-- ---------------------------------------------------------------------------

insert into storage.buckets (id, name, public)
values ('run-uploads', 'run-uploads', false)
on conflict (id) do nothing;

create policy "members read their organization's uploads" on storage.objects
  for select to authenticated using (
    bucket_id = 'run-uploads'
    and private.is_org_member(private.try_uuid((storage.foldername(name))[1]))
  );
create policy "members upload into their organization" on storage.objects
  for insert to authenticated with check (
    bucket_id = 'run-uploads'
    and private.is_org_member(private.try_uuid((storage.foldername(name))[1]))
  );
