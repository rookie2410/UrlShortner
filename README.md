# ShortLink

**ShortLink** is a URL-shortening web application with asynchronous click analytics. It lets a visitor create a short link, redirect through it, and view persisted click counts. The application is split into a React frontend, a FastAPI API, PostgreSQL for durable data, Redis for redirect caching and click-event queuing, and a separate Python worker.

This README covers the product, architecture, code organization, technology choices, local setup (including WSL Ubuntu), API usage, and testing. Deployment infrastructure, cloud resources, containers, CI/CD, hosting, and infrastructure automation are intentionally out of scope.

---

## Contents

- [Product overview](#product-overview)
- [Features](#features)
- [Architecture](#architecture)
- [Request and data flows](#request-and-data-flows)
- [Technology stack and why it is used](#technology-stack-and-why-it-is-used)
- [Repository structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Run locally on WSL Ubuntu](#run-locally-on-wsl-ubuntu)
- [Run the application](#run-the-application)
- [API reference](#api-reference)
- [Database model](#database-model)
- [Configuration reference](#configuration-reference)
- [Tests and verification](#tests-and-verification)
- [Troubleshooting](#troubleshooting)
- [Security, reliability, and limitations](#security-reliability-and-limitations)
- [Useful development commands](#useful-development-commands)

## Product overview

A user submits a destination URL such as `https://example.com/products`. ShortLink validates the URL, generates a random short code, stores the link in PostgreSQL, and returns a URL such as `http://localhost:8000/Ab3Kx7P`.

When someone visits the short URL, the API resolves the code using Redis when possible and PostgreSQL on a cache miss or Redis failure. It enqueues a click event in Redis Streams and responds with an HTTP redirect. A separate worker persists the event to PostgreSQL. The frontend retrieves analytics from the API, which calculates counts from persisted click events.

## Features

- Generate seven-character short codes using cryptographically secure randomness.
- Accept HTTP and HTTPS destinations; reject malformed URLs and embedded credentials.
- Optional link expiration and administrative deactivation.
- HTTP 302 redirects.
- Redis cache for frequently visited short links, with PostgreSQL fallback.
- Redis Streams queue for asynchronous click analytics.
- Separate worker process with pending-message recovery, bounded retries, idempotent writes, and a dead-letter stream.
- PostgreSQL-backed total-click and last-24-hour statistics.
- Responsive React interface with link creation, copy/open actions, optional expiration, analytics, loading states, and error handling.
- Request validation, structured logs, request IDs, CORS allowlisting, link-creation rate limiting, and health/readiness endpoints.
- No user accounts in this initial version.

## Architecture

```text
                         CREATE / STATS REQUESTS
Browser (React + TypeScript) --------------------------+
        |                                              |
        | fetch /api/v1                                v
        +----------------------------------------> FastAPI API
                                                      |
                            +-------------------------+-------------------+
                            |                         |                   |
                            v                         v                   v
                       PostgreSQL                  Redis cache        Redis Streams
                    (source of truth)          (redirect mappings)   (click events)
                            ^                                             |
                            |                                             v
                            +-------------------------------------- Python worker
                                                             validates + persists
                                                             then acknowledges
```

### Component responsibilities

**Frontend — React, TypeScript, Vite**
- Renders the link-creation form and analytics.
- Maintains loading, success, validation, and network-error states.
- Uses a typed fetch client to communicate with the API.
- Does not connect directly to PostgreSQL or Redis.

**API — FastAPI**
- Exposes the HTTP endpoints and OpenAPI documentation.
- Validates request data and destination URLs.
- Creates short codes and persists links.
- Resolves short codes, checks expiration/deactivation, reads and writes the redirect cache, and publishes click events.
- Serves analytics calculated from PostgreSQL.
- Returns redirects without waiting for the worker to persist analytics.

**PostgreSQL**
- The authoritative store for links and click events.
- Enforces short-code and event-ID uniqueness.
- Stores timestamps using timezone-aware columns; the application uses UTC.
- Provides the data for click statistics.

**Redis**
- Caches short-code-to-destination mappings to reduce database reads.
- Holds click events in Redis Streams.
- Is an optimization and queue, not the authoritative data store.

**Analytics worker**
- Runs as a separate Python process—not a background thread inside FastAPI.
- Consumes events from a Redis Streams consumer group.
- Validates payloads and writes click events to PostgreSQL.
- Acknowledges a message only after the database transaction commits or the event is confirmed to have already been stored.
- Recovers eligible pending messages, retries transient failures with bounded backoff, and routes malformed or repeatedly failing messages to a dead-letter stream.

### Why this architecture?

- **Fast redirects:** the browser doesn't wait for an analytics database write.
- **Cache efficiency:** common redirects can be resolved from Redis.
- **Durable source of truth:** PostgreSQL stores link state and persisted click events.
- **Independent processing:** the worker can be restarted independently of the API.
- **Safe retries:** unique event IDs make duplicate message delivery idempotent.
- **Clear responsibilities:** UI, HTTP routes, persistence, caching, and background processing are separated.

## Request and data flows

### 1. Create a short link

1. The user enters a URL in the React interface.
2. The frontend sends `POST /api/v1/links`.
3. FastAPI/Pydantic validate the payload. Application validation allows only HTTP/HTTPS, rejects embedded credentials and malformed URLs, and applies the configured length limit.
4. The service generates a random short code.
5. SQLAlchemy inserts the link into PostgreSQL. The database enforces code uniqueness; collisions are retried within a bounded limit.
6. The API returns HTTP `201` with the short code, short URL, destination, creation time, and optional expiry.

### 2. Resolve and redirect

1. A browser requests `GET /{code}`.
2. The API validates the code and looks up the redirect mapping in Redis.
3. On a cache miss, it queries PostgreSQL. Redis errors are bounded and fall back to PostgreSQL.
4. Unknown links return `404`; expired or deactivated links return `410`.
5. A valid mapping may be cached. Cache TTL is capped by the link's expiry.
6. The API publishes a click event to Redis Streams and returns HTTP `302`.
7. The browser follows the `Location` header to the destination.

If event enqueueing fails, the redirect is not unnecessarily blocked. The failure is logged, but that click may be absent from analytics.

### 3. Process a click event

1. The API publishes a compact event containing `event_id`, `link_id`, `clicked_at`, `referrer_domain`, and `user_agent_family`.
2. The worker reads the event from the stream.
3. It validates the event and inserts it into PostgreSQL using `event_id` for idempotency.
4. It commits the database transaction.
5. It acknowledges the Redis message only after successful persistence or confirmation of an existing event.
6. Recoverable failures are retried with bounded backoff. Malformed or repeatedly failing events can be routed to the configured dead-letter stream.

This is **at-least-once delivery with idempotent database writes**, not an exactly-once guarantee. Analytics can lag behind redirects, and queued events can be lost if Redis data is lost or enqueueing fails.

### 4. Read analytics

1. The frontend calls `GET /api/v1/links/{code}/stats`.
2. The API/repository queries PostgreSQL.
3. Total clicks and clicks in the last 24 hours are calculated from persisted events.
4. The API returns the counts and link timestamps.

The application does not use a process-local counter or Redis as the authoritative source for click totals.

## Technology stack and why it is used

| Technology | Use in this application |
|---|---|
| React | Component-based frontend UI. |
| TypeScript | Static typing for frontend components and API contracts. |
| Vite | Frontend development server and production asset build. |
| Fetch API | Browser-to-API HTTP communication. |
| CSS / CSS Modules | Responsive styling and component presentation. |
| Vitest | Frontend unit/component test runner. |
| React Testing Library | Tests frontend behavior through the user interface. |
| Python 3.12+ | Backend and worker runtime. |
| FastAPI | HTTP routing, dependency handling, validation integration, and OpenAPI docs. |
| Pydantic | Request, response, and event payload validation. |
| SQLAlchemy 2.x | ORM models, database sessions, inserts, and queries. |
| Alembic | Versioned database schema migrations. |
| Psycopg 3 | PostgreSQL driver. |
| Redis Python client | Redis cache and Streams operations. |
| PostgreSQL | Durable link and click-event storage and analytics queries. |
| Redis | Redirect cache and asynchronous click-event stream. |
| Pytest | Backend unit and API tests. |
| HTTPX | HTTP client used in API tests. |

## Repository structure

```text
shortlink/
├── frontend/
│   ├── src/
│   │   ├── api/              # Typed fetch client and API calls
│   │   ├── components/       # Reusable UI components
│   │   ├── pages/            # Main page and page-level interactions
│   │   ├── types/            # TypeScript API/data types
│   │   └── App.tsx            # Application root
│   ├── tests/                 # Frontend tests
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── api/routes/        # Link, redirect, health and readiness endpoints
│   │   ├── cache/             # Redis redirect-cache adapter
│   │   ├── core/              # Settings, logging and shared configuration
│   │   ├── db/                # SQLAlchemy base and database sessions
│   │   ├── models/            # Link and click-event ORM models
│   │   ├── queue/              # Redis Streams event producer
│   │   ├── repositories/      # Database reads and writes
│   │   ├── schemas/            # Pydantic request/response/event schemas
│   │   ├── services/           # Validation, short codes and rate limiting
│   │   ├── worker/             # Separate click analytics worker
│   │   └── main.py             # FastAPI application entry point
│   ├── migrations/             # Alembic migrations
│   ├── tests/                  # Pytest tests
│   ├── alembic.ini
│   └── pyproject.toml
├── .env.example                # Example configuration; no real credentials
└── README.md
```

> If your checked-out source tree differs slightly, use the files actually present in your repository as the source of truth. Keep responsibilities separated when adding code.

## Prerequisites

- Python **3.12 or newer**
- Node.js **22.12+** (Node.js 22 LTS is recommended for local development)
- npm
- PostgreSQL
- Redis **7.2+** with Streams and consumer-group support
- Git and a terminal

The commands below assume WSL Ubuntu and a project directory such as `/mnt/d/Roshan/Project/UrlShortner`. Replace that path with your own. For better Linux file performance, a project under `~/UrlShortner` is generally preferable to a Windows-mounted `/mnt/d` directory.

## Run locally on WSL Ubuntu

### 1. Verify the tools

```bash
python3.12 --version
node --version
npm --version
```

Confirm that Python reports `3.12.x` or newer and Node reports `22.12.x` or newer.

### 2. Start PostgreSQL and Redis

If these services are installed through Ubuntu packages:

```bash
sudo service postgresql start
sudo service redis-server start
```

Verify they are responding:

```bash
pg_isready
redis-cli ping
redis-server --version
```

Expected Redis response:

```text
PONG
```

If either command is unavailable, install that service using its official package instructions for your Ubuntu version before continuing.

### 3. Create the PostgreSQL user and database

Open the PostgreSQL shell:

```bash
sudo -u postgres psql
```

Run these SQL statements once, changing the example password to a local development password:

```sql
CREATE USER shortlink WITH PASSWORD 'change-me';
CREATE DATABASE shortlink OWNER shortlink;
\q
```

If the role or database already exists, don't create it again. Ensure the password matches the `DATABASE_URL` in your `.env` file.

### 4. Configure the environment

From the repository root:

```bash
cd /path/to/UrlShortner
cp .env.example .env
nano .env
```

Set or verify the local values:

```dotenv
DATABASE_URL=postgresql+psycopg://shortlink:change-me@localhost:5432/shortlink
REDIS_URL=redis://localhost:6379/0

PUBLIC_BASE_URL=http://localhost:8000
FRONTEND_API_BASE_URL=http://localhost:8000/api/v1
VITE_API_BASE_URL=http://localhost:8000/api/v1

ALLOWED_FRONTEND_ORIGINS=http://localhost:5173
```

Keep the other documented values from `.env.example`. The database password must match the user created above. Set `ADMIN_API_TOKEN` to a long random value if you want to enable administrative link deactivation. Never commit `.env` or real credentials.

### 5. Install backend dependencies

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

Verify that the virtual environment uses the right Python:

```bash
python --version
which python
```

The executable path should point to `backend/.venv/bin/python` and report Python 3.12 or newer. If `python` or pip is missing, recreate the virtual environment using the explicit `python3.12` executable and make sure the Python 3.12 venv package is installed.

### 6. Apply the database migration

From `backend/`, with the virtual environment active:

```bash
alembic upgrade head
```

This creates the application tables. If the command fails, verify PostgreSQL is running and `DATABASE_URL` is correct.

### 7. Start the API

Still in `backend/`:

```bash
uvicorn app.main:app --reload --port 8000
```

Keep this terminal open.

- API docs: <http://localhost:8000/docs>
- Liveness: <http://localhost:8000/health>
- Readiness: <http://localhost:8000/ready>

If port 8000 is already in use, check the process before stopping it:

```bash
sudo lsof -i :8000
```

If the process is a previous Uvicorn instance that you own, stop it with `Ctrl+C` in its terminal. Alternatively, run the API on another port and update `PUBLIC_BASE_URL` and frontend API configuration to match.

### 8. Start the analytics worker

Open a **second terminal**:

```bash
cd /path/to/UrlShortner/backend
source .venv/bin/activate
python -m app.worker.runner
```

Keep it open. The worker is a separate process and must be running for queued click events to be persisted.

### 9. Install and start the frontend

Open a **third terminal**:

```bash
cd /path/to/UrlShortner/frontend
npm install
npm run dev
```

Open the local URL printed by Vite, normally <http://localhost:5173>.

If you need to override the frontend API URL, create `frontend/.env.local`:

```dotenv
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Vite environment variables prefixed with `VITE_` are exposed to browser code. Never put secrets in them.

### 10. Confirm the application works

In a fourth terminal:

```bash
curl -i http://localhost:8000/health
curl -i http://localhost:8000/ready
```

Create a link:

```bash
curl -sS -X POST http://localhost:8000/api/v1/links \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/products","expires_at":null}'
```

Copy the `short_url` or `code` from the response. Test the redirect using the actual code:

```bash
curl -i http://localhost:8000/YOUR_CODE
```

A valid link should return HTTP `302` and a `Location` header. Visit the short URL in a browser, wait briefly for the worker to process the event, and refresh the analytics view.

All of the following must be running for the full local workflow:

1. PostgreSQL service
2. Redis service
3. FastAPI API process
4. Analytics worker process
5. Vite frontend process

## API reference

All application API routes use the `/api/v1` prefix, except redirect and health/readiness routes.

### `POST /api/v1/links`

Creates a short link.

Request:

```json
{
  "url": "https://example.com/products",
  "expires_at": null
}
```

Success: HTTP `201 Created`.

The response includes `code`, `short_url`, `original_url`, `created_at`, and `expires_at`. The short URL is built from `PUBLIC_BASE_URL`, not from an untrusted request Host header.

Optional expiration timestamps must include a timezone and be in the future.

### `GET /{code}`

Resolves a short link and redirects with HTTP `302`.

- `302`: valid link; `Location` contains the destination.
- `404`: unknown code.
- `410`: expired or deactivated link.

### `GET /api/v1/links/{code}/stats`

Returns the total number of persisted clicks, clicks in the last 24 hours, creation time, and expiration time.

```bash
curl -sS http://localhost:8000/api/v1/links/YOUR_CODE/stats
```

A valid link with no click events returns zero counts. Unknown links return `404`; expired/deactivated links return `410` according to the API contract.

### `POST /api/v1/links/{code}/deactivate`

Administrative endpoint for deactivating a link. It requires the `X-Admin-Token` header to match `ADMIN_API_TOKEN`. If no admin token is configured, the endpoint is disabled. A successful deactivation returns HTTP `204` and attempts to invalidate the cached mapping.

### `GET /health`

Lightweight liveness endpoint for the API process.

### `GET /ready`

Checks required dependencies and reports readiness. It returns a failure status when a required dependency is unavailable.

### Error responses

Errors use a predictable JSON envelope, for example:

```json
{
  "error": {
    "code": "link_not_found",
    "message": "This short link was not found."
  }
}
```

Validation errors use HTTP `422`. Public responses should not expose internal stack traces.

## Database model

### `links`

| Field | Purpose |
|---|---|
| `id` | UUID primary key |
| `code` | Unique, indexed short code (up to 16 characters) |
| `original_url` | Destination URL |
| `created_at` | Timezone-aware creation timestamp |
| `expires_at` | Nullable expiration timestamp |
| `is_active` | Deactivation flag |

### `click_events`

| Field | Purpose |
|---|---|
| `id` | UUID primary key |
| `event_id` | Globally unique event identifier for idempotency |
| `link_id` | Foreign key to `links.id` |
| `clicked_at` | Timezone-aware click timestamp |
| `referrer_domain` | Optional referring hostname |
| `user_agent_family` | Optional coarse client/browser family |

Timestamps use UTC consistently. Raw visitor IP addresses are not stored. Indexes support lookup by link and click time.

## Configuration reference

See `.env.example` for the full list. Important settings:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy PostgreSQL connection URL using Psycopg 3 |
| `REDIS_URL` | Redis connection URL |
| `PUBLIC_BASE_URL` | Trusted base URL used to build short links |
| `FRONTEND_API_BASE_URL` | API URL used by frontend configuration |
| `VITE_API_BASE_URL` | Browser-visible API URL for Vite |
| `ADMIN_API_TOKEN` | Enables administrative link deactivation when configured |
| `ALLOWED_FRONTEND_ORIGINS` | Comma-separated CORS origins |
| `REDIRECT_CACHE_TTL_SECONDS` | Maximum redirect cache TTL; default 300 seconds |
| `MAX_URL_LENGTH` | Maximum accepted destination URL length |
| `CREATE_RATE_LIMIT_COUNT` | Number of allowed creation requests per configured window |
| `CREATE_RATE_LIMIT_WINDOW_SECONDS` | Link-creation rate-limit window |
| `REDIS_SOCKET_TIMEOUT_SECONDS` | Bounded Redis connection/socket timeout |
| `CLICK_STREAM_NAME` | Redis Stream name for click events |
| `CLICK_CONSUMER_GROUP` | Redis Streams consumer group |
| `CLICK_DEAD_LETTER_STREAM` | Stream used for malformed or repeatedly failing messages |
| `WORKER_CONSUMER_NAME` | Worker consumer name |
| `WORKER_BATCH_SIZE` | Maximum stream batch size |
| `WORKER_BLOCK_MS` | Stream read blocking interval |
| `WORKER_PENDING_IDLE_MS` | Minimum idle time before pending-message recovery |
| `WORKER_MAX_DELIVERIES` | Maximum delivery attempts before dead-lettering |
| `WORKER_MAX_BACKOFF_SECONDS` | Upper bound for retry backoff |
| `LOG_LEVEL` | Application logging level |

## Tests and verification

Run backend tests:

```bash
cd backend
source .venv/bin/activate
python -m pytest -v
```

Run frontend tests and build:

```bash
cd frontend
npm test
npm run build
```

The tests should cover URL validation, code generation/collisions, expiration, cache behavior, link creation, redirects, analytics, duplicate event delivery, worker retries/recovery, and frontend interaction/error states to the extent implemented by the test suite.

For stronger integration confidence, also verify against real PostgreSQL and Redis services:
- Create a link from the UI.
- Confirm the link row exists in PostgreSQL.
- Visit the short URL and observe the redirect.
- Confirm a click event appears in the Redis stream.
- Confirm the worker persists it to PostgreSQL.
- Replay the same event ID in a controlled test and confirm it doesn't increment counts twice.
- Confirm the stats endpoint returns the persisted count.

Do not infer that a live PostgreSQL + Redis end-to-end test has passed solely from unit tests using SQLite or fake Redis adapters.

## Troubleshooting

### Python virtual environment uses the wrong version or pip is missing

Create it with an explicit Python executable:

```bash
deactivate 2>/dev/null || true
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
python --version
python -m pip --version
```

If `venv`/`ensurepip` is unavailable, install the matching Python 3.12 venv package using your Ubuntu package manager.

### `Address already in use` on port 8000

Find the listener:

```bash
sudo lsof -i :8000
```

Stop your own previous Uvicorn instance with `Ctrl+C` in its terminal. Avoid killing unknown processes. You can use another port, but update both the generated short-link base URL and frontend API configuration.

### Redis or PostgreSQL connection errors

```bash
sudo service postgresql start
sudo service redis-server start
pg_isready
redis-cli ping
```

Then verify `.env`, database credentials, and that the required service is listening locally.

### npm `ERESOLVE` dependency errors

Don't immediately use `--force` or `--legacy-peer-deps`. Check the versions in `frontend/package.json`, review the full peer-dependency error, and align the incompatible package versions. Only remove `package-lock.json` if you intend to regenerate the lockfile and review the resulting dependency changes.

### Frontend loads but API requests fail

- Verify the API is running at port 8000.
- Check `VITE_API_BASE_URL` in `frontend/.env.local`, if set.
- Confirm `ALLOWED_FRONTEND_ORIGINS` includes the exact browser origin (usually `http://localhost:5173`).
- Restart Vite after changing frontend environment variables.

### Click counts do not update

- Verify the worker is running and has no errors.
- Verify Redis and PostgreSQL are available.
- Wait briefly for asynchronous processing, then refresh analytics.
- Inspect API and worker logs for queue enqueue failures, pending events, database errors, or dead-letter messages.

## Security, reliability, and limitations

- Only HTTP/HTTPS destination URLs are accepted. URL validation does not establish that a destination is safe.
- The API does not fetch destination URLs; this avoids turning URL creation into a server-side request.
- Public short links can be abused for phishing. This version has no reputation service, user accounts, link ownership, or public abuse-reporting workflow.
- The admin token must be kept secret. It is not a substitute for authentication and authorization across a multi-user product.
- The rate limiter's process-local fallback during Redis outages is not shared across multiple API processes.
- Cache invalidation depends on Redis being reachable when link state changes. Keep this failure mode in mind if extending the application.
- Click events may be lost if the API cannot enqueue them or Redis loses queued data. Analytics is asynchronous and can lag behind redirects.
- Idempotency prevents duplicate processing of one event ID; it does not deduplicate separate visits from the same visitor.
- No raw visitor IP addresses are persisted. Referrer host and coarse user-agent family can still be sensitive in some contexts.
- The first version reports aggregate counts only; it doesn't provide time-series charts, geolocation, unique-user detection, or per-link access control.

## Useful development commands

```bash
# Backend tests
cd backend && source .venv/bin/activate && python -m pytest -v

# Frontend tests
cd frontend && npm test

# Frontend build
cd frontend && npm run build

# Database migration
cd backend && source .venv/bin/activate && alembic upgrade head

# API liveness and readiness
curl -i http://localhost:8000/health
curl -i http://localhost:8000/ready

# Redis connectivity
redis-cli ping

# PostgreSQL connectivity
pg_isready
```

---

ShortLink's key architectural idea is simple: **PostgreSQL owns durable state, Redis accelerates redirects and queues click events, and a separate worker persists analytics asynchronously.** The API keeps redirects fast while idempotent worker writes protect click counts from duplicate message delivery.
<!-- Jenkins webhook test -->
<!-- Jenkins webhook test -->
