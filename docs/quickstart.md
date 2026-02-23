# Quickstart Guide

Get from zero to your first API call in under 10 minutes.

---

## Prerequisites

- **Python 3.11+** (`python3 --version`)
- **Git**
- **Docker** (optional - for containerised setup)

---

## 1. Clone and install

```bash
git clone https://github.com/pawel-wyszomirski/participation-architecture.git
cd participation-architecture
pip install -r requirements.txt
```

---

## 2. Ingest governance data

Downloads ~400 Arbitrum DAO proposals from Snapshot.org into a local SQLite database:

```bash
python3 app/services/snapshot_client.py
```

You should see output like:

```
Fetching proposals from Snapshot...
Ingested 399 proposals into participation.db
```

> **No external API key required.** The Snapshot GraphQL API is public.

---

## 3. Run the API server

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

You should see:

```
======================================================================
PARTICIPATION ARCHITECTURE API v0.7.0
======================================================================
  Rule Engine:    v2.7.0 (21 rules)
  Fatigue Engine: v1.0.0
  API Docs: http://localhost:8000/docs
======================================================================
```

---

## 4. Your first API calls

### Health check

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "version": "0.7.0",
  "database": "connected",
  "proposals_count": 399,
  "rule_engine": "initialized",
  "rulebook_version": "2.7.0",
  "fatigue_engine": "initialized",
  "fatigue_config_version": "1.0.0"
}
```

### Proposals feed sorted by priority

```bash
curl http://localhost:8000/proposals/feed
```

### High-priority proposals only

```bash
curl "http://localhost:8000/proposals/feed?min_priority=80"
```

### Filter by label

```bash
curl "http://localhost:8000/proposals/feed?label=TREASURY_TIER_1"
```

### Delegate Fatigue Index

```bash
curl http://localhost:8000/delegates/0x1234/fatigue
```

---

## 5. Explore with Swagger UI

Open **http://localhost:8000/docs** in your browser.

Every endpoint is interactive - you can try requests directly from the browser without any extra tooling.

---

## 6. Run the test suite

```bash
python3 -m pytest tests/ -v
```

Expected output: **55 passed** in ~2 seconds.

```
tests/fatigue/test_fatigue_engine.py   25 passed
tests/rules/test_rule_engine.py        30 passed
============================== 55 passed in 1.40s ==============================
```

---

## Docker alternative

If you prefer containers:

```bash
docker compose up
```

Then:

```bash
curl http://localhost:8000/health
```

---

## What's next

| Goal | Where to go |
|---|---|
| Understand all endpoints | [API Reference](api-reference.md) |
| Learn about Fatigue Index | [Delegate Fatigue Index](delegate-fatigue-index.md) |
| Integrate in Python | [examples/python_example.py](examples/python_example.py) |
| Integrate in TypeScript | [examples/typescript_example.ts](examples/typescript_example.ts) |
| Customize triage rules | [Video Tutorial 3](tutorials/video-03-customize-rulebook.md) |
| Full interactive docs | http://localhost:8000/docs |
