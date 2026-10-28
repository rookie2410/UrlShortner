# ShortLink

ShortLink is a URL shortener with asynchronous click analytics. This repository contains the React/TypeScript interface, a FastAPI application, PostgreSQL persistence, Redis redirect caching, and a separate Redis Streams worker. Deployment, hosting, cloud resources, containers, CI/CD, and infrastructure automation are intentionally out of scope.

## Features

- Create seven-character URL-safe short codes using Python's cryptographic random generator.
- Accept HTTP and HTTPS destinations only; reject malformed URLs and embedded credentials.
- Optional expiration timestamps; expired and deactivated links return HTTP 410.
- 302 redirects with a Redis cache that falls back to PostgreSQL when Redis is unavailable.
- Redis Streams click queue and a separate worker; analytics writes are idempotent by `event_id`.
- PostgreSQL-backed total-click and last-24-hour analytics.
- Request validation, consistent JSON errors, request IDs, structured logs, CORS allowlisting, link-creation rate limiting, bounded Redis socket timeouts, and health/readiness endpoints.
- Responsive interface with clipboard handling, optional expiration, analytics, and explicit loading/error states.

There are no user accounts in this first version. An administrative token can be configured to protect link deactivation.

## Architecture

```text
Browser (React + TypeScript)
        | fetch /api/v1
        v
FastAPI API -----------------------> PostgreSQL (source of truth)
   |        |                              ^
   |        +---- redirect cache ---- Redis|
   |                                       |
   +---- Redis Stream click event --> Worker process
                                           |
                                           +-- validates, idempotently stores, then ACKs
```

The API does not wait for the analytics worker. Click events are delivered at least once and use idempotent PostgreSQL writes; this is not an exactly-once guarantee. If Redis loses data or an event cannot be enqueued, that click may not appear in analytics. Queue enqueue failures are logged rather than silently ignored. Malformed or repeatedly failing worker messages are written to a dead-letter stream after the configured delivery limit.

PostgreSQL is authoritative. Redis is an optimization/queue, never the source of truth for link records or click totals. Cache entries are only created for valid links, their TTL is capped by link expiration, and deactivation invalidates the matching cache entry. A Redis outage causes redirects to use PostgreSQL. As with any cache-invalidation design, deactivation relies on cache invalidation reaching Redis; use operational controls that keep this dependency reliable.

## Repository layout

```text
shortlink/
├── frontend/                 # React, TypeScript, Vite, Vitest
│   ├── src/api/              # Typed fetch client
│   ├── src/components/       # Shared UI
│   ├── src/pages/            # Main page
│   ├── src/types/            # API types
│   └── tests/                # Frontend tests
├── backend/
│   ├── app/api/routes/       # API, redirects, and readiness
│   ├── app/cache/            # Redirect cache adapter
│   ├── app/core/             # Settings and structured logging
│   ├── app/db/               # SQLAlchemy base and sessions
│   ├── app/models/           # Link and click-event models
│   ├── app/queue/            # Redis Streams producer
│   ├── app/repositories/     # Database query/write operations
│   ├── app/schemas/          # Pydantic request/event/response types
│   ├── app/services/         # Validation helpers and rate limiter
│   ├── app/worker/           # Independent analytics worker
│   ├── migrations/           # Alembic schema migrations
│   └── tests/                # Pytest unit and API tests
├── .env.example
└── README.md
```

## Requirements

- Python 3.12 or newer
- Node.js 20.19+ or 22.12+
- PostgreSQL
- Redis 7.2+ with Redis Streams consumer-group support

Create a PostgreSQL database named `shortlink` and make Redis available locally, then create configuration from the example:

```bash
cp .env.example .env
```

Edit `.env` with your database URL, Redis URL, frontend origin, public short-link base URL, and a long random `ADMIN_API_TOKEN`. Leave the admin token unset to keep deactivation disabled. No real credentials belong in source control.

## Run locally

### Backend API

```bash
cd backend
python -m venv .venv
# Activate the virtual environment, then:
pip install -e '.[test]'
# From backend/; the configuration file is loaded from the repository root.
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

FastAPI's OpenAPI UI is available at `http://localhost:8000/docs` during local development.

### Click analytics worker

In a second terminal, activate the same backend virtual environment and run:

```bash
cd backend
python -m app.worker.runner
```

The worker is a separate process, not a background thread inside the API. It creates a Redis consumer group, recovers eligible pending events, validates each event, persists it, and acknowledges only after commit or confirmation that the event was already stored. Database errors leave messages pending and use bounded per-message exponential backoff; repeatedly failing messages are sent to `shortlink:click-events:dead-letter` after `WORKER_MAX_DELIVERIES` deliveries.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The default development API base URL is `http://localhost:8000/api/v1`. To override it, create `frontend/.env.local` with `VITE_API_BASE_URL=...`. This variable is public frontend configuration and must not contain secrets.

## Configuration

