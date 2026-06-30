# syntax: docker/dockerfile:1
# --- builder stage ---
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# --- runtime stage ---
FROM python:3.12-slim
WORKDIR /app

# curl needed for compose healthcheck (CMD-SHELL curl /healthz)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r uber && useradd -r -g uber uber

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY alembic.ini .
COPY alembic/ alembic/
COPY src/ src/

USER uber
EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "alembic upgrade head && uvicorn uber.main:create_app --factory --host 0.0.0.0 --port 8000"]
