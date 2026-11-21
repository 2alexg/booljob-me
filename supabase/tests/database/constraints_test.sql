-- Schema invariants enforced by constraints. Run with: pnpm supabase test db
begin;
create extension if not exists pgtap with schema extensions;
select * from no_plan();

insert into auth.users (id, email)
values ('00000000-0000-0000-0000-000000000001', 'cand@example.com');

-- Users: dual verification, phone format, case-insensitive email.
select throws_ok(
  $$ insert into public.users (id, email, status)
     values ('00000000-0000-0000-0000-000000000001', 'cand@example.com', 'active') $$,
  '23514', null,
  'a user cannot be active without both email and phone verified'
);

select throws_ok(
  $$ insert into public.users (id, phone)
     values ('00000000-0000-0000-0000-000000000001', '+972312345678') $$,
  '23514', null,
  'phone must be an Israeli mobile in E.164 format'
);

select lives_ok(
  $$ insert into public.users (id, email, phone, email_verified, phone_verified, roles, status)
     values ('00000000-0000-0000-0000-000000000001', 'cand@example.com', '+972501234567',
             true, true, '{candidate}', 'active') $$,
  'a dual-verified user can be active'
);

insert into auth.users (id, email)
values ('00000000-0000-0000-0000-000000000002', 'other@example.com');

select throws_ok(
  $$ insert into public.users (id, email)
     values ('00000000-0000-0000-0000-000000000002', 'CAND@example.com') $$,
  '23505', null,
  'email uniqueness is case-insensitive'
);

-- Matches: each status must belong to its flow.
insert into public.candidates (user_id) values ('00000000-0000-0000-0000-000000000001');
insert into public.companies (id, name, ats_provider, ats_board_token)
values ('00000000-0000-0000-0000-0000000000c1', 'Acme', 'greenhouse', 'acme');
insert into public.jobs (id, company_id, source, external_id, slug, title_original)
values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000c1',
        'scraped_ats', '123', 'acme-backend-engineer', 'Backend Engineer');

select throws_ok(
  $$ insert into public.matches (candidate_id, job_id, flow, status)
     values ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000a1',
             'external', 'mutual_interest') $$,
  '23514', null,
  'the external flow cannot enter a double opt-in state'
);

select throws_ok(
  $$ insert into public.jobs (company_id, source, slug, title_original)
     values ('00000000-0000-0000-0000-0000000000c1', 'scraped_ats', 'no-ext-id', 'X') $$,
  '23514', null,
  'scraped jobs require an external_id'
);

insert into public.matches (id, candidate_id, job_id, flow, status)
values ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-0000000000a1', 'double_opt_in', 'mutual_interest');

-- Billing: a match can be charged only once; balances cannot go negative.
insert into public.credit_transactions (company_id, amount_agorot, balance_after_agorot, kind, match_id)
values ('00000000-0000-0000-0000-0000000000c1', -5000, 0, 'unlock_debit',
        '00000000-0000-0000-0000-0000000000e1');

select throws_ok(
  $$ insert into public.credit_transactions
       (company_id, amount_agorot, balance_after_agorot, kind, match_id)
     values ('00000000-0000-0000-0000-0000000000c1', -5000, 0, 'unlock_debit',
             '00000000-0000-0000-0000-0000000000e1') $$,
  '23505', null,
  'a match can be unlocked (charged) only once'
);

select throws_ok(
  $$ update public.companies set credit_balance_agorot = -1
     where id = '00000000-0000-0000-0000-0000000000c1' $$,
  '23514', null,
  'company credit balance cannot go negative'
);

insert into public.analytics_events (event_type, match_id, is_billable)
values ('contact_unlocked', '00000000-0000-0000-0000-0000000000e1', true);

select throws_ok(
  $$ insert into public.analytics_events (event_type, match_id, is_billable)
     values ('contact_unlocked', '00000000-0000-0000-0000-0000000000e1', true) $$,
  '23505', null,
  'billable events are idempotent per match'
);

select * from finish();
rollback;
