# Product & Technical Specification Document: Bool (booljob.me)

## 1. Executive Summary & Brand Identity

* **Product Name:** **Bool**
* **Domain & Workspace:** booljob.me (managed via Google Workspace, with email aliases hello@booljob.me, hire@booljob.me, billing@booljob.me, and transactional email subdomain mail.booljob.me).
* **Core Concept:** An AI-powered, bidirectional, privacy-first job matching platform tailored for the Israeli market.
* **Target Audience:**
  * **Broad Israeli Workforce:** Ages 20–50+, spanning general/entry-level roles (sales, customer service, operations, hospitality) for younger job seekers, up to specialized, senior, and tech/engineering roles for older, experienced candidates.
  * **Employers & Recruiters:** Companies ranging from small/medium businesses without an ATS to high-tech companies and enterprises utilizing modern Applicant Tracking Systems.
* **Value Proposition:**
  * **For Candidates:** Eliminates endless scrolling through irrelevant job boards. Candidates upload a CV, complete a short AI-generated gap-filling questionnaire, and receive curated, high-relevance matches with clear explanations (*"Why this is a Bull's-eye for you"*), protected by strict employer anonymity.
  * **For Employers:** Zero-friction AI job posting and a low-risk **"Pay-per-Mutual-Match"** model. Recruiters only pay to unlock full CVs and contact details after both the recruiter and the candidate have mutually opted in.
* **Language & Accessibility:** Hebrew-first, fully RTL UI. All public and authenticated pages must comply with the Israeli accessibility regulations (IS 5568 / WCAG 2.0 AA), including an accessibility statement page. Arabic and Russian UI are out of MVP scope (see §10).

## 2. Core User Flows & Privacy Architecture (Double Opt-in Blind Matching)

To address the sensitivity of the Israeli job market (preventing an employer from discovering their current employee is job hunting, and enabling discreet executive/key-role replacements), **Bool** enforces a strict **Double Opt-in Progressive Disclosure** workflow for **direct-employer jobs**. Scraped ATS jobs use a separate, simpler flow (§2.2).

### 2.1 Employer Blocklist (Automatic & Manual)

* Blocking is by **`company_id`**, never by raw name string. Company names are resolved through a `company_aliases` table (Hebrew/English spellings, legal names, common abbreviations, e.g. "אינטל" / "Intel Israel" / "Intel Corp"), and blocks propagate through `parent_company_id` to subsidiaries and parents.
* During CV parsing, the AI extracts the candidate's current employer (`is_current = True`), resolves it to a `company_id`, and adds it to the candidate's blocklist (`candidate_blocked_companies`). Candidates can manually add more companies via an autocomplete over companies + aliases.
* Names that cannot be resolved to a known company are kept in `blocked_company_names_unresolved` and matched conservatively (normalized fuzzy match against company name + aliases). On a possible match, the job/company is excluded.
* Blocked companies never see the candidate's profile, not even anonymized, and their jobs are never matched to the candidate.

### 2.2 Scraped ATS Jobs (External Apply Flow)

Scraped jobs have no recruiter on Bool, so there is no double opt-in:

* `suggested` → `candidate_viewed` → `applied_external` (candidate clicked through to the ATS apply URL, tracked via a redirect endpoint) or `dismissed_by_candidate`.
* If a company claims its profile (`is_claimed = True`), its jobs are converted to `direct_employer` source going forward. Existing scraped-job matches stay in the external flow; new matches use the double opt-in flow.

### 2.3 Direct-Employer Jobs (Double Opt-in)

Either side may initiate:

> 1. **Stage 1a – Blind Candidate Discovery (Employer-initiated, free):**
>    * Recruiters view anonymized candidate cards for candidates with `ai_rerank_score >= 80` (§5.B).
>    * If interested, the recruiter clicks **"Express Interest"** (`status = 'employer_interested'`) at no cost.
> 2. **Stage 1b – Candidate-initiated Interest (free):**
>    * A candidate who sees a direct-employer job in their feed can click **"I'm Interested"** (`status = 'candidate_interested'`). The recruiter sees the anonymized card flagged as "Candidate interested" and can **Accept** (→ `mutual_interest`) or **Decline** (→ `declined_by_employer`).
> 3. **Stage 2 – Progressive Job Disclosure (Candidate):**
>    * On employer interest, the candidate is notified of a high-relevance match, initially seeing role details, region, salary range, and the AI match explanation *without* the company name.
>    * The candidate clicks **"Reveal Full Job Details"** (`status = 'candidate_revealed_job'`). Unless the role is confidential (`is_confidential = True`, in which case a generic company profile is shown), the company name is revealed.
>    * The candidate makes a binary choice:
>      * **Decline (`declined_by_candidate`):** The match is closed. Candidate identity remains hidden, and the employer pays nothing.
>      * **Accept (`mutual_interest`):** The candidate confirms interest, unlocking the paid reveal option for the employer.
> 4. **Stage 3 – Paid Contact Unlock (Employer):**
>    * Only matches in `mutual_interest` can be unlocked. The recruiter spends wallet credits to reveal the candidate's full name, phone, email, WhatsApp link, and a 15-minute Signed URL to the CV (`unlocked_by_employer`).

