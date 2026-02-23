# API Reference

**Base URL:** `http://localhost:8000`
**Version:** `0.7.0`
**Interactive docs:** `/docs` (Swagger UI)

All responses are JSON. All timestamps are ISO 8601 UTC.

---

## System

### `GET /`

Root endpoint. Returns API status.

**Response:**
```json
{
  "message": "Participation Architecture API v0.7.0",
  "status": "operational",
  "milestone": "M2 - Fatigue Index + Full API",
  "docs": "/docs"
}
```

---

### `GET /health`

Health check with engine status and database stats.

**Response:**
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

| Field | Type | Description |
|---|---|---|
| `status` | string | `ok` or `error` |
| `database` | string | `connected` or `disconnected` |
| `proposals_count` | int | Total proposals in DB |
| `rule_engine` | string | `initialized` or `not_initialized` |
| `rulebook_version` | string | Loaded rulebook version (e.g. `2.7.0`) |
| `fatigue_engine` | string | `initialized` or `not_initialized` |
| `fatigue_config_version` | string | Loaded config version (e.g. `1.0.0`) |

---

## Proposals

### `GET /proposals/feed`

Paginated proposals feed sorted by `priority_score` descending.
All proposals are triaged against the deterministic rulebook in real time.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | int | `1` | Page number (>=1) |
| `limit` | int | `10` | Items per page (1-100) |
| `min_priority` | int | - | Filter: return only proposals with `priority_score >= min_priority` |
| `label` | string | - | Filter: return only proposals containing this label |
| `handling` | string | - | Filter: `urgent_deep_review`, `deep_review`, `standard_review`, `fast_track_ok`, `informational_only` |
| `status` | string | - | Filter by Snapshot state: `active`, `closed`, `pending`, `executed`, `expired` |

**Example requests:**

```bash
# All proposals, page 1
curl "http://localhost:8000/proposals/feed"

# High-priority only
curl "http://localhost:8000/proposals/feed?min_priority=80"

# Treasury tier 1 proposals
curl "http://localhost:8000/proposals/feed?label=TREASURY_TIER_1"

# Active proposals requiring deep review
curl "http://localhost:8000/proposals/feed?handling=deep_review&status=active"
```

**Response:**
```json
{
  "proposals": [
    {
      "id": "0x1a2b3c...",
      "title": "ArbOS Version 32 Upgrade",
      "priority_score": 92,
      "labels": ["PROTOCOL_UPGRADE", "LONG_FORM"],
      "reasons": ["TECH-001-STRICT", "WORKLOAD-MODIFIERS"],
      "recommended_handling": "urgent_deep_review",
      "metadata": {
        "author": "0xabc...",
        "state": "active",
        "votes": 1243,
        "scores_total": 284500000.0,
        "created_at": "2026-01-10T12:00:00Z",
        "start_at": "2026-01-10T12:00:00Z",
        "end_at": "2026-01-17T12:00:00Z"
      }
    }
  ],
  "total": 399,
  "page": 1,
  "limit": 10,
  "has_next": true
}
```

**`recommended_handling` values and meaning:**

| Value | Priority score | Meaning |
|---|---|---|
| `urgent_deep_review` | >=90 | Active security incident or critical protocol change |
| `deep_review` | 75-89 | High-impact proposal requiring thorough analysis |
| `standard_review` | 50-74 | Normal governance proposal |
| `fast_track_ok` | 25-49 | Routine or operational item |
| `informational_only` | <25 | Historical, informational, or low-stakes item |

---

### `GET /proposals/{proposal_id}`

Single proposal with full triage audit trail.

**Path parameter:** `proposal_id` - Snapshot proposal ID (hex string, e.g. `0x1a2b3c...`)

**Response** (extends feed item with `body` and `explain`):
```json
{
  "id": "0x1a2b3c...",
  "title": "ArbOS Version 32 Upgrade",
  "body": "Full proposal text...",
  "priority_score": 92,
  "labels": ["PROTOCOL_UPGRADE", "LONG_FORM"],
  "reasons": ["TECH-001-STRICT", "WORKLOAD-MODIFIERS"],
  "recommended_handling": "urgent_deep_review",
  "metadata": { "...": "..." },
  "explain": {
    "base_score": 80,
    "adjustments": ["+10 TIME-MODIFIERS", "+5 WORKLOAD-MODIFIERS"],
    "final_score": 92
  }
}
```

**Error responses:**
- `404` - Proposal not found
- `503` - Rule engine not initialized

