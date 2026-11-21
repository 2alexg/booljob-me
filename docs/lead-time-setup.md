# Lead-time Setup Checklist

Accounts and approvals that take days or weeks. Tracked by task **S1-03** in the design doc (§9.1).

**Suggested order:**
1. Prerequisites (§0).
2. Privacy counsel and SMS gateway on day 1, because they take longest.
3. Vertex AI, LinkedIn, Google OAuth, and Maps during week 1.

## 0. Prerequisites (shared by most tasks)

- [ ] Registered business entity (ח.פ. or עוסק).
- [ ] Business credit card for cloud billing.
- [ ] Admin mailbox on Google Workspace (e.g. `admin@booljob.me`).
- [ ] Placeholder site on booljob.me with a draft privacy policy and terms page. Google and LinkedIn both require these links. A temporary draft is fine until counsel delivers the final text (§1).

## 1. Privacy counsel (blocks Sprint 2: needed before real CVs are collected)

- [ ] Shortlist 2–3 Israeli privacy/tech lawyers with Amendment 13 experience. Request a fixed-fee quote and turnaround time.
- [ ] Send the briefing pack:
  - [ ] Design doc §2 (privacy flow), §5 (AI processing), §7 (compliance).
  - [ ] Data map: what personal data is collected, where it is stored (Frankfurt), and the processors that touch it (Supabase, Google Cloud/Vertex AI, Vercel, Upstash, SMS gateway, Telegram with IDs only).
  - [ ] Note that Supabase and Vercel are US companies even though the data is hosted in the EU.
- [ ] Get answers to:
  - [ ] Database registration/notification obligations, and whether a DPO must be appointed.
  - [ ] Security level under the Protection of Privacy (Data Security) Regulations, 2017.
  - [ ] Whether data transfer to the EU and to US-owned processors is permitted, and the required Hebrew consent wording.
  - [ ] Whether match-notification emails/SMS need marketing consent under the anti-spam law (Communications Law §30A).
  - [ ] Whether AI matching complies with the Equal Employment Opportunities Law.
  - [ ] Whether scraping public ATS job posts and displaying company names is legal.
  - [ ] Whether the employer anti-circumvention terms are enforceable.
  - [ ] Whether the retention periods in §7 are acceptable.
- [ ] Receive the deliverables, all before Sprint 2 starts:
  - [ ] Privacy policy (Hebrew).
  - [ ] Terms of use (Hebrew).
  - [ ] Consent texts.
  - [ ] Employer terms.
  - [ ] Action list for any registration or DPO appointment.

## 2. Vertex AI (Gemini + embeddings)

- [ ] Create the GCP project, link billing, and set a budget alert.
- [ ] Enable the Vertex AI API (`aiplatform.googleapis.com`).
- [ ] Check that **Gemini 2.5 Flash** and **`gemini-embedding-001`** are available in `europe-west3` (Frankfurt). If not, pick the nearest named EU region and update design doc §3.2. Don't use the `global` endpoint, because it does not guarantee data residency.
- [ ] Check quotas:
  - [ ] Gemini 2.x mostly runs on dynamic shared quota: no per-project request is needed, but 429s are possible at peak. Provisioned Throughput is optional and not needed for the MVP.
  - [ ] Embedding models have per-project per-minute quotas. Check the Quotas page and request an increase if the first ingestion run would exceed them.
- [ ] Accept the Cloud Data Processing Addendum.
- [ ] Review Vertex AI zero-data-retention settings and disable prompt caching/logging that isn't needed, since prompts will contain CV text.
- [ ] Create separate staging and prod service accounts with only `roles/aiplatform.user`.

## 3. SMS gateway (OTP)

- [ ] Contact **InforUMobile** and **019** sales and open a business account (requires the company number).
- [ ] Request an alphanumeric sender ID (`Bool` or `BoolJob`, max 11 characters) and ask each provider:
  - [ ] Is sender-ID pre-registration required, and how long does it take?
  - [ ] Is there a REST API with delivery reports (DLR)?
  - [ ] What is the per-SMS price for Israeli numbers? Are test credits available?
  - [ ] Can sending be restricted to our IPs (servers in Frankfurt)?
  - [ ] What sending rate limits apply?
- [ ] Choose a provider and store separate staging and prod API keys in Secret Manager.
- [ ] Note: OTP messages are transactional. Whether match-notification SMS counts as marketing is a counsel question (§1).
- [ ] Integration happens in Sprint 2: Supabase Auth **Send SMS Hook** → FastAPI endpoint → gateway. Only the account and sender ID are needed now.

## 4. LinkedIn OAuth (a few days at most)

- [ ] Create a LinkedIn **Company Page** for Bool (required to create an app).
- [ ] Create the app at linkedin.com/developers and link it to the Company Page.
- [ ] Have a page admin approve the app verification request.
- [ ] Add the **"Sign In with LinkedIn using OpenID Connect"** product (self-serve, usually instant).
- [ ] Add redirect URLs for each environment: `https://<project-ref>.supabase.co/auth/v1/callback` (Supabase provider: LinkedIn (OIDC)).
- [ ] Set the privacy policy URL and app logo.
- [ ] Don't apply to partner programs (profile import, Talent APIs). They are slow and selective, and the MVP does not need them.

## 5. Google OAuth (a few business days)

- [ ] Verify the **booljob.me** domain in Google Search Console.
- [ ] Configure the OAuth consent screen: External, scopes `openid`, `email`, `profile` only.
- [ ] Add the authorized domain (booljob.me), privacy policy and terms URLs, and logo.
- [ ] Submit **brand verification** (a few business days; required to show the Bool name and logo). These basic scopes do not need the full security review.
- [ ] Create staging and prod OAuth clients with the Supabase callback URLs.

## 6. Google Maps Platform (quick)

- [ ] Create an API key restricted to the **Geocoding API** only.
- [ ] Restrict the key to the Cloud Run service (IPs or service account).
- [ ] Set a daily quota cap.
- [ ] Reminder: never store Google coordinates. Store only the resolved `locality_id` (design doc §5.C).