### 2.4 Anonymized Candidate Card (Re-identification Protection)

In a small market, a rare role + exact city + exact years of experience can identify a person. Cards therefore show only coarsened attributes:

* **Region** (e.g. Center, Sharon, North, Jerusalem, South) instead of city.
* **Experience bands** (0–2, 3–5, 6–10, 10+ years) instead of exact years.
* Normalized skills and work-model preference.
* An AI-generated summary that must pass a **de-identification check** before display: a rule-based filter (names, emails, phones, URLs, any `companies`/alias names, schools) followed by an LLM check for unique projects, products, patents, military unit names, or awards. Summaries that fail are regenerated with a stricter prompt or replaced by a skills-only card.
* Never shown: name, contact info, photo, age/birth date, previous employer names, education institution names.

### 2.5 Match Lifecycle (Expiry & Closure)

Every non-terminal state has an exit, so neither side is left waiting indefinitely:

| State | Exit | Trigger |
| :---- | :---- | :---- |
| `employer_interested` / `candidate_revealed_job` | `expired` | No candidate decision within 14 days |
| `candidate_interested` | `expired` | No employer decision within 14 days |
| `mutual_interest` | `expired` | Employer does not unlock within 14 days; candidate is notified |
| Any pre-unlock state | `withdrawn_by_candidate` | Candidate withdraws |
| Any pre-unlock state | `closed` | Job filled or soft-deleted (`is_active = FALSE`) |
| `candidate_interested` | `declined_by_employer` | Recruiter declines |

Expiry windows are configuration values. Expiry is enforced by the nightly lifecycle worker (§3).

### 2.6 Off-platform Bypass

After the company name is revealed, a candidate may apply directly, and a recruiter may try to find a candidate from a card. Mitigations in MVP: coarsened cards (§2.4); terms of service for employers prohibiting circumvention of matches surfaced through Bool; logging of reveal events for attribution. Whether to add a placement-attribution fee is an open decision (§10).

### 2.7 Authorization Rules (as implemented)

The rules in §2.1–§2.5 are implemented in one place, `api/src/bool_api/policy/`, and covered by exhaustive table-driven tests. Where §2.1–§2.5 left a case open, the conservative choice below applies.

**Transitions.**
* A candidate may dismiss a scraped-job suggestion without opening it (`suggested → dismissed_by_candidate`).
* A candidate may decline employer interest without revealing the job (`employer_interested → declined_by_candidate`), but accepting requires the reveal first.
* Withdrawal is allowed from every open pre-unlock state, including `suggested`.
* `expired` and `closed` are set only by the system worker.
* `unlocked_by_employer` is the only paid transition. Billing must confirm the debit.

**Expiry clock.** Entering `employer_interested`, `candidate_interested` or `mutual_interest` starts a fresh 14-day clock. Revealing the job keeps the clock started by employer interest.

**What the employer sees of the candidate** (direct-employer jobs only; employers never see scraped-job matches):

| State | Employer view |
| :---- | :---- |
| `suggested` | Anonymized card, only if `ai_rerank_score >= 80`; otherwise nothing |
| `employer_interested`, `candidate_interested`, `candidate_revealed_job`, `mutual_interest` | Anonymized card |
| `unlocked_by_employer` | Full identity and contact details (the only such state) |
| `declined_by_candidate`, `declined_by_employer`, `expired` | Status only, no candidate fields |
| `withdrawn_by_candidate`, `closed` | Nothing: the match disappears for the employer |

If the company is on the candidate's blocklist, the employer sees nothing and cannot act, in every state.

**What the candidate sees of the company:**
* Scraped jobs: always named.
* Direct-employer jobs:
  * Named only in `candidate_revealed_job`, `mutual_interest` and `unlocked_by_employer`.
  * Confidential jobs show a generic profile in those states.
  * Hidden in all other states, including after the match ends.

**Other rules:**
* A candidate sees a `suggested` match only if `ai_rerank_score >= 75`.
* Nobody may act on a match they cannot see.
* **Admins** see anonymized cards only. Revealing identity to an admin needs a separate, audited path.
* **Candidate fields** pass through an allowlist: an anonymized card exposes only region, experience band, skills, work models and the de-identified summary. Any new field stays hidden until it is added to the allowlist.

## 3. System Architecture & Managed Cloud Infrastructure