---

## Delegates

### `GET /delegates/{address}/fatigue`

Delegate Fatigue Index (DFI) - ecosystem governance workload score.

**Path parameter:** `address` - Delegate wallet address (any string; currently ecosystem-level, address is forward-compatible for future per-delegate signals).

**Response:**
```json
{
  "address": "0x1234...",
  "fatigue_score": 61.3,
  "status": "HIGH",
  "components": {
    "volume": 0.72,
    "concurrency": 0.60,
    "burstiness": 0.40,
    "reading_time": 0.38,
    "novelty": 0.20
  },
  "metrics": {
    "proposals_7d": 7,
    "proposals_30d": 22,
    "concurrent_active": 6,
    "avg_word_count": 2280.5,
    "weekly_avg": 5.08,
    "novelty_ratio": 0.182
  },
  "weights": {
    "volume": 0.40,
    "concurrency": 0.25,
    "burstiness": 0.20,
    "reading_time": 0.10,
    "novelty": 0.05
  },
  "config_version": "1.0.0",
  "computed_at": "2026-02-23T10:00:00Z",
  "formula": "DFI = (0.40xvolume + 0.25xconcurrency + 0.20xburstiness + 0.10xreading_time + 0.05xnovelty) x 100"
}
```

| Field | Description |
|---|---|
| `fatigue_score` | Final DFI score: 0.0 (no load) to 100.0 (maximum load) |
| `status` | `LOW` / `MODERATE` / `HIGH` / `CRITICAL` |
| `components` | Per-component scores, each in [0.0, 1.0] |
| `metrics` | Raw source metrics used to derive components |
| `weights` | Weights from `fatigue_config.yaml` (sum = 1.0) |
| `formula` | Exact formula used - included in every response |

**Status thresholds (from `fatigue_config.yaml`):**

| Status | Score range | Interpretation |
|---|---|---|
| `LOW` | < 30 | Healthy engagement, normal participation |
| `MODERATE` | 30 - 69 | Elevated but manageable workload |
| `HIGH` | 70 - 84 | Significant load - prioritize triage |
| `CRITICAL` | >= 85 | Overload risk - consider batching / scheduling |

> See [Delegate Fatigue Index](delegate-fatigue-index.md) for full component documentation.

---

### `GET /delegates/{address}/fatigue/history`

Historical DFI snapshots for auditing and trend analysis.

**Path parameter:** `address` - Delegate wallet address

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | int | `20` | Number of snapshots to return (1-100) |

**Response:**
```json
[
  {
    "computed_at": "2026-02-23T10:00:00Z",
    "fatigue_score": 61.3,
    "status": "HIGH",
    "proposals_30d": 22,
    "concurrent_active": 6
  },
  {
    "computed_at": "2026-02-22T09:00:00Z",
    "fatigue_score": 54.1,
    "status": "MODERATE",
    "proposals_30d": 19,
    "concurrent_active": 4
  }
]
```

Results are ordered newest first.

---

## Debug

These endpoints expose internal state for development and inspection.

### `GET /debug/proposals`

Returns raw DB rows (no triage). Useful for inspecting ingested data.

**Query parameter:** `limit` (default: 5)

---

### `GET /debug/rulebook`

Returns loaded rulebook metadata.

**Response:**
```json
{
  "version": "2.7.0",
  "rules_count": 21,
  "categories": ["SEC", "TECH", "TRE", "GOV", "PROG", "META", "SPON", "REP", "RES", "OPS", "CTX"]
}
```

---

### `GET /debug/fatigue-config`

Returns loaded fatigue configuration.

**Response:**
```json
{
  "version": "1.0.0",
  "formula": "DFI = (0.40xvolume + 0.25xconcurrency + 0.20xburstiness + 0.10xreading_time + 0.05xnovelty) x 100",
  "weights": {
    "volume": 0.40,
    "concurrency": 0.25,
    "burstiness": 0.20,
    "reading_time": 0.10,
    "novelty": 0.05
  },
  "reference_values": {
    "volume_7d": 5,
    "volume_30d": 20,
    "concurrent": 5,
    "reading_words": 3000
  },
  "thresholds": {
    "low": 30,
    "moderate": 70,
    "high": 85
  }
}
```

---

## Error codes

| HTTP code | Meaning |
|---|---|
| `200` | Success |
| `404` | Proposal not found |
| `422` | Validation error (invalid query parameter) |
| `503` | Engine not initialized (rulebook.yaml or fatigue_config.yaml not found) |
