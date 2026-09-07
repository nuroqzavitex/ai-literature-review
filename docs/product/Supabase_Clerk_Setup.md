# Supabase + Clerk setup

The application uses Clerk as the only identity provider. Supabase PostgreSQL
stores application profiles, projects, review history, report versions,
invitations, assignments and Copilot conversations. The browser does not access
the product tables directly; authenticated requests go through FastAPI.

## 1. Create the Supabase schema

Create a Supabase project, then apply:

```text
supabase/migrations/202608040001_product_core.sql
```

Use the direct connection or Session Pooler for migrations. The application may
use the Session Pooler or Transaction Pooler; prepared statements are disabled
in the psycopg adapter for transaction-pool compatibility.

Set this backend secret:

```dotenv
PRODUCT_DATABASE_URL=postgresql://postgres.PROJECT:PASSWORD@REGION.pooler.supabase.com:5432/postgres
```

`DATABASE_URL` must also be PostgreSQL because literature-review jobs and
LangGraph checkpoints are PostgreSQL-only. `PRODUCT_DATABASE_URL` may point to
a separate Supabase database; when omitted, product data shares `DATABASE_URL`.

```dotenv
DATABASE_URL=postgresql://postgres.PROJECT:PASSWORD@REGION.pooler.supabase.com:5432/postgres
# PRODUCT_DATABASE_URL=postgresql://postgres.PROJECT:PASSWORD@REGION.pooler.supabase.com:5432/postgres
```

The migration enables RLS on product tables without browser-facing policies.
Consequently, the Supabase publishable key cannot read product records. Do not
put `PRODUCT_DATABASE_URL` or a Supabase service-role key in the frontend.

## 2. Configure Clerk

Create a Clerk application. Add the frontend key to `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
```

Add the backend verification settings to `.env`:

```dotenv
CLERK_ISSUER=https://YOUR_INSTANCE.clerk.accounts.dev
CLERK_JWKS_URL=https://YOUR_INSTANCE.clerk.accounts.dev/.well-known/jwks.json
CLERK_AUTHORIZED_PARTIES=http://localhost:3000
CLERK_WEBHOOK_SIGNING_SECRET=whsec_...
INVITATION_BASE_URL=http://localhost:3000/
```

Production requests use the Clerk bearer token. The deterministic
`POST /api/v1/auth/session` bootstrap endpoint is available only in development
and test and returns 404 in production.

## 3. Configure the Clerk webhook

Create a Clerk webhook pointing to:

```text
https://YOUR_API_HOST/api/v1/webhooks/clerk
```

Subscribe to `user.created`, `user.updated` and `user.deleted`. The handler
verifies the webhook signature, upserts only the profile fields needed by the
application, and soft-deletes profiles so review and audit history remain intact.
An authenticated API request also creates a minimal profile synchronously; this
prevents webhook delivery delay from blocking first login.

## 4. Configure invitation email with Resend

Create a Resend API key with sending access, verify a domain you own, and add
these backend-only values to `.env`:

```dotenv
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=Research Review <review@updates.yourdomain.com>
RESEND_REPLY_TO=team@yourdomain.com
RESEND_TIMEOUT_SECONDS=10
RESEND_MIN_INTERVAL_SECONDS=60
```

`RESEND_FROM_EMAIL` must use the verified domain. A subdomain such as
`updates.yourdomain.com` is recommended to isolate sending reputation. Do not
put `RESEND_API_KEY` in `frontend/.env.local`.

Invitation creation is fail-safe: the database row and one-time link are
created before the email request. A Resend failure is recorded as `failed`, but
does not invalidate the copyable link. Sending again rotates the one-time token,
invalidates the previous link and is rate-limited by
`RESEND_MIN_INTERVAL_SECONDS`.

If the Resend settings are omitted, the invitation is marked
`not_configured` and the copyable-link workflow remains available.

## 5. Invitations and review authorization

- An owner/researcher creates a one-time invitation link for a specific review.
- Links expire after seven days by default and can be revoked.
- Accepting creates a reviewer project membership plus a review-specific
  assignment. Project membership alone does not grant access to every review.
- Authors may review their own reports. The submission is stored as
  `self_review`; invited decisions are stored as `external_review`.
- Reviewer accounts cannot access project conversations or memories.

The UI shows email delivery state and retains a copyable link as a fallback.

## 6. Verification

```powershell
docker build -t p178-test .
docker run --rm -e GOOGLE_API_KEY=test-key p178-test pytest tests -q
cd frontend
npm.cmd run lint
npm.cmd run build
```

Use a fake provider key only for the test suite, whose LLM calls are mocked.
Never deploy a fake key.
