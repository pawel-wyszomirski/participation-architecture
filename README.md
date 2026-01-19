<div align="center">

# Participation Architecture

### Governance Data Pipeline & Deterministic Triage Rules for DAOs

**A developer-first REST API to normalize governance data and apply transparent priority rules**

![Status](https://img.shields.io/badge/Status-Engineering%20Beta-yellow)
![Stack](https://img.shields.io/badge/Stack-FastAPI%20%7C%20Docker%20%7C%20PostgreSQL-blue)
![License](https://img.shields.io/badge/License-MIT-green)

[Quick Start](#-quick-start) • [API Endpoints](#-api-endpoints) • [Roadmap](#-roadmap) • [Budget](#-budget-allocation)

</div>

---

## 🎯 The Problem

**DAO Governance suffers from information overload and fragmented data sources.**

- **Symptom:** Declining participation - Arbitrum DAO saw onchain participation fall to 59.83% and offchain to 53.78% (April 2025)
- **Cause:** No standardized triage layer - builders repeatedly implement custom pipelines and priority logic
- **Result:** Delegates burn out from undifferentiated notification streams; tools can't interoperate

**The Solution:** A **reusable governance middleware** - a backend API that normalizes proposals and applies deterministic triage rules, so governance tools can prioritize what matters without building custom infrastructure.

---

## 🚀 Project Status

**Current Stage:** ✅ **Engineering Beta / Pre-Production**

### What's Working Now

- ✅ **Core Architecture:** FastAPI microservice + PostgreSQL/SQLite database
- ✅ **Data Ingestion:** Live GraphQL connection to Snapshot.org (Arbitrum DAO)
- ✅ **Database Schema:** 200+ proposals ingested and queryable
- ✅ **API Foundation:** Working endpoints with Swagger UI

### In Development (Grant Scope)

🟡 Deterministic rule engine + versioned rulebook  
🟡 Delegate Fatigue Index (transparent math, no ML)  
🟡 Production-grade error handling & logging  
🟡 Developer documentation + video tutorials  
🟡 Performance optimization (caching, indexing)

---

## 🏗 Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Client    │─────▶│  FastAPI     │─────▶│ PostgreSQL/ │
│   (Tool)    │◀─────│  + Rules     │◀─────│  SQLite     │
└─────────────┘      └──────────────┘      └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  Snapshot    │
                     │  GraphQL API │
                     └──────────────┘
```

**Stack:**
- **API Layer:** FastAPI (async, Pydantic validation, OpenAPI/Swagger)
- **Data Layer:** PostgreSQL/SQLite + SQLAlchemy ORM
- **Rule Engine:** YAML-based rulebook with versioning
- **Deployment:** Docker Compose

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Docker** (optional)

### 1. Install Dependencies

```bash
git clone https://github.com/pawel-wyszomirski/participation-architecture.git
cd participation-architecture
pip install -r requirements.txt
```

### 2. Ingest Data

```bash
python app/services/snapshot_client.py
```

### 3. Run API Server

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Explore API

- **Swagger UI:** `http://localhost:8000/docs`
- **Health Check:** `http://localhost:8000/health`

---

## 📡 API Endpoints

**Planned endpoints (Grant Deliverables):**

### Get Normalized Proposals Feed

```http
GET /proposals/feed
```

**Response:**
```json
{
  "proposals": [
    {
      "id": "proposal_123",
      "title": "Treasury Allocation Q1 2026",
      "priority_score": 85,
      "labels": ["treasury", "high_value"],
      "reasons": ["rule_treasury_large", "rule_strategic"],
      "recommended_handling": "deep_review"
    }
  ]
}
```

### Get Proposal Details

```http
GET /proposals/{id}
```

**Response includes full rule audit trail.**

### Get Delegate Fatigue Index

```http
GET /delegates/{address}/fatigue
```

**Response:**
```json
{
  "address": "0x1c6e...",
  "fatigue_index": 73,
  "components": {
    "volume_7d": 12,
    "volume_30d": 45,
    "concurrency": 3,
    "burstiness_score": 0.82,
    "reading_time_proxy": 180
  }
}
```

---

## 🛣 Roadmap

### Milestone 1: Pipeline Hardening + Rulebook v1 + API v1

**Budget:** $3,500 | **Timeline:** Weeks 1-5

**Deliverables:**

- Ingestion + normalization into documented schema
- Deterministic rule engine implementation
- **Rulebook v1** (`rulebook.yaml` + `rulebook.md`) with versioning
- API endpoints: `/proposals/feed`, `/proposals/{id}`, `/health`
- OpenAPI/Swagger + Quickstart draft

**KPIs:**
- Reproducible Docker setup (`docker compose up`)
- ≥20 rule cases covered by automated tests
- Quickstart: clone → first API call in ≤10 minutes

---

### Milestone 2: Fatigue Index + Docs/Tutorials + Public Release

**Budget:** $3,000 | **Timeline:** Weeks 6-10

**Deliverables:**

- Delegate Fatigue Index: `GET /delegates/{address}/fatigue`
- Performance improvements (indexing/caching)
- Full documentation (OpenAPI + guides + examples)
- **2-3 video tutorials:**
  1. Quickstart (run locally + first API call)
  2. Integrate into a bot/notification workflow
  3. Customize the rulebook (add/edit rules + run tests)
- Tagged release (v0.1) + maintenance notes

**KPIs:**
- Fatigue index reproducible (documented formula)
- ≥70% of test users complete Quickstart in ≤30 minutes
- p95 response time <400ms for cached queries
- Open-source and runnable by third parties

---

## 💰 Budget Allocation

**Total Request:** $6,500 USD

| Category | Amount | Details |
|----------|--------|---------|
| **Engineering** | $4,900 | ~70 hrs @ $70/hr (pipeline + rules + fatigue) |
| **Documentation** | $1,200 | ~20 hrs @ $60/hr (docs + tutorials) |
| **Infrastructure** | $400 | Hosting + monitoring + DB (grant period) |

**No ML inference costs** - deterministic rules only.

---

## 📊 Deterministic Triage Rules

### Rule Engine Concept

The rulebook (`rulebook.yaml`) defines explicit, testable rules:

```yaml
rules:
  - id: rule_treasury_large
    category: treasury
    condition: amount > 100000
    priority_boost: +30
    label: high_value
    recommended_handling: deep_review
  
  - id: rule_routine_ops
    category: operations
    condition: routine_approval == true
    priority_boost: -20
    label: routine_ops
    recommended_handling: fast_track
```

**Transparency:** Every score includes `reasons` (rule IDs that fired).

---

## 📊 Delegate Fatigue Index

### Transparent Formula (No Black Boxes)

**Components:**
- **Volume** (40%): proposals per 7d/30d windows
- **Concurrency** (25%): simultaneous active votes
- **Burstiness** (20%): cadence spike detection
- **Reading Time Proxy** (10%): word count / baseline speed
- **Novelty Proxy** (5%): new domain tags vs routine categories

**Output:** Fatigue Index (0-100)
- **0-30:** Healthy engagement
- **31-60:** Warning signs
- **61-100:** Burnout risk

---

## 🎯 Target Audience

**Primary:**
- Developers building governance tools (dashboards, bots, analytics)
- Need normalized data + triage outputs without custom pipelines

**Secondary:**
- Delegates and governance operators
- Want machine-readable "what matters now" signals

---

## 🤝 Alignment with Arbitrum SOS

This project directly supports:

- **KR 7.3:** Research on how to increase participation in DAO voting
- **KR 7.4:** Increase average voting participation
- **Objective 6:** DAO operates with efficiency
- **Objective 3:** Home of builders and innovation

**Evidence:** April 2025 governance analytics show declining participation and below-average engagement across proposals.

---

## 📂 Project Structure

```
├── app/
│   ├── core/              # Configuration
│   ├── db/                # Database models
│   ├── schemas/           # Pydantic models
│   ├── services/
│   │   ├── snapshot_client.py    # Data ingestion
│   │   ├── rule_engine.py        # Triage rules (planned)
│   │   └── fatigue_calculator.py # Fatigue index (planned)
│   ├── api/v1/            # Route handlers
│   └── main.py
├── rulebook.yaml          # Rule definitions (planned)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## 🤝 Contributing

Contributions welcome! This is open-source middleware.

**Development Setup:**
```bash
git clone https://github.com/YOUR_USERNAME/participation-architecture.git
cd participation-architecture
pip install -r requirements.txt
python app/services/snapshot_client.py
python -m uvicorn app.main:app --reload
```

---

## 📄 License

**MIT License** - Free to use, modify, and distribute.

**Public Good Commitment:** This tool will remain open-source forever. No token, no paywall, no data monetization.

---

## 💤 About the Author

**Paweł Wyszomirski** - PhD Candidate & Solo Developer

- **Background:** 10+ years civic tech (participatory budgeting), IoT startup founder (OpenAir)
- **Research Focus:** DAO governance as sociotechnical systems
- **Mission:** Reduce participation friction through explicit institutional rules

---

## 📬 Contact

- **Twitter/X:** [@pwyszomirski](https://x.com/pwyszomirski)
- **LinkedIn:** [Paweł Wyszomirski](https://www.linkedin.com/in/wyszomirski/)
- **Discord:** @pawelwyszomirski
- **Website:** [wyszomirski.online](https://wyszomirski.online/)

### Project Links

- **Repository:** https://github.com/pawel-wyszomirski/participation-architecture
- **Issues:** [Report bugs or request features](https://github.com/pawel-wyszomirski/participation-architecture/issues)

---

## 📚 Additional Resources

- [Technical Architecture](architecture.md) - System design & API specs
- [API Reference](http://localhost:8000/docs) - Interactive Swagger docs
- [Ostrom's Governing the Commons](https://wtf.tw/ref/ostrom_1990.pdf)

### Research Context

This project is a component of a PhD dissertation on participation architecture in DAOs, combining:
- Quantitative analysis (behavioral metrics)
- Qualitative validation (delegate interviews)
- Theoretical frameworks (Ostrom's principles + Self-Determination Theory)

---

## 📈 Recent Updates

**v0.6.0 (January 2026) - Grant Resubmission**
- Simplified scope: API-only (no dashboard)
- Focus on deterministic rules (no AI/ML)
- 2 milestones, 10 weeks, $6,500 budget
- Clear KPIs and developer-first deliverables

**v0.5.2 (January 2025)**
- Live Snapshot GraphQL integration
- 200+ Arbitrum DAO proposals ingested
- Working API endpoints with Swagger UI

---

<div align="center">

**Made with 🧠 + ❤️ for sustainable DAO governance**

*Developer tooling to reduce participation friction*

**Research Project | Open Source Forever | Public Good**

---

[Report Bug](https://github.com/pawel-wyszomirski/participation-architecture/issues) · [Request Feature](https://github.com/pawel-wyszomirski/participation-architecture/issues) · [Documentation](architecture.md)

**⭐ Star this repo if you support developer-first governance tools!**

</div>
