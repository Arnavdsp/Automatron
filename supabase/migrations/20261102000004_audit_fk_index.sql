-- The audit trail's foreign key to its run is the pair (run_id, organization_id).
-- Deleting or re-keying a run checks it, and without an index that matches the pair
-- the check scans every entry. Flagged by the Supabase performance advisor.
create index audit_entries_run_organization_idx
  on public.audit_entries (run_id, organization_id);
