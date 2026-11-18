# Procurem

Procurem is a local procurement workspace with seeded SQLite data, a grounded assistant, supplier and sourcing proposals, sequential approvals, notifications, audit and user administration. Adapter labels represent local database reads, not external integrations. This demonstration is not a certified electronic-signature system. The dashboard's USD total includes only USD orders; an amountless supplier edit is low risk unless the proposed risk is high.

## Run locally

Requires Python 3.12 and Node 20.9 or later. From the repository root:

```sh
python3 -m venv --copies "$HOME/venvs/procurem"
"$HOME/venvs/procurem/bin/python" -m pip install -r backend/requirements.txt
cd backend
cp .env.example .env
PYTHONPATH=. "$HOME/venvs/procurem/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
cp .env.example .env.local
npm install --no-bin-links
node node_modules/next/dist/bin/next dev
```

Open http://localhost:3000. All seven demo accounts and their passwords are displayed on sign-in. The database is created at `backend/data/procurem.db`; seed runs only if the users table is empty. Deleting this file resets local data. The seed and these credentials are for local demonstration only, not production. Set `SEED_ON_STARTUP=false` when demo data is not appropriate. Configure `COOKIE_SECURE=true` behind HTTPS, and set explicit allowed origins. `NEXT_PUBLIC_API_URL` should remain empty for the same-origin proxy; `API_PROXY_TARGET` is server-only. Frontend and API origins must match the cookie deployment policy.

## Containers

Run `docker compose up --build` and open http://localhost:3000. The named `procurem-data` volume persists SQLite across restarts. `docker compose down` leaves it intact; removing the volume destroys demo and user data. The compose settings are for local development and deliberately disable secure cookies. For HTTPS set `COOKIE_SECURE=true` and restrict exposure and origins.

## API and tests

API documentation is available at http://localhost:8000/docs. `GET /api/health` lists the five local adapter states. `POST /api/v1/auth/login`, `GET /api/v1/auth/me` and `POST /api/v1/auth/logout` use an HttpOnly, SameSite=Lax cookie; server-side sessions expire in 8 hours or 30 days and logout revokes them. Passwords and session tokens are stored only as hashes. Currency columns are exact decimal strings and should be parsed as Decimal, not float.

```sh
cd backend && PYTHONPATH=. "$HOME/venvs/procurem/bin/python" -m pytest -q
cd frontend && node node_modules/vitest/vitest.mjs run
```

The Playwright suite starts its own isolated seeded backend and frontend: `cd frontend && node node_modules/@playwright/test/cli.js test`. Install Chromium with `node node_modules/@playwright/test/cli.js install chromium` first. Set `E2E_PYTHON` to the absolute Python executable if not using the documented venv; see `frontend/e2e/README.md` for ports and isolation limitations. The assistant accepts questions and, for complete changes, explicit semicolon-delimited fields; it asks for missing information rather than guessing. Startup creates missing tables but does not migrate existing schema; preserve data and plan migrations before evolving it.
