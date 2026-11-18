# Procurem — authentication foundation

This slice provides a local procurement demo database, a sign-in screen and an authenticated identity view. The Home dashboard and all record, approval and assistant features are subsequent slices and are not implemented here. All adapter statuses describe local seed tables; no external service is contacted.

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
cd backend && PYTHONPATH=. "$HOME/venvs/procurem/bin/python" -m pytest -q tests/test_auth.py
cd frontend && node node_modules/vitest/vitest.mjs run
```

The Playwright spec is provided for a later end-to-end run against both running services: `cd frontend && node node_modules/@playwright/test/cli.js test`. Install Chromium with `node node_modules/@playwright/test/cli.js install chromium` first. `PLAYWRIGHT_BASE_URL` can override its default. Startup creates missing tables but does not migrate existing schema; preserve data and plan migrations before evolving it.