All supported variables are shown in `.env.example`:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL SQLAlchemy URL using Psycopg 3 |
| `REDIS_URL` | Redis client URL |
| `PUBLIC_BASE_URL` | Trusted base URL placed in generated short links |
| `FRONTEND_API_BASE_URL` / `VITE_API_BASE_URL` | API URL for frontend use/configuration |
| `ADMIN_API_TOKEN` | Protects the administrative deactivation endpoint; unset disables it |
| `ALLOWED_FRONTEND_ORIGINS` | Comma-separated CORS origins |
| `REDIRECT_CACHE_TTL_SECONDS` | Maximum redirect cache TTL; default 300 seconds |
| `MAX_URL_LENGTH` | Maximum accepted destination URL length |
| `CREATE_RATE_LIMIT_COUNT` / `CREATE_RATE_LIMIT_WINDOW_SECONDS` | Link creation request threshold/window |
| `REDIS_SOCKET_TIMEOUT_SECONDS` | Bounded Redis connect/socket timeout |
| `CLICK_STREAM_NAME` | Redis Streams queue name |
| `CLICK_CONSUMER_GROUP` | Shared worker consumer group |
| `CLICK_DEAD_LETTER_STREAM` | Dead-letter stream for malformed/repeated failures |
| `WORKER_CONSUMER_NAME` | Worker consumer name prefix |
| `WORKER_BATCH_SIZE` / `WORKER_BLOCK_MS` | Stream read sizing and blocking timeout |
| `WORKER_PENDING_IDLE_MS` | Minimum pending-message idle period before recovery |
| `WORKER_MAX_DELIVERIES` | Maximum processing attempts before dead-lettering |
| `WORKER_MAX_BACKOFF_SECONDS` | Maximum exponential retry backoff for pending messages |
| `LOG_LEVEL` | Application log level |

## Database model

### `links`

- `id`: UUID primary key
- `code`: unique, indexed string (up to 16 characters)
- `original_url`: destination URL
- `created_at`: timestamp with timezone
- `expires_at`: nullable expiration timestamp
- `is_active`: deactivation flag

### `click_events`

- `id`: UUID primary key
- `event_id`: globally unique UUID for idempotent delivery
- `link_id`: foreign key to `links`
- `clicked_at`: timestamp with timezone
- `referrer_domain`: optional referrer host only
- `user_agent_family`: optional family label, not the raw user-agent string

The application stores timestamps in UTC. It does not persist raw IP addresses. Total clicks and clicks in the last 24 hours are calculated from indexed PostgreSQL data, not an in-memory counter.

## API contract

All application API routes use `/api/v1`.

### `POST /api/v1/links`

Create a short link. Optional `expires_at` must include a timezone and be in the future.

```bash
curl -sS http://localhost:8000/api/v1/links \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/products","expires_at":null}'
```

Success returns HTTP `201` with `code`, `short_url`, `original_url`, `created_at`, and `expires_at`. Short URLs use `PUBLIC_BASE_URL`, never an incoming Host header.

### `GET /{code}`

Resolve and redirect with HTTP `302`. Returns `404` for unknown codes and `410` for expired/deactivated links. Queue failure does not block the redirect, but it is logged.

```bash
curl -i http://localhost:8000/AbCdEfG
```

### `GET /api/v1/links/{code}/stats`

Returns total clicks, clicks in the last 24 hours, created time, and expiry. Unknown links return `404`; expired/deactivated links return `410`; links with no events return counts of zero.

```bash
curl -sS http://localhost:8000/api/v1/links/AbCdEfG/stats
```

### `POST /api/v1/links/{code}/deactivate`

Administrative-only operation; requires `X-Admin-Token` matching `ADMIN_API_TOKEN`. It returns `204` and invalidates the cached mapping. When no admin token is configured the operation returns `503`; incorrect/missing tokens return `403`.

### `GET /health` and `GET /ready`

`/health` is lightweight process liveness. `/ready` checks PostgreSQL and Redis and returns `503` when a required dependency is unavailable.

Errors use a consistent envelope such as `{"error":{"code":"link_not_found","message":"This short link was not found."}}`. Request-validation errors use HTTP `422` and include field-level messages without echoing the complete submitted URL.

## Security and limitations

- The app accepts only HTTP/HTTPS destinations and rejects embedded credentials, malformed hosts, and overlong URLs. It does not fetch the destination URL, and URL-format validation does **not** prove a destination is benign.
- Public short links can be abused for phishing. The current version does not include reputation checks, user accounts, ownership, or a public report-abuse workflow.
- Link creation uses rate limiting. The Redis-backed rolling-window limiter uses a process-local fallback while Redis is unreachable; that fallback is not shared across multiple API processes. A small circuit breaker prevents repeated Redis timeouts from delaying every request.
- Raw visitor IP addresses and raw user-agent strings are not stored in analytics. Referrer host and a coarse user-agent family may still be sensitive in some contexts.
- Clicks can be lost when Redis loses queued data, a queue write fails, or a dead-letter event is not repaired. Analytics may lag behind redirects.
- The initial analytics summary is aggregate counts only; it does not provide time-series charts, geolocation, unique-user detection, or per-link access control.
- Link deactivation has no user-ownership model in this version; protect the admin token carefully.

## Tests

Backend:

```bash
cd backend
pip install -e '.[test]'
pytest
```

Frontend:

```bash
cd frontend
npm install
npm test
npm run build
```

Backend tests use isolated SQLite fixtures for deterministic query/API checks and fake cache/queue adapters. Full end-to-end verification against PostgreSQL and Redis requires those services running; the environment this code was authored in did not include preconfigured application databases. Do not treat successful unit/API fixture tests as proof of a production-style PostgreSQL + Redis deployment.

### Verification status for this source snapshot

- Backend: **37 Pytest tests passed**; Python modules compile successfully.
- Migration: the initial Alembic migration was applied to a temporary SQLite database and both tables were verified. PostgreSQL-specific migration execution still needs to be run against a real PostgreSQL service.
- Frontend: all 10 TypeScript/TSX files passed syntax transpilation. Vite build and Vitest were **not run** because the frontend dependencies were not installed in the authoring environment and package-registry access was unavailable.
- Integration: a live PostgreSQL + Redis end-to-end run remains outstanding. The tests currently use isolated SQLite and fake Redis adapters, so they validate application logic but not live service compatibility.
