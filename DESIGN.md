# DESIGN.md — Uber MVP Backend

> **Stack:** Python 3.12 · FastAPI · PostgreSQL 16 · Redis 7 · SQLAlchemy (async) · Docker Compose
> **Architecture:** Monolithic REST API. Nearest-driver matching via Redis GEORADIUS with PostgreSQL CAS for exactly-once assignment. Trips follow a state machine: PENDING → MATCHED → PICKED_UP → COMPLETED.

## 1. Scope

### In scope

- Ride request with pickup/dropoff coordinates and upfront fare estimate (Haversine × $1.50/km)
- Nearest-driver matching via Redis GEO proximity query with atomic PostgreSQL CAS
- Driver location updates (GPS + status) synced to PostgreSQL and Redis
- Trip lifecycle: pickup → complete, with receipt and fare calculation
- Exactly-once matching — concurrent requests produce exactly one assignment
- Trip status queries at any lifecycle stage
- Health check with database probe

### Out of scope

- Real-time WebSocket tracking of driver position
- ETA prediction beyond linear estimate
- Surge pricing and dynamic multipliers
- H3 hexagonal geospatial indexing
- Actual payment processing (fares computed and stored only)
- Paginated trip history (`GET /rides/history`)
- Cancellation flow (CANCELLED status exists in schema, no endpoint)
- Driver onboarding, rating system, or admin panel

### Target architecture (production direction)

This MVP implements a single-instance monolithic cut of the full Uber system. The production target would expand to:

- **Batched matching (DISCO):** Buffer 2–5s of ride requests, build a bipartite graph of riders↔drivers, run the Hungarian algorithm for globally optimal assignments instead of greedy nearest-driver.
- **H3 hexagonal indexing:** Replace basic Redis GEORADIUS with Uber's open-source H3 library at resolution 9 (~0.105 km² cells). Every hexagon has six equidistant neighbors, enabling uniform radius expansion — unlike rectangular geohash cells with anisotropic neighbors.
- **Event-sourced driver state via Kafka:** Every state-modifying action (location ping, status change, dispatch) becomes an immutable Kafka event keyed by driver_id. Consumers deduplicate by `{trip_id}:{event_type}` composite keys for exactly-once semantics without distributed locks.
- **DeepETA neural model:** Replace the `ceil(distance × 120)` linear estimate with a neural network trained on 100+ features (traffic, time of day, road segment type, historical patterns).
- **Surge pricing:** Flink jobs compute per-H3-cell supply/demand ratios over 5-minute rolling windows with spatial smoothing across neighboring cells — stored in Redis for fast lookup during fare estimation.
- **Cassandra for trip history:** Partition trip history by rider_id with time-ordered clustering columns, giving O(1) lookups regardless of total trip count.

## 2. Architecture

```
                    ┌──────────────────────────┐
                    │      FastAPI (port 8000)  │
                    │                          │
                    │  Routers (thin):          │
                    │  /riders  /drivers        │
                    │  /rides   /healthz        │
                    │         │                │
                    │         ▼                │
                    │  Services (business):     │
                    │  ride_service             │
                    │  driver_service ◄─── Redis (drivers:geo + status)
                    │  matching_service ◄─┘     │
                    │  trip_service             │
                    │         │                │
                    │         ▼                │
                    │  Models (ORM):            │
                    │  Rider  Driver  Trip      │
                    └──────────┬───────────────┘
                               │
                               ▼
                    ┌──────────────────┐
                    │  PostgreSQL 16    │
                    │  (source of truth)│
                    └──────────────────┘
```

**Layering:** Routers parse and validate input, raise HTTP exceptions, and delegate to services. Services contain all business logic and database/Redis calls. No business logic lives in routers.

**Data flow for matching (the critical path):**

