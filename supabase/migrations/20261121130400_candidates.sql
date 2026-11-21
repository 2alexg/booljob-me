-- Candidates (design doc §2.1, §5.A, §8).
--
-- Protected attributes (age, birth date, photo, gender, marital status,
-- religion, military unit) are never stored. Do not add columns for them.

create table public.candidates (
  user_id uuid primary key references public.users (id) on delete cascade,
  status text not null default 'onboarding',
  locality_id integer references public.localities (id),
  cv_storage_path text,
  cv_parsed jsonb,
  quiz_questions jsonb,
  quiz_answers jsonb,
  profile_summary_for_ai text,
  experience_years smallint,
  -- Whole shekels per month.
  min_salary_expected_monthly_ils integer,
  max_commute_km smallint,
  preferred_work_models text[] not null default '{}',
  -- Blocklist entries that could not be resolved to a company (§2.1).
  blocked_company_names_unresolved text[] not null default '{}',
  embedding extensions.vector(1536),
  last_active_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint candidates_status_valid check (status in ('onboarding', 'active', 'paused')),
  constraint candidates_work_models_valid
    check (preferred_work_models <@ array['onsite', 'hybrid', 'remote']::text[]),
  constraint candidates_commute_positive check (max_commute_km is null or max_commute_km > 0)
);

create index candidates_active_idx on public.candidates (last_active_at) where status = 'active';
create index candidates_embedding_idx
  on public.candidates using hnsw (embedding extensions.vector_cosine_ops);

create trigger candidates_set_updated_at
  before update on public.candidates
  for each row execute function public.set_updated_at();

create table public.candidate_skills (
  candidate_id uuid not null references public.candidates (user_id) on delete cascade,
  skill_id bigint not null references public.skills (id) on delete cascade,
  primary key (candidate_id, skill_id)
);

create index candidate_skills_skill_idx on public.candidate_skills (skill_id);

-- Resolved blocklist. Matching must also exclude parent/child companies.
create table public.candidate_blocked_companies (
  candidate_id uuid not null references public.candidates (user_id) on delete cascade,
  company_id uuid not null references public.companies (id) on delete cascade,
  source text not null,
  created_at timestamptz not null default now(),
  primary key (candidate_id, company_id),

  constraint candidate_blocked_companies_source_valid
    check (source in ('auto_current_employer', 'manual'))
);

create index candidate_blocked_companies_company_idx
  on public.candidate_blocked_companies (company_id);
