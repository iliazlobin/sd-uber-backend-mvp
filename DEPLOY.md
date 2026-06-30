# Deploy Guide - Uber MVP Backend

Stack: FastAPI + PostgreSQL 16 + Redis 7, containerized with Docker Compose.

## Prerequisites

- Docker Engine 24+ with Compose v2
- No running services on host port 8020 (override with APP_PORT if needed)

## Quick Start (from clean checkout)

```bash
git clone <repo-url> uber-mvp && cd uber-mvp
cp .env.example .env                       # optional
docker compose up --build -d
docker compose ps                           # verify all healthy
curl -f http://localhost:${APP_PORT:-8020}/healthz
# -> {"status":"ok","db":"connected"}
```

The app is now serving at http://localhost:8020.

## Environment Variables

All variables are set in docker-compose.yml with sensible defaults.
See .env.example for documentation.

- DATABASE_URL = postgresql+asyncpg://postgres:postgres@db:5432/uber
- REDIS_URL = redis://redis:6379/0
- HOST = 0.0.0.0
- PORT = 8000
- LOG_LEVEL = info

## Local Development (without Docker)

Requires local PostgreSQL 16 and Redis 7 on default ports (5432, 6379).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/uber
export REDIS_URL=redis://localhost:6379/0

createdb uber 2>/dev/null || true
alembic upgrade head
uvicorn uber.main:app --host 0.0.0.0 --port 8000
```

Run unit tests:

```bash
pytest tests/ -v
```

### Acceptance tests (black-box, against running stack)

```bash
pip install httpx pytest
export API_BASE_URL=http://localhost:8020
pytest verify/acceptance/ -v
```

### Host e2e loop

The verify/manifest.env file wires the host e2e verifier.
From the project root:

```bash
source verify/manifest.env
eval "$UP"
eval "$READY"
pip install $TEST_DEPS pytest
eval "$ACCEPTANCE"
eval "$DOWN"
```

## Tear Down

```bash
docker compose down          # stop containers
docker compose down -v       # also remove volumes
```

## Troubleshooting

Port 8020 already in use:
```bash
APP_PORT=8021 docker compose up -d
```

App fails to start (DB connection refused):
```bash
docker compose logs db      # Postgres startup
docker compose logs redis   # Redis startup
docker compose logs app     # App startup + migration errors
```

Healthcheck never passes:
```bash
docker compose logs app | tail -30
```

Migrations fail:
```bash
docker compose exec app alembic upgrade head
docker compose exec app alembic current
```

Need a fresh database:
```bash
docker compose down -v
docker compose up --build -d
```