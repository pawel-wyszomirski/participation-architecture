<div align="center">

# Participation Architecture

### Governance Data Pipeline & Deterministic Triage Rules for DAOs

**A developer-first REST API to normalize governance data and apply transparent priority rules**

![Status](https://img.shields.io/badge/Status-v0.1.0%20Released-green)
![Stack](https://img.shields.io/badge/Stack-FastAPI%20%7C%20Docker%20%7C%20SQLite-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Tests](https://img.shields.io/badge/Tests-55%2F55%20Passing-brightgreen)
![Grant](https://img.shields.io/badge/Supported%20by-Arbitrum%20Grants-blue)

**Supported by [Arbitrum Grants Program](https://questbook.app/dashboard/?grantId=67d802bd46da2f90cc3267b0&chainId=10&role=builder&proposalId=69552f08fb7e884efa09de1e&isRenderingProposalBody=true)**

**Live Demo:** [pa.wyszomirski.online](https://pa.wyszomirski.online/docs) | [Health Check](https://pa.wyszomirski.online/health)

[Quick Start](#-quick-start) • [Live Demo](#-live-demo) • [API Endpoints](#-api-endpoints) • [Video Tutorials](#-video-tutorials) • [Delegate Fatigue Index](#-delegate-fatigue-index) • [Tests](#-tests) • [Documentation](#-documentation)

</div>

---

## The Problem

**DAO Governance suffers from information overload and fragmented data sources.**

- **Symptom:** Declining participation - Arbitrum DAO saw onchain participation fall to 59.83% and offchain to 53.78% (April 2025)
- **Cause:** No standardized triage layer - builders repeatedly implement custom pipelines and priority logic
- **Result:** Delegates burn out from undifferentiated notification streams; tools can't interoperate

**The Solution:** A **reusable governance middleware** - a backend API that normalizes proposals and applies deterministic triage rules, so governance tools can prioritize what matters without building custom infrastructure.

---

## Project Status

**Current Stage:** ✅ **v0.1.0 Released** | ✅ **Milestone 1 Complete** | ✅ **Milestone 2 Complete**

### ✅ Milestone 1: Complete

- ✅ **Core Architecture:** FastAPI microservice + SQLite/PostgreSQL database
- ✅ **Data Ingestion:** Live GraphQL connection to Snapshot.org (Arbitrum DAO)
- ✅ **Database Schema:** 400+ proposals ingested and queryable
- ✅ **Rule Engine:** 21 deterministic rules implemented (`app/services/rule_engine.py`)
- ✅ **Rulebook v2.7.0:** Machine-readable YAML + human-readable documentation (ex ante validated)
- ✅ **API Endpoints:** `/proposals/feed`, `/proposals/{id}`, `/health`
- ✅ **Tests:** 30/30 passing (100% rule coverage)
- ✅ **OpenAPI/Swagger:** Auto-generated interactive documentation

### ✅ Milestone 2: Complete

- ✅ **Delegate Fatigue Index:** `GET /delegates/{address}/fatigue` - 5-component deterministic score
- ✅ **DFI History:** `GET /delegates/{address}/fatigue/history` - audit trail
- ✅ **FatigueSnapshot persistence:** Every computation stored to DB for reproducibility
- ✅ **Tests:** 55/55 passing (25 fatigue + 30 rule engine)
- ✅ **Full Documentation:** Quickstart, API Reference, DFI deep dive
- ✅ **Integration Examples:** Python + TypeScript
- ✅ **Video Tutorials:** [3 published tutorials on YouTube](https://www.youtube.com/playlist?list=PLCETnIPtht9YHuvg6XsoGJuWsr_4ZTPZV)
- ✅ **Live Demo:** [pa.wyszomirski.online](https://pa.wyszomirski.online/docs)
- ✅ **Tagged Release:** [v0.1.0](https://github.com/pawel-wyszomirski/participation-architecture/releases/tag/v0.1.0)

---

## Live Demo

**The API is publicly available for testing and integration:**

| Resource | URL |
|---|---|
| **Swagger UI** | [pa.wyszomirski.online/docs](https://pa.wyszomirski.online/docs) |
| **Health Check** | [pa.wyszomirski.online/health](https://pa.wyszomirski.online/health) |
| **Proposals Feed** | [pa.wyszomirski.online/proposals/feed](https://pa.wyszomirski.online/proposals/feed?limit=5) |

```bash
# Try it now - no setup required
curl "https://pa.wyszomirski.online/proposals/feed?min_priority=80&limit=3"
curl "https://pa.wyszomirski.online/delegates/0x1234/fatigue"
curl "https://pa.wyszomirski.online/health"
```

---

## Architecture

```
┌─────────────┐      ┌──────────────────────┐      ┌─────────────┐
│   Client    │─────▶│  FastAPI v0.7.0       │─────▶│  SQLite     │
│   (Tool)    │◀─────│  Rule Engine v2.7.0   │◀─────│  + Alembic  │
└─────────────┘      │  Fatigue Engine v1.0  │      └─────────────┘
                     └──────────────────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │  Snapshot.org    │
                     │  GraphQL API     │
                     └──────────────────┘
```

**Stack:**
- **API Layer:** FastAPI (async, Pydantic validation, OpenAPI/Swagger)
- **Data Layer:** SQLite/PostgreSQL + SQLAlchemy ORM + Alembic migrations
- **Rule Engine:** YAML-based rulebook with versioning (`rulebook.yaml`)
- **Fatigue Engine:** Configurable 5-component formula (`fatigue_config.yaml`)
- **Deployment:** Docker Compose

---

## Quick Start

### Prerequisites

- **Python 3.11+**
- **Docker** (optional)

### 1. Install

```bash
git clone https://github.com/pawel-wyszomirski/participation-architecture.git
cd participation-architecture
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Ingest Data

```bash
python3 app/services/snapshot_client.py
```

### 3. Run API Server

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Explore

- **Swagger UI:** `http://localhost:8000/docs`
- **Health Check:** `http://localhost:8000/health`

```bash
curl "http://localhost:8000/proposals/feed?min_priority=80"
curl "http://localhost:8000/delegates/0x1234/fatigue"
```

Or use the [live demo](https://pa.wyszomirski.online/docs) without any local setup.

See the full [Quickstart Guide](docs/quickstart.md) or watch [Tutorial 1 on YouTube](https://youtu.be/c12DReTyGqk).

---

## Video Tutorials

[Full playlist on YouTube](https://www.youtube.com/playlist?list=PLCETnIPtht9YHuvg6XsoGJuWsr_4ZTPZV)

| # | Tutorial | YouTube | Script |
|---|---|---|---|
| 1 | **Quickstart** - Clone, run, first API call | [Watch](https://youtu.be/c12DReTyGqk) | [Script](docs/tutorials/video-01-quickstart.md) |
| 2 | **Notification Bot** - Build a governance alert bot | [Watch](https://youtu.be/nkV6J4DW4a4) | [Script](docs/tutorials/video-02-integrate-notifications.md) |
| 3 | **Customize Rulebook** - Add rules and run tests | [Watch](https://youtu.be/hZhBm-ik-vk) | [Script](docs/tutorials/video-03-customize-rulebook.md) |

Runnable demo scripts are included in the repo:
- `scripts/governance_alerts.py` - Alert bot from Tutorial 2
- `scripts/tutorial-03-new-rule.yaml` - Rule snippet from Tutorial 3
- `scripts/tutorial-03-new-tests.py` - Test snippet from Tutorial 3

---

## API Endpoints

### Proposals Feed

```http
GET /proposals/feed?min_priority=80&status=active
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

Query parameters: `page`, `limit`, `min_priority`, `label`, `handling`, `status`.

### Proposal Detail

```http
GET /proposals/{id}
```

Returns full proposal body + `explain` with rule audit trail.

### Delegate Fatigue Index

```http
GET /delegates/{address}/fatigue
```

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
  "weights": { "volume": 0.40, "concurrency": 0.25, "burstiness": 0.20, "reading_time": 0.10, "novelty": 0.05 },
  "config_version": "1.0.0",
  "computed_at": "2026-02-23T10:00:00Z",
  "formula": "DFI = (0.40*volume + 0.25*concurrency + 0.20*burstiness + 0.10*reading_time + 0.05*novelty) * 100"
}
```

### Fatigue History

```http
GET /delegates/{address}/fatigue/history?limit=20
```

Returns last N persisted DFI computations (newest first).

---

## Delegate Fatigue Index

The DFI is a deterministic, reproducible score (0-100) measuring governance workload burden.

### Formula

```
DFI = (0.40*volume + 0.25*concurrency + 0.20*burstiness + 0.10*reading_time + 0.05*novelty) * 100
```

### Components

| Component | Weight | What it measures |
|---|---|---|
| `volume` | 40% | Proposals/7d + proposals/30d normalized against reference |
| `concurrency` | 25% | Simultaneous active proposals right now |
| `burstiness` | 20% | This week's spike vs. 4-week rolling average |
| `reading_time` | 10% | Average word count / baseline (cognitive cost proxy) |
| `novelty` | 5% | Novel-domain proposals / total (new patterns cost more) |

### Status thresholds

| Status | Score | Interpretation |
|---|---|---|
| `LOW` | < 30 | Healthy engagement, normal participation |
| `MODERATE` | 30-69 | Elevated but manageable workload |
| `HIGH` | 70-84 | Significant load - prioritize triage |
| `CRITICAL` | >= 85 | Overload risk - consider batching proposals |

### Theoretical grounding

- **Volume & concurrency:** "Kolektywna uwaga" as rivalrous commons resource (Fogg B=MAP Ability, dissertation 2.3.1)
- **Burstiness:** Habit disruption - irregular spikes prevent stable participation routines (Fogg B=MAP, 2.2.1)
- **Reading time:** Direct Fogg Ability barrier proxy (2.2.1)
- **Novelty:** Novel governance domains require more cognitive processing than routine items (CLT, 1.4)

See [Delegate Fatigue Index documentation](docs/delegate-fatigue-index.md) for full component documentation.

---

## Tests

**Status:** 55/55 Tests Passing (100% coverage)

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run fatigue engine tests only
python3 -m pytest tests/fatigue/ -v

# Run rule engine tests only
python3 -m pytest tests/rules/ -v

# With coverage report
python3 -m pytest --cov=app/services --cov-report=html
```

**Test breakdown:**

| Suite | Tests | Coverage |
|---|---|---|
| Fatigue Engine (`tests/fatigue/`) | 25 | All 5 components, status thresholds, determinism, edge cases |
| Rule Engine (`tests/rules/`) | 30 | All 21 rules, overrides, modifiers, edge cases |
| **Total** | **55** | |

---

## Documentation

| Document | Description |
|---|---|
| [Quickstart Guide](docs/quickstart.md) | Clone to first API call in <=10 minutes |
| [API Reference](docs/api-reference.md) | All endpoints with request/response examples |
| [Delegate Fatigue Index](docs/delegate-fatigue-index.md) | Formula, components, theoretical grounding |
| [Python Example](docs/examples/python_example.py) | Integration example with all endpoints |
| [TypeScript Example](docs/examples/typescript_example.ts) | TypeScript types + notification bot pattern |
| [Rulebook Documentation](rulebook.md) | All 21 triage rules documented |
| [Architecture](architecture.md) | System design and technical details |

### Video Tutorials

| Tutorial | YouTube | Script |
|---|---|---|
| 1. Quickstart | [Watch](https://youtu.be/c12DReTyGqk) | [Script](docs/tutorials/video-01-quickstart.md) |
| 2. Notification Bot | [Watch](https://youtu.be/nkV6J4DW4a4) | [Script](docs/tutorials/video-02-integrate-notifications.md) |
| 3. Customize Rulebook | [Watch](https://youtu.be/hZhBm-ik-vk) | [Script](docs/tutorials/video-03-customize-rulebook.md) |

[Full playlist](https://www.youtube.com/playlist?list=PLCETnIPtht9YHuvg6XsoGJuWsr_4ZTPZV)

**Interactive API docs:** [pa.wyszomirski.online/docs](https://pa.wyszomirski.online/docs) (Swagger UI)

---

## Project Structure

```
├── app/
│   ├── db/
│   │   ├── models.py          # Proposal + FatigueSnapshot ORM models
│   │   └── session.py         # SQLAlchemy session
│   ├── services/
│   │   ├── snapshot_client.py # Snapshot.org GraphQL ingestion
│   │   ├── rule_engine.py     # Deterministic triage rules
│   │   └── fatigue_engine.py  # Delegate Fatigue Index (5-component)
│   └── main.py                # FastAPI app + all endpoints
├── docs/
│   ├── quickstart.md
│   ├── api-reference.md
│   ├── delegate-fatigue-index.md
│   ├── examples/
│   │   ├── python_example.py
│   │   └── typescript_example.ts
│   └── tutorials/
│       ├── video-01-quickstart.md
│       ├── video-02-integrate-notifications.md
│       └── video-03-customize-rulebook.md
├── scripts/
│   ├── governance_alerts.py           # Runnable alert bot demo
│   ├── tutorial-03-new-rule.yaml      # Rule snippet for Tutorial 3
│   └── tutorial-03-new-tests.py       # Test snippet for Tutorial 3
├── tests/
│   ├── fatigue/
│   │   └── test_fatigue_engine.py  (25 tests)
│   └── rules/
│       └── test_rule_engine.py     (30 tests)
├── alembic/                   # DB migrations
├── rulebook.yaml              # Triage rule definitions (v2.7.0)
├── rulebook.md                # Human-readable rulebook documentation
├── fatigue_config.yaml        # Fatigue engine weights + parameters
├── Dockerfile
└── docker-compose.yml
```

---

## Roadmap

### ✅ Milestone 1: Pipeline + Rulebook + API (COMPLETE)

**Budget:** $4,900 | **KPIs achieved:**
- ✅ Reproducible Docker setup
- ✅ 30 rule cases covered (target: >=20, **150%**)
- ✅ Quickstart: clone to first API call in ~5 minutes (target: <=10 min)

### ✅ Milestone 2: Fatigue Index + Docs + Release (COMPLETE)

**Budget:** $1,200 (docs) + $400 (infrastructure) | **KPIs achieved:**
- ✅ Reproducible DFI formula with documented weights and config
- ✅ Full documentation with Quickstart guide
- ✅ Integration examples: Python + TypeScript
- ✅ 3 video tutorials published on [YouTube](https://www.youtube.com/playlist?list=PLCETnIPtht9YHuvg6XsoGJuWsr_4ZTPZV)
- ✅ 55/55 tests passing
- ✅ [Live demo deployed](https://pa.wyszomirski.online/docs)
- ✅ [Tagged release v0.1.0](https://github.com/pawel-wyszomirski/participation-architecture/releases/tag/v0.1.0)

---

## Deterministic Triage Rules

The rulebook (`rulebook.yaml`) defines explicit, testable rules:

```yaml
rules:
  - id: TECH-001-STRICT
    category: TECHNICAL
    phase: 2
    label: PROTOCOL_UPGRADE
    type: strict
    keywords: [hard fork, sequencer upgrade, arbos, upgrade]
    min_score: 80

  - id: TRE-010
    category: TREASURY
    phase: 3
    label: TREASURY_TIER_1
    type: strict
    amount_threshold: 10000000
    min_score: 85
```

**Transparency:** Every score includes `reasons` (rule IDs that fired). No black boxes.

See [rulebook.md](rulebook.md) for documentation of all 21 rules.

---

## Alignment with Arbitrum SOS

- **KR 7.3:** Research on how to increase participation in DAO voting
- **KR 7.4:** Increase average voting participation
- **Objective 6:** DAO operates with efficiency
- **Objective 3:** Home of builders and innovation

---

## Contributing

Contributions welcome. This is open-source middleware.

```bash
git clone https://github.com/pawel-wyszomirski/participation-architecture.git
cd participation-architecture
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app/services/snapshot_client.py
python3 -m uvicorn app.main:app --reload
python3 -m pytest tests/ -v
```

See [Video Tutorial 3](https://youtu.be/hZhBm-ik-vk) for a guide to adding new rules.

---

## License

**MIT License** - Free to use, modify, and distribute.

**Public Good Commitment:** This tool will remain open-source forever. No token, no paywall, no data monetization.

---

## Grant Information

**Supported by the Arbitrum Grants Program (Saving Our Season).**

- **Grant Amount:** $6,500 USD
- **Duration:** 10 weeks (2 milestones)
- **Full Proposal:** [View on Questbook](https://questbook.app/dashboard/?grantId=67d802bd46da2f90cc3267b0&chainId=10&role=builder&proposalId=69552f08fb7e884efa09de1e&isRenderingProposalBody=true)

---

## About the Author

**Pawel Wyszomirski** - PhD Candidate & Solo Developer

- **Background:** 10+ years civic tech (participatory budgeting), IoT startup founder (OpenAir)
- **Research Focus:** DAO governance as sociotechnical systems
- **Mission:** Reduce participation friction through explicit institutional rules

---

## Contact

- **Twitter/X:** [@pwyszomirski](https://x.com/pwyszomirski)
- **LinkedIn:** [Pawel Wyszomirski](https://www.linkedin.com/in/wyszomirski/)
- **Discord:** @pawelwyszomirski
- **Website:** [wyszomirski.online](https://wyszomirski.online/)

---

## Recent Updates

**v0.1.0 (March 2026) - Production Release**
- ✅ **Live Demo:** [pa.wyszomirski.online](https://pa.wyszomirski.online/docs)
- ✅ **Tagged release:** [v0.1.0](https://github.com/pawel-wyszomirski/participation-architecture/releases/tag/v0.1.0)
- ✅ **Production deployment** with SSL, Docker, nginx

**v0.7.0 (February 2026) - Milestone 2 Complete**
- ✅ **Delegate Fatigue Index:** 5-component deterministic formula, fully documented
- ✅ **FatigueSnapshot persistence:** Audit trail stored to SQLite
- ✅ **Full documentation:** Quickstart, API Reference, DFI deep dive
- ✅ **Integration examples:** Python + TypeScript
- ✅ **Video tutorials:** [3 tutorials on YouTube](https://www.youtube.com/playlist?list=PLCETnIPtht9YHuvg6XsoGJuWsr_4ZTPZV)
- ✅ **Runnable demo scripts:** `scripts/governance_alerts.py` + tutorial snippets
- ✅ **Test suite:** 55/55 passing (25 fatigue + 30 rule engine)

**v0.6.0 (February 2026) - Milestone 1 Complete**
- ✅ Rule engine with 21 deterministic rules
- ✅ Rulebook v2.7.0 (ex ante validated on 399 historical proposals)
- ✅ API endpoints: `/proposals/feed`, `/proposals/{id}`, `/health`
- ✅ 30 test cases, 100% rule coverage
- ✅ Docker setup

---

<div align="center">

**Made for sustainable DAO governance**

*Developer tooling to reduce participation friction*

**Research Project | Open Source Forever | Public Good**

---

[Report Bug](https://github.com/pawel-wyszomirski/participation-architecture/issues) · [Documentation](docs/quickstart.md) · [API Reference](docs/api-reference.md)

</div>