1. `POST /rides/{trip_id}/match` hits the rides router.
2. Router delegates to `matching_service.match_ride(session, redis, trip_id)`.
3. Service loads the trip, guards it's PENDING, then calls `GEORADIUS drivers:geo {lng} {lat} 5 km` on Redis — returns driver IDs sorted by distance.
4. For each candidate driver (nearest first): runs `UPDATE drivers SET status='BUSY' WHERE driver_id=X AND status='ONLINE' RETURNING *`. PostgreSQL's row-level lock under READ COMMITTED makes this atomic — the first concurrent request gets the row, others get zero rows.
5. On CAS success: `UPDATE trips SET driver_id=X, status='MATCHED' WHERE trip_id=Y AND status='PENDING' RETURNING *` — a second CAS layer preventing double-matching if two requests targeted the same trip.
6. On trip-CAS failure: rolls back the driver CAS (sets status back to ONLINE). Returns 409.
7. On success: sets `driver:{id}:status` to BUSY in Redis (driver stays in GEO set so subsequent queries see it and skip it in the CAS loop). Returns 200 with driver info, distance, and ETA.

**Redis as cache, PostgreSQL as authority:** Redis `drivers:geo` provides fast proximity queries. But Redis and PG can drift — a driver might be ONLINE in Redis but BUSY in PostgreSQL due to a race. The PG CAS is the final arbiter: Redis gives you candidate drivers fast, but PG confirms the assignment atomically.

## 3. Data Model

### PostgreSQL

```sql
CREATE TABLE riders (
    rider_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE drivers (
    driver_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    vehicle_type TEXT NOT NULL DEFAULT 'UberX',
    status       TEXT NOT NULL DEFAULT 'OFFLINE'
                 CHECK (status IN ('ONLINE', 'BUSY', 'OFFLINE')),
    lat          DOUBLE PRECISION,
    lng          DOUBLE PRECISION,
    last_ping    TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE trips (
    trip_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rider_id       UUID NOT NULL REFERENCES riders(rider_id),
    driver_id      UUID REFERENCES drivers(driver_id),
    pickup_lat     DOUBLE PRECISION NOT NULL,
    pickup_lng     DOUBLE PRECISION NOT NULL,
    dropoff_lat    DOUBLE PRECISION NOT NULL,
    dropoff_lng    DOUBLE PRECISION NOT NULL,
    fare_estimate  INTEGER NOT NULL,
    fare_actual    INTEGER,
    status         TEXT NOT NULL DEFAULT 'PENDING'
                   CHECK (status IN ('PENDING', 'MATCHED', 'PICKED_UP', 'COMPLETED', 'CANCELLED')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    picked_up_at   TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ
);

CREATE INDEX idx_trips_rider ON trips(rider_id, created_at DESC);
CREATE INDEX idx_trips_driver ON trips(driver_id) WHERE driver_id IS NOT NULL;
```

### Redis

| Key | Type | Purpose |
|-----|------|---------|
| `drivers:geo` | GEO (Sorted Set) | Driver locations for GEORADIUS queries. Only ONLINE drivers. |
| `driver:{id}:status` | String | Cached status (ONLINE/BUSY/OFFLINE) for fast filtering. |

### Key design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| PK type | UUID v4 (`gen_random_uuid`) | No coordination; safe for horizontal scaling |
| Fare storage | INTEGER (cents) | Avoids floating-point rounding |
| Driver status | TEXT with CHECK | Simpler than PG enum migrations |
| Driver FK | Nullable until matched | Trip lifecycle: created unmatched |
| Redis GEO | GEORADIUS, 5 km radius | Built into Redis; sub-ms; no PostGIS/H3 at MVP scale |
| CAS mechanism | `UPDATE … WHERE status='ONLINE' RETURNING *` | Atomic at DB level; row-level lock under READ COMMITTED |
| Redis/PG consistency | PG as authority | Redis is a performance cache; PG CAS is final arbiter |

### Trip state machine

```
PENDING ──match()──► MATCHED ──pickup()──► PICKED_UP ──complete()──► COMPLETED
```

Invalid transitions return 409. Wrong driver returns 403.

## 4. API Contracts

Base URL: `http://localhost:8000` (container) or `http://localhost:${APP_PORT:-8020}` (host).

All responses JSON. Monies in integer cents. Timestamps ISO 8601.

### POST /riders — Create rider
```
Request:  {"name": "Alice"}
Response: 201 {"rider_id": "<uuid>", "name": "Alice", "created_at": "<iso>"}
```

