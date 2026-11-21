-- Deny-all lockdown (design doc §3.1). Run with: pnpm supabase test db
begin;
create extension if not exists pgtap with schema extensions;
select * from no_plan();

select has_extension('vector');
select has_extension('postgis');

select is_empty(
  $$ select tablename::text from pg_tables where schemaname = 'public' and not rowsecurity $$,
  'every table in public has RLS enabled'
);

select is_empty(
  $$
  select r.rolname || ' has ' || p.priv || ' on ' || c.relname
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  cross join (values ('anon'), ('authenticated')) as r (rolname)
  cross join (values ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')) as p (priv)
  where n.nspname = 'public'
    and c.relkind in ('r', 'p', 'v', 'm')
    and has_table_privilege(r.rolname, c.oid, p.priv)
  $$,
  'anon and authenticated have no privileges on any table in public'
);

select is(
  (select public from storage.buckets where id = 'cvs'),
  false,
  'the cvs bucket is private'
);

-- Behavioural check: every table rejects reads and writes from both roles.
set local role anon;
select throws_ok(
  format('select 1 from public.%I', tablename), '42501', null,
  format('anon cannot read %s', tablename)
)
from pg_tables where schemaname = 'public';
select throws_ok(
  format('delete from public.%I', tablename), '42501', null,
  format('anon cannot delete from %s', tablename)
)
from pg_tables where schemaname = 'public';
reset role;

set local role authenticated;
select throws_ok(
  format('select 1 from public.%I', tablename), '42501', null,
  format('authenticated cannot read %s', tablename)
)
from pg_tables where schemaname = 'public';
select throws_ok(
  format('delete from public.%I', tablename), '42501', null,
  format('authenticated cannot delete from %s', tablename)
)
from pg_tables where schemaname = 'public';
reset role;

select * from finish();
rollback;
