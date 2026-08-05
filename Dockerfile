# Multi-stage build for production optimization

# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Install runtime libs for Postgres
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

# Create non-root user for security and grant ownership of /app so the
# uvicorn process can write SQLite journal/WAL files alongside the DB.
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Z14: entrypoint zasila korpus przed startem serwera. Do v0.1.0 kontener
# uruchamial sam uvicorn, wiec API wstawalo na pustej bazie i odpowiadalo "ok".
COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]