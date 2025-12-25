<div align="center">

# Participation Architecture

### Signal-to-Noise Governance Infrastructure for DAOs

**A developer-first REST API to measure delegate fatigue and filter governance noise**

![Status](https://img.shields.io/badge/Status-MVP%20Scaffold-yellow)
![Stack](https://img.shields.io/badge/Stack-FastAPI%20%7C%20Docker%20%7C%20PostgreSQL-blue)
![License](https://img.shields.io/badge/License-MIT-green)
[![Grant: Arbitrum](https://img.shields.io/badge/Grant-Application%20Submitted-yellow)](https://arbitrum.questbook.app/)

[Quick Start](#-quick-start) • [API Reference](#-api-usage-mvp) • [Roadmap](#-roadmap-grant-scope) • [Budget](#-budget-allocation)

</div>

---

## 🎯 The Problem: Delegate Fatigue

**DAO Governance suffers from a "Crisis of Attention".**

- **Symptom:** "Burst-then-Silence" voting patterns. 52% of active delegates show burnout after 3-6 months.
- **Cause:** High "Governance Noise" - current tools (Tally/Karma) treat admin votes equal to strategic decisions.
- **Result:** Key contributors (like L2BEAT) disengage to protect cognitive resources.

**The Solution:** **Fatigue-as-a-Service**. A containerized REST API that allows governance tooling (dashboards, wallets) to surface burnout risk metrics in real-time.

---

## 🏗 Architecture (v5.1)

**Evolution:** From research scripts (v3.1) → Production microservice (v5.1)

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Client    │─────▶│  FastAPI     │─────▶│ PostgreSQL  │
│ (Dashboard) │◀─────│  Container   │◀─────│  Container  │
└─────────────┘      └──────────────┘      └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  Snapshot    │
                     │  GraphQL API │
                     └──────────────┘
```

**Stack:**

- **API Layer:** FastAPI (Async, Pydantic validation, auto-generated OpenAPI docs)
- **Data Layer:** PostgreSQL 15 + SQLAlchemy ORM (Alembic migrations)
- **Task Management:** BackgroundTasks for idempotent data ingestion
- **Deployment:** Docker Compose orchestration (reproducible builds)

---

## 🚀 Quick Start

**Prerequisites:** Docker & Docker Compose installed.

```bash
# 1. Clone repository
git clone https://github.com/pawel-wyszomirski/participation-architecture.git
cd participation-architecture

# 2. Build and run containers
docker compose up --build
```

**Verification:**

- **Swagger UI (Interactive Docs):** `http://localhost:8000/docs`
- **Health Check:** `curl http://localhost:8000/health`
- **Expected Output:** ✅ `{"status": "healthy", "database": "connected"}`

---

## 📡 API Usage (MVP)

**Current Status:** Mock endpoint available to validate API contract. Real data ingestion coming in Milestone 1.2-1.3.

### Get Delegate Fatigue Score

**Request:**
```http
GET /v1/delegates/{address}/fatigue
```

**Response Spec (JSON Schema):**
```json
{
  "address": "0x1c6e...",
  "fatigue_score": 73.5,
  "status": "CRITICAL",
  "breakdown": {
    "volume_impact": 0.8,
    "time_scarcity": 0.7,
    "dropout_risk": 0.3
  },
  "metrics": {
    "votes_last_30d": 42,
    "avg_time_gap_hours": 18.5,
    "participation_rate": 0.85
  }
}
```

**Interactive Testing:** Visit `http://localhost:8000/docs` for Swagger UI with live request/response examples.

---

## 🛣 Roadmap (Grant Scope)

### 🏗️ Milestone 1: Core Infrastructure & Ingestion

**Budget:** $10,000 | **Timeline:** Weeks 1-6 (January 2025) | **Status:** 🟡 In Progress

**Deliverables:**

- **1.1 Containerized API**
  - [x] Docker Compose multi-container setup
  - [x] `/health` and `/v1/delegates/{address}/fatigue` endpoints (mock)
  - [ ] Production-ready error handling and logging

- **1.2 Database Schema (Alembic Migrations)**
  - [x] SQLAlchemy models: `Delegates`, `Proposals`, `Votes`
  - [ ] Alembic migration scripts versioned and tested
  - [ ] Indexing strategy for query performance optimization

- **1.3 Snapshot Ingestor (Background Service)**
  - [x] GraphQL client with rate limit handling
  - [ ] **Idempotency logic** (no duplicate entries on re-runs)
  - [ ] **Target:** Ingest **1000+ historical proposals** from Arbitrum DAO
  - [ ] Retry mechanism with exponential backoff

- **1.4 OpenAPI Documentation**
  - [x] Auto-generated Swagger UI at `/docs`
  - [ ] Complete endpoint descriptions with examples
  - [ ] Response schema validation and error codes

- **1.5 Security & Rate Limiting**
  - [ ] API Key authentication system
  - [ ] Per-key rate limiting (100 req/hour default tier)
  - [ ] Request logging and usage analytics

**Acceptance Criteria:**
- ✅ `docker compose up` starts system without errors
- ⏳ Database contains **minimum 1000 historical records**
- ⏳ CI/CD pipeline (GitHub Actions) passes all tests (**Green Build**)
- ⏳ Unit test coverage >80%

---

### 🧠 Milestone 2: Intelligence Engine & Dashboard

**Budget:** $10,000 | **Timeline:** Weeks 7-12 (February 2025)

**Deliverables:**

- **2.1 Intelligence Modules**
  - [ ] **FatigueCalculator:** Time-series analysis with weighted scoring
    - Volume impact (votes/proposal ratio)
    - Time scarcity (response time patterns)
    - Dropout risk (silence period detection)
  - [ ] **SignalClassifier:** OpenAI GPT-4 integration for proposal categorization
    - Strategic (Signal): Protocol upgrades, treasury decisions
    - Operational (Noise): Routine approvals, admin updates
  - [ ] Response caching layer (Redis/in-memory) for **<200ms latency**
  - [ ] Batch processing for historical data analysis

- **2.2 Dashboard MVP**
  - [ ] Technology: Streamlit (MVP) or React + TailwindCSS (production)
  - [ ] Features:
    - Real-time fatigue score visualization
    - Delegate search and filtering
    - Historical trend charts
    - Proposal signal/noise breakdown
  - [ ] Responsive design (mobile-friendly)

- **2.3 NLP Validation Report**
  - [ ] Manually tag **100 proposals** (Signal vs Noise ground truth)
  - [ ] Calculate **Precision & Recall** metrics
  - [ ] **Target:** >85% classification accuracy
  - [ ] Document edge cases and model limitations

**Acceptance Criteria:**
- ✅ Signal/Noise classification **Precision & Recall >85%**
- ✅ API response time for cached queries **<200ms**
- ✅ Dashboard loads successfully and displays live data
- ✅ Beta testing with **5-10 Arbitrum delegates** (feedback collected)

---

### 🚀 Milestone 3: Production Release & Adoption

**Budget:** $5,000 | **Timeline:** Weeks 13-16 (March 2025)

**Deliverables:**

- **3.1 Production Deployment**
  - [ ] Public URL with SSL certificate (Let's Encrypt)
  - [ ] Custom domain: `api.participation-architecture.com`
  - [ ] Infrastructure: Cloud hosting (Render/Railway/DigitalOcean)
  - [ ] Monitoring: UptimeRobot + error tracking (Sentry)
  - [ ] **Target:** **99.9% uptime** guarantee

- **3.2 Partner Integration ("Proof of Warmth")**
  - [ ] API integration with **L2BEAT** or **Entropy Advisors**
  - [ ] Embeddable widget for governance dashboards
  - [ ] Webhook support for real-time fatigue alerts
  - [ ] **Target:** Minimum **3 active delegate users** or integrations

- **3.3 Final Documentation Package**
  - [ ] Technical report: *"Measuring Delegate Fatigue in Arbitrum DAO"*
  - [ ] Video tutorial series (5-10 min each):
    - Setup & deployment guide
    - API integration examples
    - Dashboard walkthrough
  - [ ] Case study: **"How Signal Filtering Reduced Analysis Time by X%"**
  - [ ] Open-source handover plan (community maintainers identified)

**Acceptance Criteria:**
- ✅ Production API uptime **>99.9%** (monitored continuously)
- ✅ **Minimum 3 delegates/tools** actively using the API
- ✅ Case study with **quantified impact** (time saved, proposals filtered)
- ✅ All code documented and ready for community maintenance

---

## 💰 Budget Allocation

**Total Request:** $25,000 (Arbitrum Developer Tooling Grant)

| Category | Allocation | Justification |
|----------|------------|---------------|
| **Development** | $20,000 | 400 hours engineering (Fullstack + Data Engineering) @ $50/hour |
| **OpenAI & Cache** | $3,000 | LLM inference costs (GPT-4o-mini) + scaling buffer for classification |
| **Infrastructure** | $1,000 | Hosting (Railway/Render), database, monitoring (12 months) |
| **Community** | $1,000 | Beta-tester incentives, educational content creation |

**Cost Efficiency:** Solo researcher model ensures no overhead costs. All funds directly contribute to shipping code.

---

## 🤝 Validation Strategy (Proof of Warmth)

**We don't guess. We validate with market leaders.**

### Beta Partnership Targets:

- **L2BEAT** - Leading Arbitrum governance participant with documented fatigue concerns
- **Entropy Advisors** - Governance research firm with established tooling needs

### Success Metrics:

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Utility** | >30% time reduction | Time to filter "Signal" from "Noise" in governance workflow |
| **Retention** | Weekly active usage | API call frequency from pilot delegates |
| **Accuracy** | >85% precision | Manual validation of Signal/Noise classification |

**Feedback Loop:** Weekly check-ins with beta users during Milestone 2, with rapid iteration based on real-world usage patterns.

---

## 📂 Project Structure

```
├── app/                    # FastAPI Application
│   ├── core/              # Configuration & Settings
│   ├── db/                # Database Models (SQLAlchemy)
│   │   ├── models.py      # Delegates, Votes, Proposals
│   │   └── session.py     # Connection Management
│   ├── schemas/           # Pydantic Request/Response Models
│   ├── api/               # Route Handlers
│   │   └── v1/            # API Version 1
│   └── main.py            # Application Entry Point
├── legacy/                # Research Scripts (v3.1 artifacts)
│   ├── collector.py       # Original Snapshot Scraper
│   ├── analysis.py        # Fatigue Algorithm Prototypes
│   └── fetch_votes.py     # CLI Demo Scripts
├── data/                  # Historical Datasets
│   └── wyniki_arbitrum.csv # 7,385 delegates analyzed
├── Dockerfile             # Container Image Definition
├── docker-compose.yml     # Multi-Container Orchestration
├── requirements.txt       # Python Dependencies
├── architecture.md        # Technical Deep Dive
└── README.md             # This file
```

**Migration Notes:**
- `legacy/` contains original research scripts (preserved for reproducibility)
- `app/` is the new production-ready microservice architecture
- All analysis logic will migrate to database-backed operations

---

## 🧠 Theoretical Foundation

### Self-Determination Theory (SDT)

This project applies SDT to governance participation:

- **Autonomy** - Delegates choose when/how to engage
- **Competence** - Understanding proposals requires cognitive effort
- **Relatedness** - Community connection influences sustained participation

**Fatigue Hypothesis:** When these needs aren't met, delegates experience burnout, visible through:

1. **Extended voting gaps** (loss of autonomy/competence)
2. **Burst-then-silence patterns** (competence overwhelm)
3. **Declining trend** (weakening relatedness)

### Elinor Ostrom's Common-Pool Resource Framework

DAOs are digital commons requiring active stewardship. This tool implements Ostrom's monitoring principle: identifying when "resource monitors" (delegates) are overextended, before the commons collapses.

**Key Insight:** Governance participation isn't a linear metric - it's a commons management problem requiring behavioral economics.

---

## 📊 Metrics Explained

### Fatigue Score (0-100)

**Algorithm Components:**

| Component | Weight | Description |
|-----------|--------|-------------|
| **Volume Impact** | 30% | Votes cast vs. total proposals (overload detection) |
| **Time Scarcity** | 50% | Response time patterns (rushed decisions indicator) |
| **Dropout Risk** | 20% | Extended silence periods (>30 days without activity) |

**Risk Levels:**

- **0-30 (LOW / Healthy):** Sustainable engagement patterns
- **31-60 (MODERATE / Warning):** Early fatigue signals detected
- **61-100 (HIGH / Critical):** Immediate burnout risk

### Participation Rate

**Formula:** `votes_cast / total_proposals_in_window`

Calculated over rolling 30/90 day windows. Future versions will distinguish:
- **All Proposals** - Raw participation baseline
- **Signal Proposals Only** - Strategic engagement quality

### Signal-to-Noise Ratio (Milestone 2)

**Classification Logic:**
- **Signal (Strategic):** Protocol upgrades, treasury allocations, constitutional amendments
- **Noise (Operational):** Routine approvals, admin updates, procedural votes

**Target:** Reduce cognitive load by **30%** through intelligent proposal filtering.

---

## 🎯 Target Audience

### Primary Users

**Active Arbitrum Delegates (Top 50 by Voting Power)**
- Struggling with information overload
- Need tools to prioritize high-impact proposals
- Want to maintain engagement without burnout

### Secondary Users

**Governance Platform Developers**
- Building on Tally, Karma, or custom dashboards
- Need fatigue metrics API for their UIs
- Want behavioral analytics to complement voting data

**DAO Operations Teams**
- Monitoring delegate health across the ecosystem
- Identifying at-risk contributors early
- Optimizing proposal schedules to reduce noise

### Research Community

**Academics studying DAO governance**
- Analyzing participation patterns with rigorous methodology
- Testing theories about digital commons management
- Validating Self-Determination Theory in web3 contexts

---

## 🤝 Contributing

This is a research project in active development. Contributions welcome!

### Ways to Contribute

- 🔬 Validate fatigue algorithm against real delegate experiences
- 🐛 Report bugs or edge cases in data processing
- 📖 Improve documentation and examples
- 🎨 Design better dashboard UIs (Milestone 2)
- 📊 Propose new metrics based on governance research

### Development Setup

```bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/participation-architecture.git
cd participation-architecture

# Start development environment
docker compose up --build

# Run tests (when implemented)
pytest tests/

# Format code
black app/ && isort app/
```

For detailed guidelines, see `CONTRIBUTING.md` (coming in Milestone 1).

---

## 📄 License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

**What This Means:**

✅ Free to use, modify, and distribute  
✅ Commercial use allowed  
✅ No warranty provided  
✅ Attribution required  

**Public Good Commitment:** This tool will remain open-source forever. No token, no paywall, no data monetization.

---

## 💤 About the Author

### Paweł Wyszomirski

**PhD Candidate & Solo Researcher**

**Focus:** DAO Coordination, Public Goods, Behavioral Economics  
**Mission:** Turning academic theory into shipping code

#### Why I Built This

Having spent 10+ years in civic participation (participatory budgeting in Katowice with 70K+ annual participants), I've seen how **burnout destroys communities**. DAOs face the same challenge at scale.

After building OpenAir (IoT air quality startup, 300+ devices sold), I learned that **data without behavioral prompts = ignored alerts**. This tool combines:
- 🏛️ 10+ years civic tech experience
- 🤖 AI & behavioral coaching (Architekt Nawyków AI, 600+ clients)
- 🔬 Academic research (PhD dissertation component)

**The insight:** Governance isn't just about voting numbers - it's about sustainable human engagement. This tool measures what matters.

---

## 📬 Contact

### Connect

- **Twitter/X:** [@pwyszomirski](https://x.com/pwyszomirski)
- **LinkedIn:** [Paweł Wyszomirski](https://www.linkedin.com/in/wyszomirski/)
- **Discord:** @pawelwyszomirski
- **Website:** [wyszomirski.online](https://wyszomirski.online/)
- **Google Scholar:** [Research Publications](https://scholar.google.com/citations?user=AryRIgYAAAAJ&hl=pl)

### Project Links

- **Repository:** https://github.com/pawel-wyszomirski/participation-architecture
- **Issues:** [Report bugs or request features](https://github.com/pawel-wyszomirski/participation-architecture/issues)
- **Grant Proposal:** [Arbitrum Questbook Application](https://arbitrum.questbook.app/dashboard/?proposalId=69418dd196f32ac6ce53121f&grantId=67d802bd46da2f90cc3267b0&chainId=10)

### For DAOs & Researchers

Interested in applying this methodology to your DAO? Open to collaboration on:
- Custom fatigue analysis for specific governance structures
- Academic partnerships for validation studies
- Integration with governance platforms (API-first approach)

---

## 📚 Additional Resources

### Documentation

- [Technical Architecture](architecture.md) - System design & API specifications
- [Methodology](docs/methodology.md) - Fatigue Index calculation details (to be added)
- [API Reference](http://localhost:8000/docs) - Interactive Swagger documentation
- [SDT Framework Research](https://selfdeterminationtheory.org/)
- [Ostrom's Governing the Commons](https://wtf.tw/ref/ostrom_1990.pdf)

### Research Context

This project is a **mandatory component** of a PhD dissertation researching participation architecture in DAOs, combining:
- **Quantitative analysis** (behavioral metrics via time-series data)
- **Qualitative validation** (delegate interviews and case studies)
- **Theoretical frameworks** (Self-Determination Theory + Ostrom's principles)

All findings will be:
- Published openly (CC-BY license)
- Validated through mixed-methods research
- Shared with studied communities before publication

---

## 🙏 Acknowledgments

- **Arbitrum DAO** - Grant application support and primary data source
- **Arbitrum Delegates** - Real-world feedback and beta testing willingness
- **Snapshot Labs** - Public GraphQL API enabling this research
- **OpenAI & Anthropic** - AI assistance in development workflow
- **OpenAir & Architekt Nawyków AI Communities** - Behavioral science validation

---

## 📈 Project Status

**Current Version:** 0.5.1-MVP  
**Last Updated:** December 2025  
**Active Development:** Yes 🟡 (Grant application pending)  
**PhD Research Component:** In Progress (2023-2026)

### Current Capabilities

✅ FastAPI REST API with auto-generated Swagger docs  
✅ Docker containerization (reproducible deployment)  
✅ PostgreSQL database with relational schema  
✅ Mock endpoints to validate API contract  
✅ Snapshot GraphQL integration (prototype in `legacy/`)  
✅ Fatigue algorithm (research validated, migration in progress)  

### In Development (Current Milestone 1)

🟡 Alembic database migrations  
🟡 Idempotent Snapshot ingestor (1000+ proposals)  
🟡 API Key authentication & rate limiting  
🟡 CI/CD pipeline (GitHub Actions)  
🟡 Unit test coverage >80%  

### Planned (Milestones 2-3)

⏳ NLP Signal/Noise classifier (OpenAI integration)  
⏳ Web dashboard (Streamlit MVP → React production)  
⏳ Production deployment (public URL, SSL, 99.9% uptime)  
⏳ Partner integrations (L2BEAT/Entropy)  

### Known Limitations

- Mock data only (real ingestion coming in M1.3)
- Snapshot/Tally only (on-chain voting planned for post-grant)
- English-language proposals only
- Limited to Ethereum-based DAOs (Arbitrum One focus)
- No authentication layer yet (coming in M1.5)

---

<div align="center">

**Made with 🧠 + ❤️ for healthier DAOs**

*Combining social science with code to make governance sustainable*

**Research Project | Open Source Forever | Public Good**

---

[Report Bug](https://github.com/pawel-wyszomirski/participation-architecture/issues) · [Request Feature](https://github.com/pawel-wyszomirski/participation-architecture/issues) · [Documentation](architecture.md) · [Grant Proposal](https://arbitrum.questbook.app/dashboard/?proposalId=69418dd196f32ac6ce53121f&grantId=67d802bd46da2f90cc3267b0&chainId=10)

**⭐ Star this repo if you believe in sustainable DAO governance!**

</div>