To minimize server maintenance, OS patching, and upfront infrastructure costs while enforcing strict security and SEO requirements, **Bool** uses a **Three-Tier Managed Cloud Architecture**:

| Layer | Technology & Managed Provider | Key Responsibilities & Security Controls |
| :---- | :---- | :---- |
| **1. Public Web & BFF Edge** | **Next.js (App Router)** hosted on **Vercel** (booljob.me, hire.booljob.me) | • **Public SSR & SEO:** Renders public job pages (/jobs/[slug]) with dynamic Open Graph tags (for rich WhatsApp/LinkedIn previews) and JSON-LD (JobPosting schema for Google for Jobs). • **BFF Security Proxy:** Stores auth tokens in HttpOnly, Secure, SameSite=Strict cookies and forwards private API calls via /api/proxy/* with a secret server-side header (X-Internal-Secret). |
| **2. Private Application Backend** | **Python (FastAPI)** on **Google Cloud Run** (API service + separate worker service) | • **Zero-Trust Gateway:** Rejects any request missing X-Internal-Secret (403 Forbidden) and validates Supabase JWTs. • **Authorization layer:** All access control lives here (see §3.1). • **AI Orchestration:** CV parsing, quiz generation, embeddings, batch reranking, ATS scraping run in the worker service. • **Admin Alerts:** Operational alerts via a dedicated **Telegram Bot** (no PII in alert payloads, only IDs). |
| **3. Data, Auth & Storage Tier** | **Supabase** (PostgreSQL + pgvector + PostGIS + Auth + Storage) & **Upstash** (Redis + QStash) | • **Database:** Single PostgreSQL instance with pgvector (semantic similarity), PostGIS (commute radius), and RLS that denies all access to `anon`/`authenticated` roles. • **Private Storage:** CVs in a private bucket, accessible only via 15-minute Signed URLs. • **Redis:** IP/phone rate limiting and caching. • **QStash:** HTTP-push background job queue that invokes the worker service (works with Cloud Run scale-to-zero, with retries and dead-letter queue). |
| **4. Scheduled Workers** | **QStash schedules / GitHub Actions** | • Triggers nightly ATS scraping, nightly batched reranking, match expiry, and data-retention cleanup via authenticated internal endpoints. |

### 3.1 Authorization Model

The browser never queries Supabase directly, and FastAPI connects with the **service role, which bypasses RLS**. RLS is therefore defense-in-depth only. **All authorization is enforced in FastAPI code**, centralized in a single policy module (no ad-hoc checks in route handlers):

* Which matches a user may see, by role and match state.
* Blocklist enforcement on every candidate/job query surfaced to an employer.
* Field-level redaction of candidate data by match state (anonymized card vs. unlocked profile).
* Unlock gating (only `mutual_interest`, only the owning employer, idempotent debit).

The policy module requires dedicated test coverage for every state × role combination.

### 3.2 Hosting Regions

All services are hosted in **Western Europe, co-located in Frankfurt**, so that API ↔ database queries never cross regions. Frankfurt is also the lowest-latency major Western European cloud region from Israel, and every provider below supports it.

| Service | Region |
| :---- | :---- |
| Supabase (DB, Auth, Storage) | `eu-central-1` (Frankfurt) |
| Google Cloud Run (API + worker) | `europe-west3` (Frankfurt) |
| Vertex AI (Gemini, embeddings) | `europe-west3`, or the nearest EU region where the chosen models are available (verified in S1-08) |
| Vercel serverless functions (BFF) | `fra1` (Frankfurt) |
| Upstash Redis / QStash | `eu-central-1` (Frankfurt) |

Upstash details: Redis databases are **Regional** (never Global, which replicates outside the EU) with eviction off. QStash uses the Frankfurt endpoint `https://qstash-eu-central-1.upstash.io`. QStash tokens and signing keys are per Upstash account, so **prod uses a separate Upstash team** and staging can never send or accept prod jobs.

EU hosting is a cross-border transfer of Israeli personal data and is covered by the consent and counsel review in §7.

### 3.3 Repository & Tooling

* **Single monorepo** for all code: `web/` (Next.js), `api/` (FastAPI API + worker, one image with two entrypoints), `supabase/` (migrations, seed data, config), `eval/` (offline evaluation scripts and synthetic data).
* **Supabase CLI owns the database schema.** All schema changes (tables, pgvector/PostGIS extensions, indexes, RLS deny-all policies, seed data) are SQL migrations in `supabase/migrations/`, applied with the Supabase CLI. FastAPI never runs migrations.
* Separate Supabase projects for **dev, staging, and prod**.

## 4. Authentication & Dual-Channel Verification

* **Unified Multi-Role Identity:** A single user (`users` table) can hold multiple roles (`roles: ['candidate', 'employer']`) and link multiple OAuth providers (`user_oauth_accounts`: Google, LinkedIn) alongside password or OTP login.
* **Mandatory Dual Verification:** An account cannot transition to `status = 'active'` until **both** `email_verified = True` and `phone_verified = True`:
  * Signing in via Google/LinkedIn verifies the email automatically and prompts for an Israeli mobile number (`+9725...`, E.164) + SMS OTP.
  * Signing in via SMS OTP verifies the phone and prompts for email verification.
* **SMS OTP via Supabase Auth:** Phone OTP uses Supabase Auth's built-in phone provider with a **Send SMS Hook** that delivers codes through an Israeli SMS gateway (InforUMobile or 019). Bool does not generate, hash, or store OTP codes itself. Supabase handles code generation, expiry, and attempt limits. Upstash Redis adds extra IP and per-phone rate limits in front of the OTP request endpoint.
* **Account Linking & Collision Handling:** Email lookups are case-insensitive (`LOWER(email)`), linking OAuth logins to existing accounts automatically. Phone numbers are unique.
* **Account Merge:** If a user verifies a phone already claimed by another verified account, merging requires proof of ownership of **both** accounts: the user must be authenticated in the current account **and** complete a fresh login to the existing account (OTP to its phone and a verification link to its email). Merges are logged and the existing account's email receives a notification.

## 5. AI Pipelines & Prompt Engineering

### A. Candidate Onboarding & Dynamic Gap-Filling Quiz

> 1. **Extraction:** PyMuPDF / python-docx extracts raw text from uploaded PDF/DOCX CVs (with multimodal LLM fallback for scanned PDFs).
> 2. **Structured Gap Analysis (Gemini 2.5 Flash + Pydantic):**
>    * Extracts personal metadata, work history, education, normalized `skills_tags`, `experience_years`, and current employer (for auto-blocking, §2.1).
>    * **Does not extract or store** age, birth date, photo, gender, marital status, religion, or military unit details. The prompt instructs the model to drop them, and the Pydantic schema has no fields for them (Equal Employment Opportunities Law).
>    * Identifies missing hard constraints (salary expectations, preferred work model, shift availability/mobility for junior roles) and career aspirations.
>    * Generates a tailored **5–7 question quiz** in Hebrew: **4–5 multiple-choice questions** (`single_choice` / `multiple_choice` with direct DB constraint mappings) + **1–2 open-ended questions** (`open_text`) maximum.
> 3. **Profile Vectorization:** Combines extracted CV history and quiz answers into a unified semantic summary (`profile_summary_for_ai`), generates a 1536-dimension embedding with **`gemini-embedding-001` (`output_dimensionality = 1536`)**, and activates the candidate. A single embedding model is used for both candidates and jobs. Changing models requires re-embedding everything. The model choice is gated on a Sprint 1 offline Hebrew retrieval evaluation against `text-embedding-3-small` (S1-18).
>    * **Evaluation data:** The evaluation uses **LLM-generated synthetic Hebrew CVs only**. They live in `eval/` and are **never uploaded to the system**: not to Supabase, not to Storage, not to any environment.

### B. Two-Stage Hybrid Matching & Batch Reranking

**Thresholds (single source of truth):**

| Name | Value | Applies to |
| :---- | :---- | :---- |
| `vector_similarity_score` cutoff | ≥ 0.75 cosine similarity | Stage 1 retrieval |
| `ai_rerank_score` candidate-feed threshold | ≥ 75 | Shown in candidate feed, with Hebrew explanation |
| `ai_rerank_score` recruiter threshold | ≥ 80 | Shown to recruiters as anonymized cards |

> 1. **Stage 1 – Fast SQL + pgvector Retrieval:**
>    * Filters active jobs/candidates by hard constraints: PostGIS commute distance (`ST_DWithin`), `work_model`, `min_salary_expected`, and the blocklist (§2.1).
>    * **Missing data:** Jobs with no salary pass the salary filter and are labeled "salary not listed". Jobs with no parseable location are only matched if `work_model = 'remote'`; otherwise they are held out until location normalization succeeds.
>    * Ranks by cosine distance (`embedding <=> target_embedding`) and selects the Top 15–20 above the 0.75 cutoff.
> 2. **Stage 2 – Batch LLM Reranking & Explainability:**
>    * Sends the candidate profile and the Top 15–20 jobs in a single batch call to Gemini 2.5 Flash.
>    * Evaluates deal-breakers, seniority alignment, and quiz preferences to assign `ai_rerank_score` (0–100).
>    * For matches scoring ≥ 75, generates a concise, personalized Hebrew explanation (≤ 25 words) connecting concrete CV/quiz details to the job requirements.
>    * Results are pre-computed into the `matches` table for instant feed loading.
> 3. **Cost Controls:**
>    * **Triggers:** Candidate profile updates and direct-employer job postings trigger reranking immediately. **Scraped job ingestion does not trigger per-job reranking.** New scraped jobs are batched into one nightly rerank pass per candidate.
>    * **Active candidates only:** Reranking runs only for candidates active in the last 30 days.
>    * **Daily token budget:** A configurable global daily LLM token budget. When exceeded, reranking pauses (Stage 1 results are still stored) and a Telegram alert fires.

### C. Locations

* **Localities:** Seeded from the Israeli government localities list (data.gov.il / CBS), with Hebrew and English names, locality code, and district. Spelling variants ("Herzliya", "הרצליה", "Herzliya Pituach") are stored in `locality_aliases`.
* **Regions:** Product regions (Center, Sharon, North, Haifa, Jerusalem, South, etc.) are a manually maintained mapping from locality to region, because CBS districts don't match how job seekers think (e.g. there is no "Sharon" district).
* **Coordinates:** Matching uses **locality-level points** (one point per locality), which is precise enough for commute-radius filtering. Points come from the government data if it includes them, otherwise from OpenStreetMap (ODbL, stored with attribution).
* **Free-text resolution:** Job and candidate locations resolve to a `locality_id` by alias lookup first. Only on a miss is the **Google Geocoding API** called, and its result is mapped to the nearest locality. Bool stores only the `locality_id`, never Google's coordinates, because Google Maps Platform terms do not allow storing coordinates permanently.
* Special values: "Remote", "Israel" (no specific city), and multi-location postings.

### D. Skills Taxonomy

* No suitable public Hebrew skills taxonomy exists, so Bool grows its own: a `skills` table (canonical English key, Hebrew label, English label, category) and `skill_aliases`.
* Seeded with ~300 common skills across target role families (LLM-drafted, human-reviewed).
* During CV and job normalization, the LLM maps extracted skills to existing skill IDs. Skills it cannot map are inserted as `status = 'pending'` and reviewed in the admin dashboard (approve, reject, or merge into an existing skill as an alias). Only approved skills are used in matching.

### E. Full AI Audit Logging (ai_interaction_logs)

* Every LLM interaction (CV analysis, quiz generation, quiz submission summary, de-identification checks, and job reranking) is logged with `session_id`, `prompt_version`, `system_prompt`, `user_input_payload`, `ai_raw_output`, token counts, latency, and admin review fields (`admin_reviewed`, `admin_quality_rating`) to support quality assurance and prompt A/B testing.
* **This table holds full CV text and is the largest PII store in the system.** Access is restricted to admin roles, every admin read is logged, and payloads are redacted or deleted per the retention policy (§7).

## 6. ATS Scraping & Job Ingestion Pipeline

To solve the marketplace cold-start problem and build organic SEO inventory:

> 1. **Company Discovery:** A paid search API (e.g. Brave Search API or SerpAPI; not automated Google queries, which violate Google's ToS) runs queries such as `site:boards.greenhouse.io`, `site:jobs.lever.co`, `site:comeet.com/jobs` + Israeli locations. Public VC/startup directories also populate the `companies` table with ATS identifiers and aliases.
> 2. **ATS Connectors (Strategy Pattern):** Only **free, open, unauthenticated** public job-board APIs are used. MVP connectors: **Greenhouse** (`boards-api.greenhouse.io`) and **Lever** (`api.lever.co/v0/postings`). **Comeet** is added only if its careers API is usable without per-company credentials (checked in S1-15). **Ashby**'s public posting API is the next candidate. Nightly workers filter exclusively for Israel-based or Israel-remote roles. Each connector's terms of use are reviewed before launch.
> 3. **Attribution Tracking:** All external apply URLs are tagged with `?utm_source=booljob.me&utm_medium=ai_match` and served through a Bool redirect endpoint (records `applied_external`, §2.2) to surface **Bool** inside recruiters' ATS dashboards.
> 4. **LLM Normalization & Deduplication:** SHA-256 content hashing skips unchanged jobs. New/updated jobs are parsed via LLM into structured fields (`title_original` kept verbatim in the posting's language, plus normalized `title_he`; `locality_id` via §5.C; work model; experience years; salary range; skill IDs via §5.D) and vectorized. Many Israeli tech jobs are posted in English: the original title and description are always kept and shown as posted, and the embedding input is built the same way for every job (normalized structured fields + original description).
> 5. **Lifecycle Sync:** Jobs no longer returned by a company's ATS feed are soft-deleted (`is_active = FALSE`), and their open matches move to `closed`.

## 7. Privacy, Compliance & Data Retention

Bool processes CVs at scale and sends personal data to an LLM provider outside Israel, so the Privacy Protection Law as amended by **Amendment 13 (in force since August 2025)** applies. **All items below require review by Israeli privacy counsel before launch.**

* **Consent:** Explicit, separate consent at onboarding for (a) CV processing by AI, including transfer to Google (Gemini) outside Israel, and (b) matching and anonymized exposure to employers. Consent text and version are stored per user.
* **LLM provider terms:** Use Gemini via a paid tier / Vertex AI with contractual no-training-on-customer-data terms and an EU or other approved data region where available.
* **Database obligations:** Assess database registration/notification requirements and whether a Data Protection Officer must be appointed. Maintain a database definition document and a security procedure.
* **Data subject rights:** Self-service data export and account deletion. Deletion removes the CV file, parsed data, embedding, and contact details, and anonymizes match records retained for billing.
* **Retention (proposed defaults, configurable):**
  * Inactive candidate profiles: CV and parsed data deleted after 24 months without login, with a reminder email 30 days before.
  * `ai_interaction_logs`: PII fields redacted after 90 days. Metadata (prompt version, tokens, latency, ratings) kept for QA.
  * Billing records (`credit_transactions`, billable `analytics_events`): kept as required by tax law, with candidate identifiers pseudonymized.
* **Non-discrimination:** Age, gender, and other protected attributes are never extracted, stored, used in matching/reranking, or shown to employers (§5.A).

## 8. Database Schema Summary (PostgreSQL + pgvector + PostGIS)

* **users & user_consents:** Core identity (keyed to Supabase `auth.users`), dual verification flags (`email_verified`, `phone_verified`), multi-role array (`roles`), and versioned consent records. OAuth provider links are not duplicated: they live in Supabase's `auth.identities`.
* **candidates:** `locality_id` (region and commute point derived from it), CV URL, parsed JSON, dynamic quiz questions & answers, hard constraints (`min_salary_expected_monthly_ils`, `max_commute_km`, `preferred_work_models`, `blocked_company_names_unresolved`), skills via `candidate_skills`, resolved blocklist via `candidate_blocked_companies`, `last_active_at`, and `vector(1536)` embedding. **No birth date.**
* **companies, company_aliases & employers:** Company metadata, `parent_company_id`, aliases (Hebrew/English names), ATS configuration, `is_claimed` status, tax ID (ח.פ.), billing email, payment gateway token, and `credit_balance_agorot`.
* **jobs:** Supports both `scraped_ats` and `direct_employer` sources, `title_original`, `title_he`, `is_confidential` flag, structured requirements, `locality_id` (nullable), `cost_per_action_agorot`, and `vector(1536)` embedding.
* **localities, locality_aliases & regions:** Government localities seed, spelling variants, locality-level `GEOGRAPHY` point, and locality → product region mapping (§5.C).
* **skills & skill_aliases:** Self-grown taxonomy with `status` (`approved` / `pending` / `rejected`) (§5.D).
* **match_feedback:** Candidate's relevance rating per match (`relevant` / `not_relevant`, optional reason), which feeds the Phase 1 success metric (§9).
* **matches:** Tracks the state machine for both flows. External flow (§2.2): `suggested → candidate_viewed → applied_external / dismissed_by_candidate`. Double opt-in flow (§2.3): `suggested → employer_interested → candidate_revealed_job → mutual_interest → unlocked_by_employer`, `suggested → candidate_interested → mutual_interest`, plus terminal `declined_by_candidate`, `declined_by_employer`, `withdrawn_by_candidate`, `expired`, `closed` (§2.5). Also stores `vector_similarity_score`, `ai_rerank_score`, `ai_explanation_he`, `status_changed_at`, and `expires_at`. Every transition is recorded in **match_status_events** (from/to status, actor). The DB only checks that a status belongs to its flow. Legal transitions are enforced by the FastAPI policy module.
* **analytics_events & credit_transactions:** Idempotent billing event log (enforced via unique partial index on billable events) and prepaid wallet ledger linked to Israeli payment/invoicing providers (Morning / Meshulam / CardCom) with row-level locking (`SELECT ... FOR UPDATE`) to prevent double charges.
* **ai_interaction_logs & ai_log_access:** Audit trail of all LLM inputs, outputs, prompt versions, and admin QA ratings, subject to the retention policy (§7). Every admin read is recorded in `ai_log_access`.
* **Money units:** Billing amounts are integer agorot. Salaries are whole shekels per month (`*_monthly_ils`).

## 9. Phased MVP Execution Roadmap

The MVP is split into two phases. **Phase 1 validates matching quality with candidates and scraped jobs only.** Phase 2 (recruiter portal and billing) starts only once Phase 1 shows that candidates find the matches relevant.

**Phase 1 success metric:** the **share of matches rated relevant**, i.e. `relevant` ratings ÷ all ratings in `match_feedback`, across beta candidates. Every match card in the candidate feed has a 👍/👎 relevance control. The target value that unlocks Phase 2 is an open decision (§10).

### Phase 1 – Candidate MVP (Weeks 1–6)

> 1. **Sprint 1 (Weeks 1–2) – Core Infrastructure & ATS Ingestion:** see the task breakdown in §9.1.
> 2. **Sprint 2 (Weeks 3–4) – Authentication & Candidate Onboarding:**
>    * Supabase Auth (Google, LinkedIn, Email, phone OTP via Send SMS Hook) with dual verification, account linking, and safe merge.
>    * Consent flow, CV upload, AI gap-analysis quiz generator, Typeform-style mobile quiz UI (RTL, accessible), profile vectorization.
> 3. **Sprint 3 (Weeks 5–6) – Matching Engine & Candidate Portal:**
>    * Two-stage matching with cost controls and nightly batched reranking.
>    * Mobile-first Candidate Feed with the external apply flow and 👍/👎 relevance rating (`match_feedback`), public SSR job pages (/jobs/[slug]), accessibility statement, data export/deletion.
>    * Admin QA dashboard (/admin/ai-logs). Closed beta with 50–100 Israeli candidates.

### Phase 2 – Recruiter MVP (Weeks 7–10)

> 4. **Sprint 4 (Weeks 7–8) – Recruiter Portal & Double Opt-in:**
>    * Desktop-first Recruiter Portal (hire.booljob.me): company claiming, AI job draft parser, anonymized candidate cards with de-identification check, employer- and candidate-initiated interest, match expiry.
> 5. **Sprint 5 (Weeks 9–10) – Billing & Soft Launch:**
>    * Atomic credit wallet with free pilot credits, then Israeli payment gateway webhooks and invoicing. Employer ToS (anti-circumvention). Recruiter soft launch.

### 9.1 Sprint 1 Task Breakdown

**Sprint goal:** By the end of week 2, staging ingests real Israeli jobs every night from at least two ATS sources. Those jobs are normalized, geo-resolved, skill-tagged, and embedded, and the embedding model has been chosen based on the offline evaluation.

**A. Foundation**

* **S1-01 Monorepo scaffold.** `web/` (Next.js App Router, TypeScript, pnpm), `api/` (FastAPI, uv, ruff, pytest), `supabase/` (`supabase init`), `eval/`. GitHub Actions CI: lint + tests for web and api, plus `supabase db reset` against the local Supabase stack to validate migrations.
  *Done when:* CI is green on a trivial app in each package.
* **S1-02 Cloud environments.** Supabase dev/staging/prod in `eu-central-1`. GCP project with Cloud Run (`europe-west3`), Artifact Registry, and Secret Manager. Upstash Redis + QStash in `eu-central-1`. Vercel project with functions in `fra1`. Secrets wired into each environment.
  *Done when:* staging exists end to end and no secrets are stored in the repo.
* **S1-03 Long-lead registrations (start day 1).** Follow the checklist in [`docs/lead-time-setup.md`](lead-time-setup.md): privacy counsel for §7, Israeli SMS gateway account + sender ID, Vertex AI setup and quotas, LinkedIn and Google OAuth apps, Google Maps Platform key (Geocoding only, restricted).
  *Done when:* all requests are submitted and tracked.
* **S1-04 Schema migration v1.** Extensions (`vector`, `postgis`). Tables from §8, including `localities`, `skills`, and `match_feedback`. Phase 2 tables are created minimally. Indexes: HNSW on embeddings, GIST on geography, the unique partial index for billable events. RLS enabled with deny-all on every table.
  *Done when:* `supabase db reset` passes locally and in CI, and a test asserts that `anon` and `authenticated` cannot read or write any table.
* **S1-05 FastAPI skeleton.** API and worker entrypoints in one image. `X-Internal-Secret` middleware (403), Supabase JWT validation, service-role DB access, health check, structured logging with PII scrubbing.
  *Done when:* deployed to Cloud Run staging, a request without the secret gets 403, and one with a valid JWT reaches a test route.
* **S1-06 Authorization policy module + match state machine.** One central module: the match state transitions from §2.2/§2.3/§2.5 as code, and role × state visibility and redaction rules.
  *Done when:* table-driven tests cover every state × role combination and every illegal transition is rejected.
* **S1-07 Background jobs & alerts.** QStash dispatch helper, signature verification on worker endpoints, retries + dead-letter queue, nightly schedules. Telegram bot helper that sends IDs only, never PII. Alerts on worker failure, DLQ, and the nightly ingestion summary.
  *Done when:* a test job fails, retries, lands in the DLQ, and triggers a Telegram alert.
* **S1-08 LLM client wrapper.** Vertex AI clients for Gemini 2.5 Flash and embeddings in the EU region (confirm model availability in `europe-west3`, else pick the nearest EU region and update §3.2). Every call is logged to `ai_interaction_logs` with `prompt_version`, tokens, and latency. Daily token budget counter and Telegram alert when exceeded.
  *Done when:* a test prompt round-trips, its log row is written, and the budget cutoff works.

**B. Reference data**

* **S1-09 Localities & regions seed.** Import the government localities list (Hebrew/English names, code, district). Locality points from the government data or OpenStreetMap. Manual locality → region mapping. Seed common spelling variants into `locality_aliases`.
  *Done when:* the seed loads in a migration and test cases ("Herzliya", "הרצליה", "Herzliya Pituach", "Tel Aviv-Yafo", "ת״א") resolve to the right locality.
* **S1-10 Location resolver.** Free text → `locality_id`, alias lookup first, Google Geocoding fallback mapped to the nearest locality. Handles "Remote", "Israel", hybrid strings, and multi-location postings. Google coordinates are never stored.
  *Done when:* ≥ 95% of locations from a sample of 200 scraped jobs resolve correctly (spot-checked).
* **S1-11 Skills taxonomy v0.** `skills` / `skill_aliases` with ~300 seeded skills (LLM-drafted, human-reviewed). Normalization step maps extracted skills to IDs and inserts unknown skills as `pending`. CLI script to approve, reject, or merge pending skills (admin UI comes in Sprint 3).
  *Done when:* normalization of a 50-job sample maps ≥ 80% of extracted skills to approved IDs.

**C. Job ingestion**

* **S1-12 Company discovery.** Search API integration (Brave Search API or SerpAPI) for Greenhouse/Lever/Comeet/Ashby + Israel queries. Extract ATS board identifiers, upsert `companies` + ATS config, seed `company_aliases` (Hebrew/English names).
  *Done when:* ≥ 200 Israeli companies with a verified ATS board are loaded.
* **S1-13 Connector interface + Greenhouse.** Strategy-pattern connector interface (`list_jobs(company) → RawJob[]`). Greenhouse public boards API connector with an Israel / Israel-remote filter.
  *Done when:* it runs against the discovered Greenhouse companies with recorded-response tests.
* **S1-14 Lever connector.** Public postings API with the same interface and Israel filter.
  *Done when:* same as S1-13.
* **S1-15 Comeet / Ashby check (days 1–2).** Determine whether Comeet's careers API is usable without per-company credentials. If yes, build the connector. If not, document the finding and build Ashby instead, if time allows.
  *Done when:* the decision is recorded in §6.
* **S1-16 Ingestion pipeline.** Per company: fetch → SHA-256 content hash (skip unchanged) → LLM normalization (`title_original` + `title_he`, `locality_id` via S1-10, work model, experience, salary, skill IDs via S1-11) → embedding → upsert. Soft-delete jobs missing from the feed and move their open matches to `closed`. UTM-tagged apply URLs. Nightly QStash schedule with a Telegram summary (jobs added / updated / removed / failed).
  *Done when:* two consecutive nightly runs succeed on staging, the second one skips unchanged jobs, and active Israeli jobs are normalized and embedded.

**D. Embedding evaluation (offline)**

* **S1-17 Synthetic CV set.** Script that generates ~150 Hebrew CVs with an LLM, spread across role families (sales, customer service, operations, hospitality, tech) and seniority levels. Each CV comes with ground-truth target roles. A human spot-checks ~30 for realism. Stored only in `eval/data/`. **Never uploaded to Supabase, Storage, or any environment.**
  *Done when:* the set and generation script are committed under `eval/`.
* **S1-18 Embedding model comparison.** Offline: embed the synthetic CVs and a snapshot of ingested jobs with `gemini-embedding-001` (1536 dims) and `text-embedding-3-small`. Compare recall@20 and nDCG@20 against the ground-truth roles, plus a Hebrew-vs-English job subset. Embeddings stay local to `eval/`.
  *Done when:* there is a short report in `eval/` and the decision is recorded in §5.A. If the result changes the model, S1-16 re-embeds.

### 9.2 Lead-time Items Outside Sprint 1

Privacy counsel sign-off on §7 is required **before Sprint 2 collects real CVs**.

## 10. Open Decisions

* **Phase 1 success target:** The share-of-matches-rated-relevant value that unlocks Phase 2, plus a minimum number of ratings for the number to be meaningful (proposal: ≥ 60% relevant over ≥ 500 ratings).
* **Bypass monetization:** Whether to add a placement-attribution fee or other mechanism beyond ToS for hires that originate on Bool but bypass the paid unlock (§2.6).
* **Expiry windows:** Confirm the 14-day defaults (§2.5).
* **Retention periods:** Confirm with counsel (§7).
* **Additional UI languages:** Whether and when to support Arabic and Russian.
