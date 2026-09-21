# AI Act Copilot

A copilot that classifies whether an AI system is high-risk under the EU AI Act and explains why, grounded in official sources with citations.

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

**Always activate `.venv` before running project commands** (`source .venv/bin/activate`, from the repo root). Every command below — `pytest`, `ruff`, `alembic`, `uvicorn`, the ingestion scripts — assumes it's running against `.venv`, not your system Python.

If you forget to activate it, `pytest`/`python`/`pip` can silently resolve to a *different* Python on your `PATH` (a system install, pyenv, conda, etc.) that has none of this project's dependencies installed — you'll see `ModuleNotFoundError` for packages that `pip list` (inside `.venv`) clearly shows as installed. Check which interpreter is actually running with `which pytest` / `which python`; both should point inside `.../ai-act-copilot/.venv/bin/`. If they don't, activate the venv (or run `.venv/bin/pytest`, `.venv/bin/python -m pytest` explicitly).

Run the tests:
```
cd backend
pytest
```

A plain `pytest` never spends money: the five live-stack tests (real Supabase + real OpenAI: measured at 3 chat-model calls and 3 embedding calls per run) are marked `live` and skipped unless you opt in explicitly with `RUN_LIVE_TESTS=1 pytest` (they still need `DATABASE_URL`, `OPENAI_API_KEY` and `INTERNAL_API_SECRET` in `backend/.env`).

## Deploy

Backend on Railway, frontend on Vercel, Supabase as the database, Google OAuth in testing mode (invite-only). Both services run on their default platform domains.

### How the backend runs on Railway

`backend/railway.json` is the contract (Root Directory is the one setting the file cannot hold; set it to `backend` in the dashboard):

- **Pre-deploy:** `alembic upgrade head`. Runs after the build and **before the new instance starts**, in its own container with the service's variables. It must come first: `_write_trace_safe` swallows failures by design, so code that writes a column the table does not have yet would fail every trace write silently, and an uncounted call is an open daily quota.
- **Start:** `python scripts/build_bm25_index.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips='*'`. The BM25 index lives in `backend/data/`, which is gitignored, so it is rebuilt from the database on every instance boot before uvicorn binds. One worker, because the rate limiter and the index cache are per-process. If the build fails the process exits and Railway retries, instead of serving vector-only answers.
- **Health check:** `GET /health` returns `{"status": "ok", "environment": "production"}`. In production `/docs`, `/redoc` and `/openapi.json` are disabled, and both `/ask` and `/classify` require the BFF service token; the only anonymous route is `/health`.
- `backend/.python-version` pins 3.11 (what CI and the venv run).

### Environment variables

Backend (Railway → Variables). Nothing else is read by the code.

| variable | value |
|---|---|
| `DATABASE_URL` | the Supabase **session pooler** URL (`...pooler.supabase.com:5432`, user `postgres.<ref>`). The direct host is IPv6-only and unreachable from Railway. |
| `OPENAI_API_KEY` | |
| `INTERNAL_API_SECRET` | byte-identical to the Vercel value |
| `APP_ENV` | `production` |

Frontend (Vercel → Environment Variables, Production scope). Nothing is `NEXT_PUBLIC_`.

| variable | value |
|---|---|
| `AUTH_SECRET` | `openssl rand -base64 32` |
| `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET` | from Google Cloud Console |
| `INTERNAL_API_SECRET` | byte-identical to the Railway value |
| `FASTAPI_URL` | `https://<service>.up.railway.app`, no trailing slash |
| `AUTH_URL` | `https://<project>.vercel.app`, **Production scope only**. Not required by Auth.js v5 on Vercel, but pins the OAuth callback origin to the production domain. Leave it unset for Preview. |
| `AUTH_RESEND_KEY`, `AUTH_DB_URL`, `AUTH_EMAIL_FROM` | leave unset (magic-link stays off) |

`INTERNAL_API_SECRET` is generated once and pasted into both dashboards. A trailing newline or a re-generation on one side turns every question into a 401 that the UI reports as "The service is misconfigured".

### Runbook (dashboard steps, in order)

1. **Railway:** New project → Deploy from GitHub → this repo. Service Settings → Root Directory `backend`. Confirm the start and pre-deploy commands from `railway.json` appear in Settings.
2. Settings → Networking → Generate Domain. Copy it. Make sure App Sleeping is **off** (a sleeping instance turns the first question of the day into a 20-30 s cold start).
3. Variables → the four backend values above. Deploy.
4. Deploy logs, in order: the alembic line (`Running upgrade ...` or already at head), then `documents indexed: N` and `candidate sets match: True` from the index build, then uvicorn listening, and **no** `ACTION REQUIRED` line.
5. Smoke the backend alone (zero cost):
   `curl https://<railway>/health` → `environment: production`;
   `curl -i https://<railway>/docs` → 404;
   `curl -i -X POST https://<railway>/ask -H 'content-type: application/json' -d '{"question":"x"}'` → 401;
   `curl -i -X POST https://<railway>/classify -H 'content-type: application/json' -d '{}'` → 401.
6. **Vercel:** New project → import the repo → Root Directory `frontend`. Environment Variables → the frontend table above, with `FASTAPI_URL` from step 2. Deploy. Copy the `*.vercel.app` domain.
7. Add `AUTH_URL=https://<project>.vercel.app` (Production scope only). Redeploy.
8. **Google Cloud Console** → the OAuth client: Authorised JavaScript origins += `https://<project>.vercel.app`; Authorised redirect URIs += `https://<project>.vercel.app/api/auth/callback/google`. OAuth consent screen → Test users += every account that should be able to sign in (testing mode rejects everyone else with `access_denied`). Preview deployments will never be able to sign in; that is expected.
9. **Full smoke (one paid call, about $0.01):** open the Vercel URL, sign in with a listed test user, ask "What obligations apply to providers of high-risk AI systems?" Expect a grounded answer citing Article 16.
10. In Supabase, check the newest `query_trace` row: `environment = 'production'` and `retrieval_config` starting `hybrid_bm25`. That one row proves the environment label, the actor prior and the BM25 index all landed. `vector_only_degraded` there means the index build did not run.

### Rollback

Railway: Deployments → the previous successful deployment → Redeploy. Vercel: Deployments → previous → Promote to Production. Do **not** roll the schema back as part of a code rollback: migrations here are additive with server defaults, so older code still writes fine. `alembic downgrade` is only for a migration that is itself the fault.

### What goes wrong first

1. **No BM25 index at boot.** Symptom: `ACTION REQUIRED ... build_bm25_index.py` on every request and `retrieval_config = vector_only_degraded` in `query_trace`. Answers still come back, so only the logs and the trace row tell you. Cause: the start command was overridden, or the DB was unreachable when the script ran.
2. **`INTERNAL_API_SECRET` mismatch.** Every question shows "The service is misconfigured"; Railway logs a 401 per request; nothing is spent.
3. **Google OAuth.** `redirect_uri_mismatch` (the console URI must match the Vercel domain character for character) or `access_denied` (account not in Test users).