### POST /drivers — Create driver
```
Request:  {"name": "Bob", "vehicle_type": "UberX"}
Response: 201 {"driver_id": "<uuid>", "name": "Bob", "vehicle_type": "UberX",
               "status": "OFFLINE", "lat": null, "lng": null, "created_at": "<iso>"}
```

### POST /drivers/{id}/location — Update driver GPS + status
```
Request:  {"lat": 40.7590, "lng": -73.9845, "status": "ONLINE"}
Response: 200 {"driver_id": "<uuid>", "lat": 40.7590, "lng": -73.9845,
               "status": "ONLINE", "last_ping": "<iso>"}
Errors:   404 driver not found; 422 invalid field/enum
```

### GET /drivers/nearby — List nearby ONLINE drivers
```
Query:    ?lat=40.7580&lng=-73.9855&radius_km=3   (default 3, max 50)
Response: 200 [{"driver_id": "<uuid>", "lat": 40.7590, "lng": -73.9845,
                "status": "ONLINE", "distance_km": 0.15}, ...]
          200 []  — no ONLINE drivers in radius
```
Sorted by distance ascending. Only ONLINE drivers.

### POST /rides — Request a ride (FR-1)
```
Request:  {"pickup_lat": 40.7580, "pickup_lng": -73.9855,
           "dropoff_lat": 40.7484, "dropoff_lng": -73.9857,
           "rider_id": "<uuid>"}
Response: 201 {"trip_id": "<uuid>", "fare_estimate": 215, "status": "PENDING",
               "created_at": "<iso>", ...}
Errors:   422 invalid/missing; 404 rider not found
```
Fare = `round(Haversine(pickup, dropoff) × 150)` cents.

### GET /rides/{id} — Trip status (FR-5)
```
Response: 200 {"trip_id", "rider_id", "driver_id": null|uuid,
               "status": "PENDING"|"MATCHED"|"PICKED_UP"|"COMPLETED",
               "pickup_lat", "pickup_lng", "dropoff_lat", "dropoff_lng",
               "fare_estimate", "fare_actual": null|int,
               "created_at", "picked_up_at": null|iso, "completed_at": null|iso}
Errors:   404 trip not found
```

### POST /rides/{id}/match — Match to nearest driver (FR-2)
```
Request:  (no body)
Response: 200 {"driver_id": "<uuid>",
               "driver_location": {"lat": 40.7590, "lng": -73.9845},
               "distance_km": 0.15, "eta_estimate": 60, "status": "MATCHED"}
Errors:   404 trip not found; 409 not PENDING; 503 no drivers within 5 km
```
ETA: `ceil(distance_km × 120)` seconds (~30 km/h urban speed).

### POST /rides/{id}/pickup — Driver picks up rider (FR-4)
```
Request:  {"driver_id": "<uuid>"}
Response: 200 {"trip_id", "status": "PICKED_UP", "picked_up_at": "<iso>", "driver_id"}
Errors:   404 not found; 403 wrong driver; 409 not MATCHED
```

### POST /rides/{id}/complete — Complete trip, return receipt (FR-4)
```
Request:  {"driver_id": "<uuid>", "distance_km": 5.2, "duration_minutes": 12}
Response: 200 {"trip_id", "status": "COMPLETED", "fare": 780,
               "distance_km": 5.2, "duration_minutes": 12, "completed_at": "<iso>"}
Errors:   404 not found; 403 wrong driver; 409 not PICKED_UP; 422 invalid fields
```
Fare = `round(distance_km × 150)` cents. Driver released ONLINE after completion.

### Error conventions

| Status | When | Example |
|--------|------|---------|
| 422 | Validation | `{"detail":[{"loc":["body","pickup_lat"],"msg":"…","type":"value_error"}]}` |
| 404 | Not found | `{"detail":"Rider not found"}` |
| 403 | Wrong driver | `{"detail":"Driver does not match assigned driver for this trip"}` |
| 409 | State violation | `{"detail":"Trip is not in MATCHED state"}` |
| 503 | No drivers | `{"detail":"No available drivers within 5 km"}` |

