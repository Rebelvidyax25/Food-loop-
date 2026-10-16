# FoodLoop

FoodLoop is a small food donation coordination prototype for a college hackathon. It connects donors with verified community organizations, shows explainable pickup matches, and tracks requests through a confirmed handover.

**The application does not certify that food is safe.** Donors must provide accurate handling information and organizations must make their own decisions. Missing allergen/storage information and expired listings are not claimable.

## Problem and workflow

Surplus food can go unused while community organizations need a timely way to discover suitable donations. FoodLoop supports one complete flow:

1. A donor posts food, quantity, preparation time, storage details, allergens and a pickup deadline.
2. Matching excludes ineligible organizations and lists the remaining candidates with transparent scores.
3. A verified recipient requests the donation.
4. The donor accepts and marks it ready for pickup.
5. The recipient or donor confirms the actual handover; only then do impact totals change.

## Architecture

- Python 3.12, FastAPI and Pydantic API validation.
- Vanilla HTML, CSS and JavaScript served from the same FastAPI origin.
- Rule-based deterministic matching in `backend/matching.py`.
- A lock-protected in-memory demo repository by default; optional Supabase PostgreSQL/Auth integration.
- Pytest and FastAPI TestClient tests; no live Supabase credentials are needed for tests.

## Features

- Responsive donation board with search, category, location, quantity, deadline and status filters.
- Donation form with timezone-aware dates, handling and allergen fields plus a donor suitability attestation.
- Safety information status and administrative review queue.
- Explainable eligible-recipient match scores.
- Authorized request, acceptance, pickup-ready, cancellation and handover transitions.
- Pickup timelines, impact dashboard and admin review view.
- Supabase bearer-token authentication and database-backed records when configured.

## Matching formula

Eligible organizations are ranked on a 0–100 score. Initial adjustable weights are:

| Component | Weight |
|---|---:|
| Distance | 35% |
| Urgency | 25% |
| Quantity suitability | 25% |
| Availability and pickup window | 15% |

Eligibility is checked before score ranking: the organization must be verified, available, compatible with the donation category and quantity, have sufficient pickup capacity, and be able to collect before the deadline. Safety-ineligible donations do not receive matches. Distance uses a straight-line haversine estimate only when both locations have coordinates; otherwise the distance component uses a neutral score and is explicitly marked unavailable. It is not a travel-time estimate. These weights and calculations are demonstration assumptions, not validated operational guidance.

## Food safety limitations

FoodLoop only checks that safety-related information is present and that deadlines are in the future. It does not prescribe universal storage durations, assess actual handling, or certify food as safe. Unknown allergens, incomplete storage descriptions and expired deadlines are flagged or require review. An administrator can resolve a review only after a human assessment; they should not treat the action as a safety certification.

Donors must attest that food is edible and suitable before posting. Clearly questionable handling descriptions (for example, food left out or reported as spoiled) require human review. This text screening is deliberately conservative and is not a safety decision.

## Local setup and demo mode

From the project directory in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Open `http://127.0.0.1:8000`. The demo starts with synthetic records and no credentials:

- Demo College Canteen (donor)
- Demo Event Organizer (donor)
- Demo Harvest Community Kitchen (verified recipient)
- Demo Neighborhood Pantry (verified recipient)
- Demo Community Outreach (verified recipient; coordinates unavailable)
- Demo Organization Awaiting Review (unverified)
- Demo Administrator

Use the role selector in the header. This is only a local judging convenience and is **not authentication**. The demo includes an eligible 30-portion donation, an eligible 40-portion donation, a listing pending safety review, an expired listing and a completed sample donation. Sample data and its initial impact are synthetic. In-memory changes are not shared between deployments and may not survive restarts.

Judge workflow: switch to a recipient and request one available donation; switch to its donor and accept it, then mark it ready; switch back to that recipient and confirm the handover. The impact count and portion total then update.

A claim reserves the whole listing so another organization cannot claim its remaining quantity. Cancelling releases the listing only when its pickup deadline is still in the future; expired food is never reopened.

## Supabase setup

1. Create a Supabase project and run [`supabase/schema.sql`](./supabase/schema.sql) in its SQL Editor.
2. Configure Supabase Auth users, then create their `public.profiles` records and recipient `public.organizations` records. Recipient profiles must point to the corresponding organization. Admin profile assignment is an administrative operation.
3. Copy `.env.example` to `.env` and set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY`. The service-role key is server-side only and must never be put in frontend JavaScript.
4. Restart FastAPI. The application selects Supabase storage when URL and service-role key are both present. If only one is set, startup fails with a configuration error; with neither, demo mode is used.

The browser signs in through Supabase Auth using the anon key. The backend verifies the returned bearer token and obtains the role from `public.profiles`; browser-supplied role headers are ignored in Supabase mode. Privileged data access uses the server-side service key after backend authorization. RLS policies restrict direct client queries, and SQL RPC functions serialize claim creation and status transitions. Keep the service-role key private and rotate it immediately if exposed.

Do not use the demo role selector as production authentication. Set up users and profiles through Supabase's trusted administrative tools. This repository's Supabase integration has not been exercised against a live project; run the SQL and verify policies in a non-production Supabase project before deployment.

## Environment variables

- `SUPABASE_URL`: project URL; blank means local demo mode.
- `SUPABASE_ANON_KEY`: public project anon key used for browser sign-in through the backend.
- `SUPABASE_SERVICE_ROLE_KEY`: privileged backend key; secret and server-side only.
- `CORS_ORIGINS`: optional comma-separated trusted origins; defaults to the local same-origin address.

## Tests

```powershell
python -m pytest -q
```

Tests use synthetic fixed-clock data and do not require Supabase credentials.

## Render deployment

1. Create a Render Web Service from the repository and use `render.yaml`.
2. Add Supabase URL, anon key and service-role key as Render environment variables.
3. Run `supabase/schema.sql` in the matching Supabase project and configure Auth profiles/organizations.
4. Deploy, then verify `/api/health` and sign in with a test account.

Without Supabase variables, Render runs an ephemeral in-memory demo; data is not persistent. Use Supabase for deployment persistence.

## Known limitations

- Demo role switching is deliberately not secure, and demo state is process-local/in-memory.
- Supabase sign-in requires pre-provisioned Auth users and profiles; account administration is done in Supabase.
- Matching distance is straight-line only; the app does not calculate routes, traffic or pickup travel time.
- No SMS/email notifications, delivery services, or food-safety certification are provided.
- The 0.4 kg per portion impact conversion is a labelled configurable estimate, not a measured waste reduction.
