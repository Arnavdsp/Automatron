-- Run content is encrypted by the application before it reaches the database.
--
-- Each run has its own AES-256-GCM data key, stored here only in wrapped form
-- (wrapped by Cloud KMS or by a key the database never sees). Every sealed value is
-- bound to its run, its owner and its field, so a value copied into another row
-- does not decrypt. The database holds ciphertext it cannot read: a leaked backup,
-- a mistaken policy or anyone with database access learns sector, workflow, status
-- and timing, and nothing of what was asked or concluded.
--
-- There is deliberately no plaintext column for the request, the inputs or the
-- brief, and the checks below refuse any value that is not sealed, so plaintext
-- cannot arrive by accident either.

alter table public.runs
  add column key_id text not null default ''
    check (key_id ~ '^(local:[A-Za-z0-9_-]{1,32}|kms:projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+)$'),
  add column wrapped_key text not null default ''
    check (char_length(wrapped_key) between 16 and 2048),
  add column sealed_input text not null default ''
    check (sealed_input ~ '^v1\.[A-Za-z0-9_-]+$' and char_length(sealed_input) <= 2000000),
  add column sealed_result text
    check (sealed_result is null
           or (sealed_result ~ '^v1\.[A-Za-z0-9_-]+$' and char_length(sealed_result) <= 4000000));

-- The defaults above exist only so the columns could be added; every new run must
-- supply real values, which the checks then hold to the sealed format.
alter table public.runs
  alter column key_id drop default,
  alter column wrapped_key drop default,
  alter column sealed_input drop default;

-- The creator may record the outcome, never rewrite what was asked or the key.
grant update (sealed_result) on public.runs to authenticated;

-- Audit payloads carry the decision in the clear and everything else sealed.
alter table public.audit_entries
  add constraint audit_entries_payload_sealed check (
    payload ? 'sealed' and payload ->> 'sealed' ~ '^v1\.[A-Za-z0-9_-]+$'
    and (payload - 'sealed' - 'action') = '{}'::jsonb
  );
