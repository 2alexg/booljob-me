# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Early Sprint 1. The monorepo is scaffolded (S1-01), but there is no product code yet. The source of truth is `docs/BoolJob.me - Product & Technical Design.md`. Read it before designing anything. Its §9.1 has the Sprint 1 tasks and its §10 lists decisions that are still open.

## Commands

Toolchain: Node 26 (`.node-version`), pnpm 10, uv, Python 3.13 (`api/.python-version`). The Supabase CLI is a pinned dev dependency at the repo root, so always run it as `pnpm supabase ...`, never through a global install. Docker is required for the local Supabase stack.

```bash
pnpm install                      # repo root: installs web + Supabase CLI

# web/ (Next.js 16)
cd web && pnpm dev                # dev server
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm vitest run src/lib/site.test.ts   # single test file

# api/ (FastAPI)
cd api && uv sync
uv run uvicorn bool_api.main:app --reload
uv run ruff check && uv run ruff format --check && uv run pytest
uv run pytest tests/test_health.py::test_healthz   # single test

# supabase/ (run from repo root)
pnpm supabase db start && pnpm supabase db reset   # apply all migrations from scratch
pnpm supabase migration new <name>                 # new SQL migration
pnpm supabase test db                              # pgTAP tests in supabase/tests/database/
```

Every new table in `public` must `enable row level security` in its migration and grant nothing to `anon`/`authenticated`. `supabase/tests/database/lockdown_test.sql` fails otherwise.

CI (`.github/workflows/ci.yml`) runs the web, api and migration checks above on every PR.

**Next.js 16 differs from older versions.** Read `web/AGENTS.md` and the docs bundled in `web/node_modules/next/dist/docs/` before writing web code. `next dev` regenerates `web/AGENTS.md`; commit it as is.

GCP setup is scripted and idempotent: `infra/gcp/bootstrap.sh <project-id> <staging|prod>`. Staging is `booljob-me-staging`. GitHub Actions authenticates through Workload Identity Federation (variables in the `staging` GitHub environment); there are no service-account keys.

## What Bool is

Bool (booljob.me) is an AI-powered, privacy-first, two-sided job matching platform for the Israeli market. The UI is Hebrew-first and RTL, and must meet the Israeli accessibility standard (IS 5568 / WCAG 2.0 AA). Candidate-facing AI text (quiz questions, match explanations, normalized job titles) is generated in Hebrew. Billing money is stored as integer **agorot**; salaries as whole shekels per month (`*_monthly_ils`). Phones are Israeli mobiles in E.164 format (`+9725...`).

## Repo & hosting

- **Monorepo layout:**
  - `web/` (Next.js, pnpm)
  - `api/` (FastAPI, uv, ruff, pytest; one image with API and worker entrypoints)
  - `supabase/` (Supabase CLI project)
  - `eval/` (offline evaluation only)
- **The Supabase CLI owns the schema.** Every DB change is a SQL migration in `supabase/migrations/`. FastAPI never runs migrations. Validate with `supabase db reset`.
- **Everything runs in Frankfurt:**
  - Supabase `eu-central-1`
  - Cloud Run `europe-west3`
  - Vertex AI in the EU
  - Vercel `fra1`
  - Upstash `eu-central-1`

  There are separate Supabase projects for dev, staging, and prod.
- **`eval/` holds LLM-generated synthetic CVs** for the embedding evaluation. Never load them into Supabase, Storage, or any environment.
- The Sprint 1 task list (S1-01 … S1-18) is in design doc §9.1.

## Planned architecture

1. **Next.js App Router on Vercel**: `booljob.me` (candidates, public SSR job pages `/jobs/[slug]` with OG tags + JSON-LD `JobPosting`) and `hire.booljob.me` (recruiters). It acts as a **BFF**: auth tokens live in HttpOnly/Secure/SameSite=Strict cookies, and private calls go through `/api/proxy/*`, which adds a server-side `X-Internal-Secret` header.
2. **FastAPI on Cloud Run**, split into an API service and a worker service. It returns 403 for any request without `X-Internal-Secret`, and validates Supabase JWTs. All AI work runs in the worker. Telegram admin alerts carry IDs only, never PII.
3. **Supabase** (Postgres + pgvector + PostGIS + Auth + Storage). **Upstash Redis** handles rate limits and caching. **Upstash QStash** is the background queue: it pushes jobs to the worker over HTTP and also runs the cron schedules. CVs sit in a private bucket and are reachable only through 15-minute signed URLs.

**Authorization lives in FastAPI, not in RLS.** FastAPI uses the service role, which bypasses RLS, and RLS simply denies everything to the `anon`/`authenticated` roles. All access control must go through one central policy module, never ad-hoc checks in route handlers. That module covers:
- which matches a user may see, by role and state
- blocklist filtering
- per-state redaction of candidate fields
- unlock gating

