-- Extensions and shared helpers.
--
-- Access model (design doc §3.1): the browser never talks to the database.
-- FastAPI connects with the service role. anon/authenticated get nothing.

create extension if not exists vector with schema extensions;
create extension if not exists postgis with schema extensions;

-- New objects in public must not be reachable by the Data API roles by default.
-- (Cloud projects may still have the legacy auto-grant behaviour; the final
-- lockdown migration also revokes explicitly.)
alter default privileges for role postgres in schema public
  revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke execute on functions from public, anon, authenticated;

-- Keeps updated_at current on every UPDATE.
create function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;
