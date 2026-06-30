# Uber MVP — Engineering Spec

> **Variant:** mvp · **Service Type:** Backend · **Stack:** Python 3.12 · FastAPI · PostgreSQL 16 · Redis 7 · Docker Compose

## 1. Goal & scope

Build a monolithic MVP of the Uber ride-hailing backend — riders request trips with upfront fare estimates, nearest-driver matching via Redis GEORADIUS with PostgreSQL CAS for exactly-once assignment, and a full trip lifecycle from PENDING through MATCHED, PICKED_UP, to COMPLETED.

**In scope**
- Ride request with pickup/dropoff coordinates and upfront fare estimate (Haversine × $1.50/km)
- Nearest-driver matching via Redis GEO proximity query with atomic PostgreSQL CAS
- Driver location updates (GPS + status) synced to PostgreSQL and Redis
- Trip lifecycle: pickup → complete, with receipt and fare calculation
- Exactly-once matching — concurrent requests produce exactly one assignment
- Trip status queries at any lifecycle stage
- Health check with database probe

**Out of scope**
- Real-time WebSocket tracking of driver position
- ETA prediction beyond linear estimate
- Surge pricing and dynamic multipliers
- H3 hexagonal geospatial indexing
- Actual payment processing (fares computed and stored only)
- Paginated trip history
- Cancellation flow (CANCELLED status exists in schema, no endpoint)
- Driver onboarding, rating system, or admin panel

## 2. Functional requirements

- **FR-1 — Request a Ride.** Create a new trip with pickup/dropoff coordinates, upfront Haversine fare estimate, and PENDING status → `POST /rides` (rider_id, pickup_lat/lng, dropoff_lat/lng) → `201`; missing field/invalid coordinate → `422`; non-existent rider → `404`.

- **FR-2 — Match with Nearest Driver.** Atomic nearest-driver assignment via Redis GEORADIUS + PostgreSQL CAS (exactly-once guarantee) → `POST /rides/{id}/match` (no body) → `200` with driver_id, location, distance, ETA, MATCHED; not PENDING → `409`; no drivers within 5 km → `503`.

- **FR-3 — Driver Location Tracking.** Update driver GPS coordinates and status (ONLINE/BUSY/OFFLINE); query nearby ONLINE drivers sorted by distance → `POST /drivers/{id}/location` (lat, lng, status) → `200`; `GET /drivers/nearby` (lat, lng, radius_km) → `200` ordered list; invalid status → `422`; non-existent driver → `404`.

- **FR-4 — Trip Lifecycle.** Driver picks up rider (MATCHED → PICKED_UP), completes trip (PICKED_UP → COMPLETED) with distance-based fare receipt → `POST /rides/{id}/pickup` (driver_id) → `200`; `POST /rides/{id}/complete` (driver_id, distance_km, duration_minutes) → `200` with fare; wrong driver → `403`; invalid state transition → `409`; driver released ONLINE after completion.

- **FR-5 — Trip Status.** Retrieve full trip details at any lifecycle stage → `GET /rides/{id}` → `200` with all fields including assigned driver and timestamps; non-existent → `404`.

## 3. Stack & deployment

- Runtime: Python 3.12 · FastAPI · Uvicorn
- Datastore: PostgreSQL 16 (source of truth) · Redis 7 (driver geo cache)
- Tests: pytest · pytest-asyncio · httpx
- Deploy: Docker Compose (app + postgres + redis)
- Design → [System Design: Uber](https://notion.so/iliazlobin/System-Design-Uber-38ad865005a8811f996efeb82e64115f) · Board: `projects`

## 4. Data model

```sql
Rider {
  rider_id:   uuid PK
  name:       text
  created_at: timestamptz
}

Driver {
  driver_id:    uuid PK
  name:         text
  vehicle_type: text
  status:       text    ← CHECK (ONLINE | BUSY | OFFLINE)
  lat:          float8
  lng:          float8
  last_ping:    timestamptz
  created_at:   timestamptz
}

Trip {
  trip_id:        uuid PK
  rider_id:       uuid FK → Rider
  driver_id:      uuid FK → Driver   ← nullable until matched
  pickup_lat:     float8
  pickup_lng:     float8
  dropoff_lat:    float8
  dropoff_lng:    float8
  fare_estimate:  integer             ← cents
  fare_actual:    integer             ← cents, null until completed
  status:         text                ← CHECK (PENDING | MATCHED | PICKED_UP | COMPLETED | CANCELLED)
  created_at:     timestamptz
  picked_up_at:   timestamptz
  completed_at:   timestamptz
}
```

## 5. API

- `POST /riders` — Create rider
- `POST /drivers` — Create driver
- `POST /drivers/{id}/location` — Update driver GPS + status
- `GET /drivers/nearby` — List nearby ONLINE drivers sorted by distance
- `POST /rides` — Request a ride (FR-1)
- `GET /rides/{id}` — Trip status (FR-5)
- `POST /rides/{id}/match` — Match to nearest driver (FR-2)
- `POST /rides/{id}/pickup` — Driver picks up rider (FR-4)
- `POST /rides/{id}/complete` — Complete trip, return receipt (FR-4)
- `GET /healthz` — Health check with database probe

## 6. Test scenarios

- Exactly-once matching: two concurrent match requests → one 200, one 409; two trips for one driver → driver assigned to exactly one
- State machine enforcement: cannot pickup PENDING (409), cannot complete MATCHED without pickup (409), cannot complete PENDING (409)
- Driver authorization: only assigned driver can pickup/complete (403 for wrong driver)
- Nearest-driver ordering: closer driver before farther in nearby results
- Status filtering: BUSY and OFFLINE drivers excluded from nearby queries
- Validation: missing fields → 422, invalid coordinates → 422, invalid status enum → 422, non-existent entities → 404
- Fare correctness: creation fare = Haversine × 150 cents/km; completion fare = reported distance × 150 cents/km
- Driver release: after completion, driver returns to ONLINE and reappears in nearby queries

## 7. Module layout

```
src/uber/
├── main.py              # create_app(), lifespan, router mounting
├── config.py            # pydantic Settings
├── database.py          # async SQLAlchemy engine + sessionmaker
├── redis_client.py      # async Redis client
├── models/
│   ├── rider.py         # Rider ORM
│   ├── driver.py        # Driver ORM (CHECK status)
│   └── trip.py          # Trip ORM (CHECK status)
├── schemas/
│   ├── rider.py         # RiderCreate, RiderResponse
│   ├── driver.py        # DriverCreate, DriverResponse, DriverLocationUpdate, NearbyDriver
│   ├── ride.py          # RideRequest, RideResponse, RideMatchResponse
│   ├── trip.py          # TripPickup/Complete request/response, TripResponse
│   └── health.py        # HealthResponse
├── routers/
│   ├── health.py        # GET /healthz
│   ├── riders.py        # POST /riders
│   ├── drivers.py       # POST /drivers, POST …/location, GET …/nearby
│   └── rides.py         # POST /rides, GET …/…, POST …/match, …/pickup, …/complete
└── services/
    ├── ride_service.py      # Trip creation, Haversine, status lookup
    ├── driver_service.py    # Driver CRUD, location sync (PG+Redis), nearby
    ├── matching_service.py  # GEORADIUS + PG CAS, exactly-once assignment
    └── trip_service.py      # Trip FSM: pickup/complete, fare, driver release
```

## 8. Run

```bash
docker compose up -d
curl http://localhost:8000/healthz
pytest tests/ verify/acceptance/ -v
```