## 5. Functional Requirements & Acceptance Tests

Each FR maps to a black-box acceptance test file in `verify/acceptance/`. Tests run against the live system over HTTP — no app imports.

### FR-1: Request a Ride → `test_fr1_request_ride.py`

| Criteria | Test |
|----------|------|
| Valid request → 201 with trip_id, fare_estimate, PENDING | `test_request_ride_creates_trip_with_pending_status` |
| Fare = Haversine × $1.50/km | `test_fare_estimate_is_reasonable` |
| Missing field → 422 | `test_missing_required_field_returns_422` (5 fields parametrized) |
| Invalid coordinate → 422 | `test_invalid_coordinate_returns_422` (8 values) |
| Non-existent rider → 404 | `test_nonexistent_rider_returns_404` |
| Empty body → 422 | `test_empty_json_body_returns_422` |

### FR-2: Match with Nearest Driver → `test_fr2_match_driver.py`

| Criteria | Test |
|----------|------|
| Match returns driver_id, location, distance, ETA, MATCHED | `test_match_returns_driver_info` |
| After match, GET shows MATCHED + assigned driver | `test_match_sets_trip_to_matched` |
| Already matched → 409 | `test_already_matched_returns_409` |
| No drivers within 5 km → 503 | `test_no_available_drivers_returns_503` |
| Non-existent trip → 404 | `test_nonexistent_trip_returns_404` |
| Concurrent match on same trip: one 200, one 409 | `test_concurrent_match_same_trip_one_succeeds` |
| Two trips one driver: driver assigned exactly once | `test_driver_not_double_assigned` |

### FR-3: Driver Location Tracking → `test_fr3_driver_location.py`

| Criteria | Test |
|----------|------|
| POST location updates coordinates | `test_update_location_sets_coordinates` |
| Status transitions ONLINE→BUSY→OFFLINE | `test_update_location_changes_status` |
| Non-existent driver → 404 | `test_update_nonexistent_driver_returns_404` |
| Missing field → 422 | `test_missing_field_returns_422` |
| Invalid status enum → 422 | `test_invalid_status_returns_422` |
| Nearby: empty when no drivers | `test_returns_empty_list_when_no_drivers` |
| Nearby: ONLINE driver appears | `test_returns_online_driver` |
| Nearby: sorted by distance ascending | `test_sorted_by_distance_ascending` |
| Nearby: excludes BUSY drivers | `test_excludes_busy_drivers` |
| Nearby: excludes OFFLINE drivers | `test_excludes_offline_drivers` |
| Nearby: respects radius_km | `test_respects_radius_km` |
| Nearby: missing params → 422 | `test_missing_query_params_returns_422` |

### FR-4: Trip Lifecycle → `test_fr4_trip_lifecycle.py`

| Criteria | Test |
|----------|------|
| Pickup sets PICKED_UP + timestamp | `test_pickup_sets_status_to_picked_up` |
| Pickup sets picked_up_at | `test_pickup_sets_picked_up_at_timestamp` |
| Pickup on PENDING → 409 | `test_pickup_not_matched_returns_409` |
| Wrong driver pickup → 403 | `test_wrong_driver_returns_403` |
| Pickup non-existent → 404 | `test_pickup_nonexistent_trip_returns_404` |
| Complete sets COMPLETED + receipt | `test_complete_sets_status_to_completed` |
| Fare = distance × $1.50/km | `test_fare_calculation` (3 parametrized distances) |
| Complete on MATCHED → 409 | `test_complete_not_picked_up_returns_409` |
| Wrong driver complete → 403 | `test_complete_wrong_driver_returns_403` |
| Missing distance/duration → 422 | `test_complete_missing_fields_returns_422` |
| Non-existent trip → 404 | `test_complete_nonexistent_trip_returns_404` |
| Negative distance → 422 | `test_complete_negative_distance_returns_422` |
| Driver released ONLINE after completion | `test_driver_released_after_completion` |

### FR-5: Trip Status → `test_fr5_trip_status.py`

