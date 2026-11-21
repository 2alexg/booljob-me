-- Identity, roles, verification and consent (design doc §4, §7).
--
-- OAuth provider links live in Supabase's auth.identities; there is no
-- separate user_oauth_accounts table.

create table public.users (
  id uuid primary key references auth.users (id) on delete cascade,
  email text,
  phone text unique,
  email_verified boolean not null default false,
  phone_verified boolean not null default false,
  roles text[] not null default '{}',
  status text not null default 'pending_verification',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint users_phone_e164_il_mobile check (phone ~ '^\+9725[0-9]{8}$'),
  constraint users_roles_valid check (roles <@ array['candidate', 'employer', 'admin']::text[]),
  constraint users_status_valid
    check (status in ('pending_verification', 'active', 'suspended', 'deleted')),
  -- Activation requires both channels verified.
  constraint users_active_requires_dual_verification
    check (status <> 'active' or (email_verified and phone_verified))
);

-- Email lookups are case-insensitive.
create unique index users_email_lower_key on public.users (lower(email));

create trigger users_set_updated_at
  before update on public.users
  for each row execute function public.set_updated_at();

create table public.user_consents (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.users (id) on delete cascade,
  consent_type text not null,
  consent_version text not null,
  granted_at timestamptz not null default now(),
  revoked_at timestamptz,

  constraint user_consents_type_valid
    check (consent_type in ('ai_processing', 'cross_border_transfer', 'employer_matching'))
);

create index user_consents_user_idx on public.user_consents (user_id, consent_type);
