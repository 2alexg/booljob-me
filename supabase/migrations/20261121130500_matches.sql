-- Matches, their status history, and relevance feedback (design doc §2.2–§2.5, §9).
--
-- Legal transitions are enforced by the FastAPI policy module (S1-06).
-- The constraints here only guarantee that each status belongs to its flow.

create table public.matches (
  id uuid primary key default gen_random_uuid(),
  candidate_id uuid not null references public.candidates (user_id) on delete cascade,
  job_id uuid not null references public.jobs (id) on delete cascade,
  flow text not null,
  status text not null default 'suggested',
  vector_similarity_score real,
  ai_rerank_score smallint,
  ai_explanation_he text,
  status_changed_at timestamptz not null default now(),
  -- Set when entering a state that can expire (§2.5).
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  unique (candidate_id, job_id),

  constraint matches_flow_valid check (flow in ('external', 'double_opt_in')),
  constraint matches_status_valid_for_flow check (
    (flow = 'external' and status in (
      'suggested', 'candidate_viewed', 'applied_external', 'dismissed_by_candidate', 'closed'
    ))
    or
    (flow = 'double_opt_in' and status in (
      'suggested', 'employer_interested', 'candidate_interested', 'candidate_revealed_job',
      'mutual_interest', 'unlocked_by_employer', 'declined_by_candidate', 'declined_by_employer',
      'withdrawn_by_candidate', 'expired', 'closed'
    ))
  ),
  constraint matches_similarity_range
    check (vector_similarity_score is null or vector_similarity_score between -1 and 1),
  constraint matches_rerank_range
    check (ai_rerank_score is null or ai_rerank_score between 0 and 100)
);

create index matches_candidate_status_idx on public.matches (candidate_id, status);
create index matches_job_status_idx on public.matches (job_id, status);
create index matches_expiry_idx on public.matches (expires_at) where expires_at is not null;

create trigger matches_set_updated_at
  before update on public.matches
  for each row execute function public.set_updated_at();

create table public.match_status_events (
  id bigint generated always as identity primary key,
  match_id uuid not null references public.matches (id) on delete cascade,
  from_status text,
  to_status text not null,
  actor_user_id uuid references public.users (id) on delete set null,
  -- 'system' for worker-driven transitions such as expiry or closure.
  actor_kind text not null,
  created_at timestamptz not null default now(),

  constraint match_status_events_actor_kind_valid
    check (actor_kind in ('candidate', 'employer', 'system'))
);

create index match_status_events_match_idx on public.match_status_events (match_id, created_at);

-- Phase 1 success metric: share of matches rated relevant.
create table public.match_feedback (
  match_id uuid primary key references public.matches (id) on delete cascade,
  rating text not null,
  reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint match_feedback_rating_valid check (rating in ('relevant', 'not_relevant'))
);

create trigger match_feedback_set_updated_at
  before update on public.match_feedback
  for each row execute function public.set_updated_at();
