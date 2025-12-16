<div align="center">

# Participation Architecture

### Signal-to-Noise Governance Infrastructure for DAOs

**A "Spam Filter for Governance" that separates Signal from Noise**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Grant: Arbitrum](https://img.shields.io/badge/Grant-Application%20Submitted-yellow)](https://arbitrum.questbook.app/)

[Quick Start](#-quick-start) • [Methodology](#-theoretical-foundation) • [Roadmap](#️-roadmap) • [Contact](#-contact)

</div>

---

## 📊 Active Development Status

> **Research Artifact:** Mandatory component of a PhD dissertation on DAO Governance  
> **Grant Status:** Application Submitted (Arbitrum Developer Tooling)  
> **Current Phase:** Milestone 1 - Backend Infrastructure & Data Pipeline  
> **Status:** 🟡 MVP Development in Progress

---

## 🎯 The Problem: Delegate Fatigue

**DAO Governance is suffering from a "Crisis of Attention".**

**The Symptom:** "Burst-then-Silence" voting patterns. 52% of active delegates show signs of burnout after 3-6 months.

**The Cause:** High "Governance Noise". Current tools (Tally/Karma) optimize for the *quantity* of votes, treating administrative maintenance equal to strategic decisions.

**The Result:** Key contributors (like L2BEAT) disengage to protect their cognitive resources.

---

## 🛠 The Solution: Signal-to-Noise Engine

**Participation Architecture** is a Python-based analytics suite that implements Elinor Ostrom's commons principles and Self-Determination Theory (SDT) to filter governance proposals.

Instead of asking *"Did they vote?"*, we ask *"Did they waste their time?"*.

### What Makes This Different

| Tool | Approach |
|------|----------|
| **Karma/Tally** | Display raw data volume (vanity metrics) |
| **Participation Architecture** | Filters cognitive load and creates actionable habits |

Drawing from experience building OpenAir (IoT air quality monitors), we learned that **data without prompts doesn't drive action**. This tool operationalizes behavioral science into governance infrastructure.

---

## ✨ Core Features (Current MVP)

### 1. 🐍 Fatigue Engine (Backend) ✅ Operational

Python-based scraper integrating with Snapshot API

- **Quantifies Burnout:** Calculates "Fatigue Index" based on voting gaps and response time
- **Data Ingestion:** Automatically fetches and normalizes voting history for Arbitrum delegates
- **Anomaly Detection:** Identifies "Burst-then-Silence" patterns
- **Historical Analysis:** 7,385 delegates analyzed (see `data/wyniki_arbitrum.csv`)

### 2. 🎯 Signal Classifier (NLP Module) 🟡 In Development (Milestone 2)

Machine learning pipeline to categorize proposals by importance

- **Strategic (Signal):** Protocol upgrades, treasury decisions, major policy changes
- **Operational (Noise):** Routine approvals, administrative updates, procedural votes
- **Goal:** Filter ~30% of governance noise to reclaim delegate attention
- **Status:** Planned for Month 2 of grant timeline

### 3. 📊 Metrics & Algorithms ✅ Operational

Based on Self-Determination Theory (SDT)

- **Participation Rate** - Rolling 30/90 day activity windows
- **Burnout Detection** - Identifies rapid voting → silence patterns
- **Trend Analysis** - Declining vs. stable engagement over time
- **Cognitive Load Score** - Measures information overload impact

---

## 🚀 Quick Start (Demo)

### Prerequisites

- Python 3.9 or higher
- Internet connection (for Snapshot GraphQL API)

### Installation

```bash
# Clone the repository
git clone https://github.com/pawel-wyszomirski/participation-architecture.git
cd participation-architecture

# Install dependencies
pip install -r requirements.txt
```

### Run the Demo Script

We have prepared a simple script to fetch live voting data for a target delegate (e.g., L2BEAT):

```bash
python fetch_votes.py
```

**Expected Output:**

```
--- Participation Architecture: Fatigue Engine (MVP Demo) ---
Target Space: arbitrumfoundation.eth
📡 Connecting to Snapshot API for: 0x1c6e...
✅ Successfully fetched 10 recent votes.
📊 Calculating Fatigue Index...
⚠️  Burnout Pattern Detected: 45-day gap after burst activity
```

### Advanced Usage

```bash
# Collect data from Snapshot
python src/main.py collect --space arbitrum --proposals 50

# Run the fatigue analysis
python src/main.py analyze

# Generate a report
python src/main.py report --output data/report.md
```

---

## 📂 Project Structure
```
├── data/                   # Raw and processed datasets
│   ├── arbitrum_results.json
│   ├── wyniki_arbitrum.csv # Historical analysis of 7,385 delegates
│   └── raport_arbitrum.md  # Generated report
├── src/                    # Core Business Logic
│   ├── collector.py        # Data Ingestion
│   ├── analysis.py         # Fatigue Index Implementation
│   ├── targeting.py        # Delegate Segmentation
│   └── main.py             # Orchestrator
├── fetch_votes.py          # MVP Demo Script
├── architecture.md         # Technical Documentation
├── requirements.txt        # Dependencies
└── README.md               # This file
└── LICENSE                 # MIT License
```

**Note:** Additional components (web dashboard, NLP classifier, REST API) are planned for Milestones 2-3.

---

## 🧠 Theoretical Foundation

### Self-Determination Theory (SDT)

This project applies SDT to governance participation:

- **Autonomy** - Delegates choose when/how to engage
- **Competence** - Understanding proposals requires cognitive effort
- **Relatedness** - Community connection influences sustained participation

**Fatigue Hypothesis:** When these needs aren't met, delegates experience burnout, visible through:

1. Extended voting gaps (loss of autonomy/competence)
2. Burst-then-silence patterns (competence overwhelm)
3. Declining trend (weakening relatedness)

### Elinor Ostrom's Common-Pool Resource Framework

DAOs are digital commons requiring active stewardship. Ostrom's principles for sustainable commons management:

- **Clear boundaries** - Who are the decision-makers? (Delegates)
- **Monitoring** - Are stewards overextended? (Fatigue Index)
- **Graduated sanctions** - How do we prevent burnout? (Signal filtering)

This tool helps identify when "resource monitors" (delegates) are overextended, before the commons collapses.

---

## 📊 Metrics Explained

### Participation Rate

**Formula:** `votes_cast / total_proposals_in_window`

Measures baseline activity over 30/90 day periods. Distinguishes between:
- **All Proposals** - Raw participation
- **Signal Proposals Only** - Strategic engagement quality (future feature)

### Fatigue Score (0-100)

**Components:**

| Component | Points | Description |
|-----------|--------|-------------|
| Long voting gaps | 0-30 | Extended periods without votes |
| Burnout pattern | 0-50 | Burst-then-silence behavior |
| Declining trend | 0-20 | Negative slope over 90 days |

**Interpretation:**

- **0-30:** Healthy engagement
- **31-60:** Moderate fatigue signals (early warning)
- **61-100:** High risk of disengagement (critical)

### Signal-to-Noise Ratio (Planned for Milestone 2)

**Formula:** `strategic_proposals / total_proposals`

**Classification Logic (NLP):**
- **Signal (Strategic):** Keywords like "protocol upgrade", "treasury allocation", "constitutional amendment"
- **Noise (Operational):** Keywords like "grant approval", "working group update", "procedural motion"

**Target:** Reduce noise exposure by 30%, allowing delegates to focus cognitive resources on high-impact decisions.

---

## 🛣️ Roadmap (Grant Timeline)

### Milestone 1 (Month 1): Data & Fatigue Engine

- [x] Repository initialized and public
- [x] Snapshot Scraper (MVP operational)
- [ ] Fatigue Algorithm Calibration
- [ ] "Health Check" Report for Top 100 Arbitrum Delegates
- [ ] Unit test coverage >80%

**Budget:** $10,000 | **Timeline:** January 2026

---

### Milestone 2 (Month 2): Signal-to-Noise Dashboard

- [ ] NLP Classifier (Signal vs Noise)
- [ ] Web Dashboard (React/Streamlit)
- [ ] REST API endpoints documented and accessible
- [ ] Beta Testing with 5-10 Arbitrum Delegates

**Budget:** $10,000 | **Timeline:** February 2026

---

### Milestone 3 (Month 3): Documentation & Handover

- [ ] Full GitHub documentation (README, API reference, methodology)
- [ ] Video tutorial demonstrating tool usage
- [ ] Final "Delegate Fatigue Index" research report for Arbitrum DAO
- [ ] Open-source handover (MIT License, community maintainers identified)

**Budget:** $5,000 | **Timeline:** March 2026

---

### Post-Grant: Sustainability & Growth

**Maintenance Plan:**
- Codebase supports doctoral research (guaranteed 2-3 years minimum)
- Community contributions via GitHub issues and PRs
- Potential for Arbitrum Pluralistic Grants or Retroactive Funding

**Future Enhancements (Beyond Grant Scope):**
- Multi-DAO support (Optimism, ENS, Uniswap)
- Predictive modeling (churn probability forecasting)
- Network analysis (delegate cluster identification)

---

## 🎯 Target Audience

### Primary Users

**Active Arbitrum Delegates (Top 50 by Voting Power)**
- Struggling with information overload
- Need tools to prioritize high-impact proposals
- Want to maintain engagement without burnout

### Secondary Users

**Governance Interface Developers**
- Building on top of Tally, Karma, or custom dashboards
- Need a "Signal/Noise" API endpoint to enrich their UIs (future)
- Want behavioral analytics to complement voting metrics

### Research Community

**Academics studying DAO governance**
- Analyzing participation patterns
- Testing theories about digital commons management
- Validating Self-Determination Theory in web3 contexts

---

## 🤝 Contributing

This is a research project in active development. Contributions welcome!

### Ways to Contribute

- 📝 Improve metric definitions based on governance research
- 🐛 Report bugs or edge cases in data processing
- 🔬 Validate findings against real delegate experiences
- 📚 Expand documentation and examples

### Development Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run the demo
python fetch_votes.py

# Run analysis (if you have local data)
python src/main.py analyze
```

For detailed guidelines, see the `architecture.md` file.

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

## 👤 About the Author

### Paweł Wyszomirski

**PhD Candidate & Solo Researcher**

**Focus:** DAO Coordination, Public Goods, Behavioral Economics  
**Goal:** Turning academic theory into shipping code

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
- **Grant Proposal:** [Arbitrum Questbook](https://arbitrum.questbook.app/dashboard/?proposalId=69418dd196f32ac6ce53121f&grantId=67d802bd46da2f90cc3267b0&chainId=10)

### For DAOs & Researchers

Interested in applying this methodology to your DAO? Open to collaboration on:
- Custom fatigue analysis for specific governance structures
- Academic partnerships for validation studies
- Integration with governance platforms (planned for Milestone 2)

---

## 📚 Additional Resources

### Documentation

- [Technical Architecture](architecture.md) - System design & data flow
- [Methodology](docs/methodology.md) - Fatigue Index calculation details
- [SDT Framework Research](https://selfdeterminationtheory.org/)
- [Ostrom's Governing the Commons](https://wtf.tw/ref/ostrom_1990.pdf)

### Research Context

This project is a core component of a PhD dissertation researching participation architecture in DAOs, combining:
- Quantitative analysis (behavioral metrics)
- Qualitative validation (delegate interviews)
- Theoretical frameworks (SDT, Ostrom)

All findings will be:
- Published openly (CC-BY license)
- Validated through mixed-methods research
- Shared with studied communities before publication

---

## 🙏 Acknowledgments

- **Arbitrum DAO** - Grant application support and primary data source
- **Arbitrum Delegates** - Real-world feedback (L2BEAT, others)
- **Snapshot Labs** - Public API access enabling this research
- **OpenAir & Architekt Nawyków AI Communities** - Behavioral science validation

---

## 📈 Project Status

**Current Version:** 0.1.0-MVP  
**Last Updated:** December 2025  
**Active Development:** Yes 🟡 (Grant application submitted)  
**PhD Research Component:** In Progress

### Current Capabilities

✅ Snapshot API integration  
✅ Fatigue Index calculation  
✅ Historical data analysis (7,385 delegates)  
✅ Burnout pattern detection  

### In Development (Pending Grant Approval)

🟡 NLP Signal/Noise classifier  
🟡 Web dashboard interface  
🟡 REST API endpoints  
🟡 Real-time monitoring  

### Known Limitations

- Snapshot/Tally only (on-chain voting analysis planned)
- English-language proposals only
- Limited to Ethereum-based DAOs (Arbitrum One focus)
- Requires validation with delegate interviews (Milestone 2)

---

<div align="center">

**Made with 🧠 + ❤️ for healthier DAOs**

*Combining social science with code to make governance sustainable*

**Research Project | Open Source Forever | Public Good**

---

[Report Bug](https://github.com/pawel-wyszomirski/participation-architecture/issues) · [Request Feature](https://github.com/pawel-wyszomirski/participation-architecture/issues) · [Documentation](architecture.md) · [Grant Proposal](https://arbitrum.questbook.app/dashboard/?proposalId=69418dd196f32ac6ce53121f&grantId=67d802bd46da2f90cc3267b0&chainId=10)

</div>
