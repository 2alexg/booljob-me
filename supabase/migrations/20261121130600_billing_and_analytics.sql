-- Prepaid wallet ledger and analytics events (design doc §8).
--
-- Debits lock the company row with SELECT ... FOR UPDATE, then insert a ledger
-- row and update companies.credit_balance_agorot in the same transaction.
-- Billing rows survive candidate deletion with identifiers nulled out (§7).

create table public.credit_transactions (
  id bigint generated always as identity primary key,
  company_id uuid not null references public.companies (id),
  -- Positive = credit, negative = debit.
  amount_agorot bigint not null,
  balance_after_agorot bigint not null,
  kind text not null,
  match_id uuid references public.matches (id) on delete set null,
  external_payment_ref text,
  created_by_user_id uuid references public.users (id) on delete set null,
  created_at timestamptz not null default now(),

  constraint credit_transactions_kind_valid
    check (kind in ('purchase', 'pilot_grant', 'unlock_debit', 'refund', 'adjustment')),
  constraint credit_transactions_amount_nonzero check (amount_agorot <> 0),
  constraint credit_transactions_balance_non_negative check (balance_after_agorot >= 0),
  constraint credit_transactions_debit_sign check (kind <> 'unlock_debit' or amount_agorot < 0)
);

create index credit_transactions_company_idx on public.credit_transactions (company_id, created_at);
-- A match can be charged at most once.
create unique index credit_transactions_one_unlock_per_match
  on public.credit_transactions (match_id)
  where kind = 'unlock_debit' and match_id is not null;

create table public.analytics_events (
  id bigint generated always as identity primary key,
  event_type text not null,
  user_id uuid references public.users (id) on delete set null,
  company_id uuid references public.companies (id) on delete set null,
  job_id uuid references public.jobs (id) on delete set null,
  match_id uuid references public.matches (id) on delete set null,
  is_billable boolean not null default false,
  properties jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create index analytics_events_type_time_idx on public.analytics_events (event_type, created_at);
-- Idempotent billing: one billable event of each type per match.
create unique index analytics_events_billable_once
  on public.analytics_events (event_type, match_id)
  where is_billable and match_id is not null;
