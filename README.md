# Uber MVP Backend

Ride-matching backend for an Uber-like service — riders request trips, the system finds the nearest available driver via Redis geospatial queries with atomic PostgreSQL CAS for exactly-once assignment, and trips flow through a PENDING → MATCHED → PICKED_UP → COMPLETED state machine with automated fare calculation.

**Stack:** Python 3.12 · FastAPI · PostgreSQL 16 · Redis 7 · SQLAlchemy (async) · Docker Compose

## Quickstart

```bash
cp .env.example .env
docker compose up --build -d
curl -f http://localhost:8020/healthz
# {"status":"ok","db":"connected"}
```

Override the host port:
```bash
APP_PORT=8021 docker compose up -d
```

## Architecture

```
Rider App ── POST /rides ───────────────────────┐
                    │                            │
                    ▼                            │
Driver App ── POST /drivers/{id}/location ──► Redis (drivers:geo + status)
                    │                            │
                    │        ┌───────────────────┘
                    ▼        ▼
            FastAPI REST API (port 8000)
                    │
                    ▼
              PostgreSQL (riders, drivers, trips)
```

Routers are thin — they parse, validate, and delegate to services. Services contain all business logic. The matching service queries Redis `GEORADIUS` to find nearby ONLINE drivers, then uses PostgreSQL `UPDATE … WHERE status='ONLINE' RETURNING *` as an atomic CAS (compare-and-swap) to claim a driver — exactly one concurrent request succeeds.

## API Reference

All endpoints return JSON. Monies in integer cents. Timestamps in ISO 8601.

### Utility

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Health check with DB probe. Returns `{"status":"ok","db":"connected"}` |
| `POST` | `/riders` | Create a rider. Body: `{"name":"Alice"}` → 201 |

### Drivers

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/drivers` | Create a driver (OFFLINE by default). Body: `{"name":"Bob","vehicle_type":"UberX"}` → 201 |
| `POST` | `/drivers/{id}/location` | Update driver GPS and status. Body: `{"lat":40.75,"lng":-73.98,"status":"ONLINE"}` → 200 |
| `GET` | `/drivers/nearby?lat=40.75&lng=-73.98&radius_km=3` | List ONLINE drivers sorted by distance. Returns `[{"driver_id","lat","lng","status","distance_km"}]` |

### Rides (FR-1 through FR-5)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/rides` | Request a ride. Body: `{"pickup_lat","pickup_lng","dropoff_lat","dropoff_lng","rider_id"}` → 201 `{"trip_id","fare_estimate","status":"PENDING"}` |
| `GET` | `/rides/{id}` | Get trip details: status, driver, coordinates, fare. → 200 / 404 |
| `POST` | `/rides/{id}/match` | Match trip to nearest ONLINE driver (Redis GEORADIUS + PG CAS). → 200 `{"driver_id","driver_location","distance_km","eta_estimate","status":"MATCHED"}` / 409 / 503 |
| `POST` | `/rides/{id}/pickup` | Driver picks up rider. Body: `{"driver_id"}` → 200 `{"status":"PICKED_UP","picked_up_at"}` / 403 / 409 |
| `POST` | `/rides/{id}/complete` | Driver completes trip, returns receipt. Body: `{"driver_id","distance_km","duration_minutes"}` → 200 `{"trip_id","fare","distance_km","duration_minutes","status":"COMPLETED"}` / 403 / 409 |

### Error conventions

| Status | Meaning | Example body |
|--------|---------|-------------|
| 422 | Validation error | `{"detail":[{"loc":["body","pickup_lat"],"msg":"…","type":"value_error"}]}` |
| 404 | Entity not found | `{"detail":"Rider not found"}` |
| 403 | Wrong driver | `{"detail":"Driver does not match assigned driver for this trip"}` |
| 409 | State machine violation | `{"detail":"Trip is not in MATCHED state"}` |
| 503 | No available drivers | `{"detail":"No available drivers within 5 km"}` |

### Fare model

Fare estimate on ride creation: Haversine great-circle distance between pickup and dropoff × $1.50/km (150 cents/km), rounded to nearest cent. Completed trips report actual fare = `round(distance_km × 150)` cents.

### Exactly-once matching

Concurrent match requests for the same trip: one gets 200, the other 409. Concurrent match requests for different trips targeting the same driver: the PG CAS (`UPDATE drivers SET status='BUSY' WHERE driver_id=X AND status='ONLINE' RETURNING *`) atomically assigns the driver to exactly one trip; the other request retries or returns 503.

## Configuration

All variables live in `src/uber/config.py` (pydantic-settings) and are overrideable via environment.

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/uber` | asyncpg driver |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `HOST` | `0.0.0.0` | Uvicorn bind address |
| `PORT` | `8000` | Container-internal port |
| `LOG_LEVEL` | `info` | debug / info / warning / error |
| `APP_PORT` | `8020` | Compose: host port to publish |

## Testing

### Unit & functional tests (white-box)

```bash
pip install -e '.[dev]'
pytest tests/ -v
```

### Acceptance tests (black-box, against running system)

```bash
export API_BASE_URL=http://localhost:8020
pytest verify/acceptance/ -v
```

The acceptance suite covers all 5 functional requirements — one file per FR, HTTP-only, no app imports — including concurrent exactly-once matching tests.

## Project Layout

```
├── src/uber/
│   ├── main.py              # App factory + lifespan + /healthz
│   ├── config.py            # pydantic-settings
│   ├── database.py          # Async SQLAlchemy engine + session
│   ├── redis_client.py      # Async Redis client
│   ├── models/              # ORM: Rider, Driver, Trip
│   ├── schemas/             # Pydantic v2 DTOs (request/response)
│   ├── routers/             # Thin HTTP handlers (riders, drivers, rides)
│   └── services/            # Business logic: ride, matching, driver, trip
├── tests/                   # White-box unit + functional tests
├── verify/acceptance/       # Black-box HTTP acceptance tests (1 per FR)
├── alembic/                 # DB migrations (001_initial_schema)
├── Dockerfile               # Multi-stage Python 3.12-slim
├── docker-compose.yml       # PostgreSQL 16 + Redis 7 + app
├── DEPLOY.md                # Deploy guide (host-native + Docker Compose)
└── .env.example             # Environment variable template
```

## Limitations (MVP Scope)

- **No real-time tracking** — no WebSocket stream for driver position updates.
- **No surge pricing** — fare is always $1.50/km, regardless of demand.
- **No ETA prediction** — ETA is a simple linear estimate (`ceil(distance_km × 120)` seconds, ~30 km/h average urban speed), not a neural model like Uber's DeepETA.
- **No actual payment processing** — fares are computed and recorded but not charged. A production system would integrate a payment gateway.
- **No trip history endpoint** — `GET /rides/{id}` retrieves individual trips, but there's no paginated `GET /rides/history` for a rider's past trips.
- **Single-instance matching** — the matching algorithm uses local Redis GEO + PostgreSQL CAS on a single database. A production system would add H3 hexagonal geospatial indexing, Kafka for event-sourced driver state, and batched bipartite matching (DISCO/Hungarian) for global optimality.
- **No cancellation flow** — the `CANCELLED` status exists in the schema but no endpoint triggers it.
- **No authentication** — endpoints are open. A production system would add API keys, OAuth, or session tokens.
