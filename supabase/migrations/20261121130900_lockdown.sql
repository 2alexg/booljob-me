-- Deny-all for the Data API roles (design doc §3.1).
--
-- RLS is enabled with no policies, and all privileges are revoked, on every
-- table in public. Every future migration that creates a table must enable
-- RLS on it; supabase/tests/database/lockdown_test.sql enforces this.

do $$
declare
  t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end;
$$;

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;
