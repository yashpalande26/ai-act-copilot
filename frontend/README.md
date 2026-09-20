# AI Act Copilot, Web UI

Next.js (App Router) + TypeScript + Tailwind v4 + shadcn/ui frontend for the
AI Act Copilot. Talks to the FastAPI backend in `../backend` using the **BFF
pattern**: the browser never holds a backend credential.

---

## Architecture: how a question travels

```
Browser                Next.js (server)                    FastAPI
───────                ────────────────                    ───────
  │  fetch /api/ask         │                                 │
  │  (Auth.js httpOnly      │                                 │
  │   session cookie)       │                                 │
  ├────────────────────────►│                                 │
  │                         │ auth()  ← verifies session      │
  │                         │ SignJWT ← mints 60s HS256 token │
  │                         │   {sub, email, iat, exp}        │
  │                         ├────────────────────────────────►│
  │                         │  Authorization: Bearer <token>  │ jwt.decode(
  │                         │                                 │   leeway=10)
  │                         │◄────────────────────────────────┤
  │◄────────────────────────┤  {answer, citations, abstained} │
```

**Why this shape.** Auth.js v5 session tokens are JWE-*encrypted* by default,
not plain signed JWTs. Verifying one in Python means reimplementing Auth.js's
HKDF key derivation, which is coupled to internals that changed between v4 and
v5. The BFF sidesteps that entirely, keeps the OpenAI-spending endpoint off the
public internet, and means XSS has no backend credential to steal.

**The signing key never transits the wire.** Only 60-second derived tokens do.
A leaked request log therefore exposes a one-minute credential, not a standing
one.

> **Residual risk, stated plainly:** a valid token proves *a party holding the
> signing key asserted this identity*, not that the end user authenticated. In
> production, restrict FastAPI ingress to the Next.js origin. Key custody plus
> network isolation is the real security boundary.

---

## Environment variables

Copy `.env.local.example` → `.env.local` (gitignored) and fill in.

| Variable | Required | Where it lives | Purpose |
|---|---|---|---|
| `AUTH_SECRET` | yes | Next.js server | Signs/encrypts the Auth.js session cookie |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | yes* | Next.js server | Google OAuth sign-in |
| `FASTAPI_URL` | yes | Next.js server | Backend origin, e.g. `http://127.0.0.1:8000` |
| `INTERNAL_API_SECRET` | yes | **Next.js server AND `backend/.env`** | HMAC key for the service token, must match byte for byte |
| `AUTH_RESEND_KEY` / `AUTH_DB_URL` / `AUTH_EMAIL_FROM` | no | Next.js server | Enables magic-link sign-in |

\* At least one sign-in method must be configured. The sign-in page adapts to
whichever are present and tells you if none are.

### Every one of these is server-side only

Next.js inlines **only** `NEXT_PUBLIC_*` variables into the browser bundle.
Nothing above carries that prefix, so nothing above reaches the client.

Two mechanisms enforce this rather than relying on discipline:

1. **`lib/fastapi.ts` begins with `import "server-only"`.** If any client
   component ever imports it, **the build fails**. Verified by deliberately
   adding such an import. The build errored with
   `./lib/fastapi.ts [Client Component Browser]`, then passed again once
   removed.
2. **Bundle scan.** `.next/static` was grepped for every secret name and for a
   sentinel secret value: zero matches.

The browser only ever holds the Auth.js httpOnly session cookie.

---

## Running locally

**1. Start the backend** (from the repo root):

```bash
cd backend
# INTERNAL_API_SECRET must match the frontend's value
INTERNAL_API_SECRET='your-shared-secret' ../.venv/bin/uvicorn app.main:app --reload --port 8000
```

The backend also needs `DATABASE_URL` + `OPENAI_API_KEY` in `backend/.env`, and
a BM25 index built (`python scripts/build_bm25_index.py`). Without one it
still answers, but degrades to vector-only and logs loudly.

**2. Start the frontend:**

```bash
cd frontend
cp .env.local.example .env.local   # then fill it in
npm install
npm run dev
```

Open http://localhost:3000.

**Generating secrets:**

```bash
npx auth secret                 # AUTH_SECRET
openssl rand -base64 32         # INTERNAL_API_SECRET (paste into BOTH envs)
```

**Google OAuth setup:** Google Cloud Console → APIs & Services → Credentials →
OAuth client ID (Web). Authorised redirect URI:
`http://localhost:3000/api/auth/callback/google`.

---

## Magic-link sign-in (optional)

Auth.js **requires a database adapter** for email sign-in, because verification
tokens must be persisted and single-use. Set `AUTH_RESEND_KEY` + `AUTH_DB_URL`
to enable it; leave them blank and the app runs on Google alone.

> ⚠️ **Alembic caveat, read before enabling.** The adapter creates its own
> tables (`users`, `accounts`, `sessions`, `verification_token`). If you point
> `AUTH_DB_URL` at the same database Alembic manages, the next
> `alembic revision --autogenerate` will see them as unknown tables and
> **propose dropping them**, the same class of false positive that already bit
> the HNSW/GIN indexes in this repo. Either point `AUTH_DB_URL` at a separate
> database, or put the tables in a dedicated schema and exclude it via
> `include_object` in `alembic/env.py`. This is why magic-link is off by
> default rather than wired in silently.

---

## Design notes

**Trust is built from product properties, not borrowed badges.** The usual
legal-tech landing page leans on G2 ratings, client logos and SOC 2 badges. We
have none of those, and inventing them would violate the project's first rule.
So the landing page argues from what the system actually does: every claim
carries a citation, citations come from retrieved provisions rather than model
prose, it declines when it doesn't know, and answers are pinned to a corpus
version. Those are verifiable and they're the real differentiators.

**Abstention is a first-class UI state.** When the copilot declines it gets its
own treatment: caution colouring, its own icon, and an explanation that this is
*intended* behaviour. Rendering a refusal as ordinary prose would invite users
to skim past the one moment the product is protecting them.

**Citations are the interface, not a footnote.** Each is a collapsible control
showing the article label; expanding reveals the provision text verbatim plus
its machine citation id. The quoted text is what was actually retrieved and fed
to the model.

**Colour carries meaning.** Navy for institutional trust (the fintech/compliance
convention), green reserved exclusively for grounded/cited, amber exclusively
for abstention. Those are the two states a compliance user must distinguish at a glance.

**Defence in depth on input.** The 2000-character cap is enforced in the
textarea (live counter), again in the route handler, and again by Pydantic in
FastAPI. An oversized question never reaches the model.

**Accessibility.** Semantic landmarks, `aria-live` on the pending and
error states, labelled controls, visible focus rings, and a
`prefers-reduced-motion` block that neutralises animation.

**Responsive.** Single column on phones, comfortable measure on desktop; the
composer stays pinned with the transcript scrolling independently.

---

## Known limitations

- **Non-streaming.** The current `/ask` contract returns a complete answer, so
  the UI shows a pending state then the full cited response. Streaming is a
  natural future enhancement and would need a backend change (SSE) plus
  incremental citation rendering. Deliberately not built now.
- **Conversation history is in-memory.** Turns live in React state for the
  session; the backend persists messages, but there's no history UI yet.
- **Dark mode** ships coherent tokens but no toggle. It follows the system
  preference.
