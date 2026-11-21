-- Companies, employers and jobs (design doc §2.1, §6, §8).

create table public.companies (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  name_he text,
  parent_company_id uuid references public.companies (id) on delete set null,
  website text,
  ats_provider text,
  ats_board_token text,
  is_claimed boolean not null default false,
  -- Billing (Phase 2). The wallet belongs to the company.
  tax_id text,
  billing_email text,
  payment_gateway_token text,
  credit_balance_agorot bigint not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint companies_ats_provider_valid
    check (ats_provider is null or ats_provider in ('greenhouse', 'lever', 'comeet', 'ashby')),
  constraint companies_ats_config_complete
    check ((ats_provider is null) = (ats_board_token is null)),
  constraint companies_credit_balance_non_negative check (credit_balance_agorot >= 0),
  constraint companies_not_own_parent check (parent_company_id <> id)
);

create unique index companies_ats_board_key
  on public.companies (ats_provider, ats_board_token)
  where ats_provider is not null;
create index companies_parent_idx on public.companies (parent_company_id);

create trigger companies_set_updated_at
  before update on public.companies
  for each row execute function public.set_updated_at();

-- Hebrew/English spellings, legal names, abbreviations. Used for blocklist resolution.
create table public.company_aliases (
  alias_normalized text primary key,
  company_id uuid not null references public.companies (id) on delete cascade
);

create table public.employers (
  user_id uuid not null references public.users (id) on delete cascade,
  company_id uuid not null references public.companies (id) on delete cascade,
  role text not null default 'recruiter',
  created_at timestamptz not null default now(),
  primary key (user_id, company_id),

  constraint employers_role_valid check (role in ('owner', 'recruiter'))
);

create index employers_company_idx on public.employers (company_id);

create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies (id) on delete cascade,
  source text not null,
  -- ATS posting id for scraped jobs.
  external_id text,
  slug text not null unique,
  title_original text not null,
  title_he text,
  description_original text,
  apply_url text,
  locality_id integer references public.localities (id),
  work_model text,
  experience_years_min smallint,
  experience_years_max smallint,
  -- Salaries are whole shekels per month (billing amounts are agorot).
  salary_min_monthly_ils integer,
  salary_max_monthly_ils integer,
  requirements jsonb not null default '{}',
  is_confidential boolean not null default false,
  is_active boolean not null default true,
  content_hash text,
  cost_per_action_agorot integer,
  embedding extensions.vector(1536),
  posted_at timestamptz,
  last_seen_at timestamptz,
  deactivated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint jobs_source_valid check (source in ('scraped_ats', 'direct_employer')),
  constraint jobs_scraped_have_external_id check (source <> 'scraped_ats' or external_id is not null),
  constraint jobs_work_model_valid
    check (work_model is null or work_model in ('onsite', 'hybrid', 'remote')),
  constraint jobs_experience_range_valid
    check (experience_years_min is null or experience_years_max is null
           or experience_years_min <= experience_years_max),
  constraint jobs_salary_range_valid
    check (salary_min_monthly_ils is null or salary_max_monthly_ils is null
           or salary_min_monthly_ils <= salary_max_monthly_ils),
  constraint jobs_cost_non_negative check (cost_per_action_agorot is null or cost_per_action_agorot >= 0)
);

create unique index jobs_external_key
  on public.jobs (company_id, external_id)
  where external_id is not null;
create index jobs_active_company_idx on public.jobs (company_id) where is_active;
create index jobs_locality_idx on public.jobs (locality_id);
create index jobs_embedding_idx
  on public.jobs using hnsw (embedding extensions.vector_cosine_ops);

create trigger jobs_set_updated_at
  before update on public.jobs
  for each row execute function public.set_updated_at();

create table public.job_skills (
  job_id uuid not null references public.jobs (id) on delete cascade,
  skill_id bigint not null references public.skills (id) on delete cascade,
  primary key (job_id, skill_id)
);

create index job_skills_skill_idx on public.job_skills (skill_id);