| Criteria | Test |
|----------|------|
| GET PENDING: all fields, null driver | `test_get_pending_trip` |
| GET MATCHED: shows driver + status | `test_get_matched_trip` |
| GET COMPLETED: fare_actual + completed_at | `test_get_completed_trip_shows_fare` |
| Non-existent → 404 | `test_nonexistent_trip_returns_404` |
| Full lifecycle PENDING→MATCHED→PICKED_UP→COMPLETED | `test_full_lifecycle_transitions` |

## 6. Test Scenarios (Edge Cases)

- **Exactly-once matching:** Two concurrent `POST /rides/{id}/match` → one 200, one 409. Two concurrent trips for one driver → driver assigned to exactly one.
- **State machine:** Cannot pickup PENDING (409). Cannot complete MATCHED without pickup (409). Cannot complete PENDING (409).
- **Driver authorization:** Only assigned driver can pickup/complete (403 for wrong driver).
- **Nearest-driver ordering:** Closer driver appears before farther driver in nearby results.
- **Status filtering:** BUSY and OFFLINE drivers excluded from nearby queries.
- **Validation:** Missing fields → 422. Invalid coordinates → 422. Invalid status enum → 422. Non-existent entities → 404.
- **Fare correctness:** Creation fare = Haversine × 150 cents/km. Completion fare = reported distance × 150 cents/km. Parametrized at 3 distances.
- **Driver release:** After completion, driver returns to ONLINE and reappears in nearby queries.

## 7. Project Layout

```
sd-uber-backend-mvp/
├── src/uber/
│   ├── main.py              # create_app(), lifespan, router mounting
│   ├── config.py            # pydantic Settings
│   ├── database.py          # async SQLAlchemy engine + sessionmaker
│   ├── redis_client.py      # async Redis client + connection pool
│   ├── models/
│   │   ├── rider.py         # Rider ORM
│   │   ├── driver.py        # Driver ORM (CHECK status)
│   │   └── trip.py          # Trip ORM (CHECK status)
│   ├── schemas/
│   │   ├── rider.py         # RiderCreate, RiderResponse
│   │   ├── driver.py        # DriverCreate, DriverResponse, DriverLocationUpdate, NearbyDriver
│   │   ├── ride.py          # RideRequest, RideResponse, RideMatchResponse
│   │   ├── trip.py          # TripPickup/Complete request/response, TripResponse
│   │   └── health.py        # HealthResponse
│   ├── routers/
│   │   ├── health.py        # GET /healthz
│   │   ├── riders.py        # POST /riders
│   │   ├── drivers.py       # POST /drivers, POST /drivers/{id}/location, GET /drivers/nearby
│   │   └── rides.py         # POST /rides, GET /rides/{id}, POST …/match, …/pickup, …/complete
│   └── services/
│       ├── ride_service.py      # Trip creation, Haversine, status lookup
│       ├── driver_service.py    # Driver CRUD, location sync (PG+Redis), nearby
│       ├── matching_service.py  # GEORADIUS + PG CAS, exactly-once assignment
│       └── trip_service.py      # Trip FSM: pickup/complete, fare, driver release
├── tests/
│   ├── conftest.py              # Test DB, async client, seeded data
│   ├── unit/
│   │   ├── test_health.py
│   │   ├── test_ride_service.py
│   │   └── test_trip_service.py
│   └── functional/
│       └── test_ride_api.py
├── verify/
│   ├── manifest.env             # Host e2e loop configuration
│   └── acceptance/
│       ├── conftest.py          # API_BASE_URL, httpx client, helpers, fixtures
│       ├── test_fr1_request_ride.py
│       ├── test_fr2_match_driver.py
│       ├── test_fr3_driver_location.py
│       ├── test_fr4_trip_lifecycle.py
│       └── test_fr5_trip_status.py
├── alembic/
│   ├── env.py
│   └── versions/001_initial_schema.py
├── pyproject.toml
├── Dockerfile                   # Multi-stage Python 3.12-slim
├── docker-compose.yml           # PostgreSQL 16 + Redis 7 + app; healthchecks on all
├── .env.example
├── README.md
├── DESIGN.md                    # This file
└── DEPLOY.md
```
