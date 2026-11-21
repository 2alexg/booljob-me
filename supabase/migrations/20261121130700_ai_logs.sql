-- AI audit trail (design doc §5.E, §7).
--
-- The largest PII store in the system: admin-only, every admin read is
-- recorded in ai_log_access, and PII payloads are redacted after 90 days
-- (pii_redacted_at marks rows already processed).

create table public.ai_interaction_logs (
  id bigint generated always as identity primary key,
  session_id uuid,
  task text not null,
  model text not null,
  prompt_version text not null,
  system_prompt text,
  user_input_payload jsonb,
  ai_raw_output text,
  input_tokens integer,
  output_tokens integer,
  latency_ms integer,
  status text not null default 'ok',
  error text,
  candidate_id uuid references public.candidates (user_id) on delete set null,
  job_id uuid references public.jobs (id) on delete set null,
  pii_redacted_at timestamptz,
  admin_reviewed boolean not null default false,
  admin_quality_rating smallint,
  admin_notes text,
  created_at timestamptz not null default now(),

  constraint ai_interaction_logs_task_valid check (task in (
    'cv_analysis', 'quiz_generation', 'quiz_summary', 'deidentification',
    'rerank', 'job_normalization', 'skill_mapping', 'location_resolution'
  )),
  constraint ai_interaction_logs_status_valid check (status in ('ok', 'error')),
  constraint ai_interaction_logs_rating_range
    check (admin_quality_rating is null or admin_quality_rating between 1 and 5)
);

create index ai_interaction_logs_created_idx on public.ai_interaction_logs (created_at);
create index ai_interaction_logs_task_idx on public.ai_interaction_logs (task, prompt_version);
create index ai_interaction_logs_unredacted_idx
  on public.ai_interaction_logs (created_at) where pii_redacted_at is null;

create table public.ai_log_access (
  id bigint generated always as identity primary key,
  log_id bigint not null references public.ai_interaction_logs (id) on delete cascade,
  admin_user_id uuid not null references public.users (id),
  accessed_at timestamptz not null default now()
);

create index ai_log_access_log_idx on public.ai_log_access (log_id);