The module needs a test for every state × role combination.

## Invariants that span multiple components

- **Two match flows** (`matches.status`):
  - *Scraped ATS jobs:* `suggested → candidate_viewed → applied_external | dismissed_by_candidate`.
  - *Direct-employer jobs (double opt-in):* `suggested → employer_interested → candidate_revealed_job → mutual_interest → unlocked_by_employer`, or the candidate-initiated path `suggested → candidate_interested → mutual_interest`.
  - Terminal states: `declined_by_candidate`, `declined_by_employer`, `withdrawn_by_candidate`, `expired` (14-day windows, enforced by the nightly worker), `closed` (job inactive).
  - Candidate identity must never reach an employer before `unlocked_by_employer`. Only `mutual_interest` matches can be unlocked (paid).
- **Anonymized cards** show region (not city), experience bands, skills, and work model. The AI-written summary must pass a de-identification check (rule filter + LLM check) before it is displayed.
- **The blocklist uses `company_id`**, resolved through `company_aliases` and extended through `parent_company_id`. CV parsing auto-blocks the current employer. Names that can't be resolved go to `blocked_company_names_unresolved` and are fuzzy-matched conservatively (exclude when unsure). Blocked companies never see the candidate, not even anonymized.
- **Protected attributes are never extracted or stored**: age, birth date, photo, gender, marital status, religion, military unit. This keeps the product within the Equal Employment Opportunities Law.
- **Confidential jobs** (`is_confidential`) show a generic company profile even after the candidate reveals the job.
- **Auth**:
  - Activation requires both `email_verified` and `phone_verified`.
  - SMS OTP goes through Supabase Auth's phone provider with a Send SMS Hook to an Israeli gateway. Do not build our own OTP storage.
  - Email lookups use `LOWER(email)`. Phone numbers are unique.
  - An account merge requires proving ownership of both accounts.
- **Billing**: prepaid wallet with `credit_transactions`. Debits use `SELECT ... FOR UPDATE`. Billable `analytics_events` are idempotent through a unique partial index.
- **AI audit**: log every LLM call to `ai_interaction_logs`. This table is the largest PII store, so it is admin-only, every read is logged, and PII is redacted after 90 days.
- **Privacy (Amendment 13)**:
  - explicit consent for AI processing and cross-border transfer
  - self-service data export and deletion
  - retention policy in design doc §7

## AI pipelines (summary)

- **Onboarding**: extract text (PyMuPDF / python-docx, with a multimodal fallback for scans), then run a Gemini 2.5 Flash structured extraction with Pydantic. This produces a Hebrew quiz of 5–7 questions (4–5 single/multiple choice, at most 1–2 `open_text`). The result becomes `profile_summary_for_ai` and an embedding from `gemini-embedding-001` at 1536 dims. Candidates and jobs must use the same embedding model.
- **Matching thresholds**: vector similarity ≥ 0.75 for Stage 1. `ai_rerank_score` ≥ 75 appears in the candidate feed with an explanation of ≤ 25 Hebrew words. `ai_rerank_score` ≥ 80 appears to recruiters.
- **Matching**:
  - Stage 1 is SQL hard filters (PostGIS `ST_DWithin`, work model, salary, blocklist) plus pgvector top 15–20.
  - Stage 2 is a single batched Gemini rerank.
  - Missing salary passes the salary filter. Missing location matches only remote jobs.
- **Rerank cost controls**:
  - Scraped jobs are reranked in one nightly batch, never per job.
  - Only candidates active in the last 30 days are reranked.
  - A daily token budget pauses reranking and sends a Telegram alert when exceeded.
- **Locations**:
  - Everything resolves to a `locality_id` from the government localities seed. Alias lookup comes first, with Google Geocoding as a fallback.
  - **Never store Google's coordinates.** Google Maps terms forbid it. Commute filtering uses locality-level points from the government data or OpenStreetMap.
  - Regions come from a manual locality → region mapping.
- **Skills**:
  - A self-grown `skills` / `skill_aliases` taxonomy.
  - Skills the LLM can't map are inserted as `pending` and need admin approval before they are used in matching.
- **Jobs** keep `title_original` verbatim (often English) alongside `title_he`.
- **Phase 1 success metric**: share of matches rated relevant, from `match_feedback`.
- **ATS ingestion**:
  - Only free, unauthenticated public job-board APIs are used: Greenhouse and Lever, plus Comeet or Ashby depending on the S1-15 check. Connectors use a strategy pattern and keep only Israel and Israel-remote roles.
  - Companies are discovered through a paid search API, not by scraping Google.
  - Unchanged jobs are skipped by SHA-256 content hash.
  - Apply links go through a redirect endpoint with UTM tags.
  - Jobs missing from a feed are soft-deleted, and their open matches move to `closed`.
