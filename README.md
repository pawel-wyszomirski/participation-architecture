# Participation Architecture (MVP)

🔍 **Governance Health & Delegate Fatigue Analytics for Arbitrum DAO**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Status: Experimental](https://img.shields.io/badge/status-experimental-orange.svg)]()

---

## 📋 Overview

**Status:** Experimental / Research Preview  
**Grant Category:** Developer Tooling / Governance Analytics

### Project Goal

Current DAO governance tools track votes, but they don't track the **human cost of voting**. This tool parses Snapshot/on-chain data to diagnose **"Delegate Fatigue"** and visualize the health of the delegation market beyond simple participation rates.

### Why This Matters

- 🔥 **Burnout Detection** - Identify delegates showing signs of governance fatigue
- 📉 **Trend Analysis** - Track declining participation before it becomes critical
- 🏥 **System Health** - Measure DAO vitality through behavioral patterns
- 🎯 **Evidence-Based** - Grounded in Self-Determination Theory (SDT) and Ostrom's governance frameworks

---

## ✨ Core Features (In Development)

### 🐍 Data Parser
Python script to fetch raw voting patterns via Snapshot API
- GraphQL integration with Snapshot Hub
- Automatic caching for offline analysis
- Rate-limited requests to respect API quotas

### 📊 Fatigue Index
Custom metric based on Self-Determination Theory (SDT)
- **Participation Rate** - Rolling 30/90 day activity windows
- **Burnout Detection** - Identifies rapid voting → silence patterns
- **Trend Analysis** - Declining vs. stable engagement over time

### 🛡️ Public Good
Open Source (MIT), no token, privacy-preserving
- ✅ No PII collection (only public wallet addresses)
- ✅ Local-first processing (no external database)
- ✅ Transparent algorithms (open-source metrics)
- ✅ Community-owned research

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10 or higher
- pip (Python package manager)
- Git

### Installation

```bash
# Clone the repository
git clone https://github.com/TwojNick/participation-architecture.git
cd participation-architecture

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

```bash
# 1. Collect data from Snapshot
python src/main.py collect --proposals 50

# 2. Run the analysis
python src/main.py analyze

# 3. Generate a report
python src/main.py report --output data/report.md
```

### Example Output

```
📊 DAO HEALTH SUMMARY
============================================================
Total Delegates: 342
Avg Participation 30d: 0.456 (45.6%)
Avg Fatigue Score: 32.4/100
At Risk Delegates: 28 (8.2%)
Active Delegates: 156 (45.6%)

TOP 10 AT-RISK DELEGATES (Highest Fatigue)
============================================================
delegate                                    fatigue_score  longest_break_days
0x1234...5678                              87.5           120
0xabcd...ef01                              82.3           95
...
```

---

## 📂 Project Structure

```
participation-architecture/
├── src/                   # Core Python logic
│   ├── collector.py      # Snapshot API integration
│   ├── analysis.py       # Fatigue metrics & SDT logic
│   └── main.py           # CLI entry point
├── data/                  # Local cache & results (git-ignored)
│   ├── cache/            # Raw Snapshot data
│   └── results.json      # Analysis output
├── docs/                  # Research documentation
├── tests/                 # Unit tests
├── architecture.md        # Technical documentation & Data Flow
├── requirements.txt       # Python dependencies
├── README.md              # This file
└── LICENSE                # MIT License
```

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

### Ostrom's Common-Pool Resource Framework

DAOs are digital commons requiring active stewardship. This tool helps identify when "resource monitors" (delegates) are overextended.

---

## 📊 Metrics Explained

### Participation Rate
**Formula:** `votes_cast / total_proposals_in_window`

Measures baseline activity over 30/90 day periods.

### Fatigue Score (0-100)
**Components:**
- Long voting gaps (0-30 points)
- Burnout pattern detection (0-50 points)
- Declining participation trend (0-20 points)

**Interpretation:**
- 0-30: Healthy engagement
- 31-60: Moderate fatigue signals
- 61-100: High risk of disengagement

### Burnout Detection
Flags when recent inactivity exceeds 2x the delegate's historical average gap.

---

## 🛠️ Advanced Usage

### Analyze Specific DAO Space

```bash
python src/main.py collect --space "ens.eth" --proposals 100
python src/main.py analyze --space "ens.eth"
```

### Export to CSV

```bash
python src/main.py analyze --output data/results.csv
```

### Custom Analysis Window

Edit `src/analysis.py` to adjust rolling window parameters:
```python
participation_60d = self.calculate_participation_rate(voter, window_days=60)
```

---

## 🧪 Testing

Run the test suite:

```bash
# All tests
pytest tests/ -v

# With coverage report
pytest tests/ --cov=src --cov-report=html
```

---

## 🗺️ Roadmap

### Phase 1: MVP (Current)
- [x] Snapshot API integration
- [x] Basic fatigue metrics
- [x] CLI interface
- [ ] Unit test coverage >80%

### Phase 2: Advanced Analytics
- [ ] Alignment score (voting consistency)
- [ ] Network analysis (delegate clusters)
- [ ] Predictive modeling (churn probability)

### Phase 3: Dashboard
- [ ] Web-based visualization
- [ ] Real-time monitoring
- [ ] Delegate profiles with historical trends

### Phase 4: Multi-DAO Support
- [ ] Tally API integration
- [ ] Comparative analysis across DAOs
- [ ] Standardized governance health benchmarks

---

## 🤝 Contributing

This is a research project in active development. Contributions welcome!

### Ways to Contribute:
- 📝 Improve metric definitions based on governance research
- 🐛 Report bugs or edge cases in data processing
- 🔬 Validate findings against real delegate experiences
- 📚 Expand documentation and examples

### Development Setup

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run linter
flake8 src/ tests/

# Format code
black src/ tests/
```

See `CONTRIBUTING.md` for detailed guidelines.

---

## 📄 License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

### What This Means:
✅ Free to use, modify, and distribute  
✅ Commercial use allowed  
✅ No warranty provided  

---

## 👤 About

**Built by a Solo Researcher** combining social science (Ostrom's Theory) with code.

### Research Background:
- Governance participation patterns in digital commons
- Self-Determination Theory applied to DAO engagement
- Commons management in decentralized systems

### Contact & Feedback:
- GitHub Issues: [Report bugs or request features](https://github.com/TwojNick/participation-architecture/issues)
- Twitter: [@YourHandle](https://twitter.com/YourHandle)
- Forum: [Arbitrum Governance Forum](https://forum.arbitrum.foundation/)

---

## 📚 Additional Resources

### Documentation
- [Technical Architecture](architecture.md) - System design & data flow
- [Metric Definitions](docs/metrics.md) - Detailed formula explanations
- [SDT Framework](docs/sdt-framework.md) - Theoretical foundation

### Related Research
- [Self-Determination Theory Overview](https://selfdeterminationtheory.org/)
- [Ostrom's Governing the Commons](https://wtf.tw/ref/ostrom_1990.pdf)
- [DAO Governance Patterns](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4620723)

---

## 🙏 Acknowledgments

- **Arbitrum DAO** - Inspiration and data source
- **Snapshot Labs** - Public API access
- **Governance Research Community** - Theoretical foundations

---

## 📈 Project Status

**Current Version:** 0.1.0-MVP  
**Last Updated:** November 2024  
**Active Development:** Yes ✅

### Known Limitations:
- Snapshot-only (on-chain voting not yet supported)
- English-language proposals only
- Limited to Ethereum-based DAOs

---

## 🔗 Links

- **Repository:** https://github.com/TwojNick/participation-architecture
- **Documentation:** [architecture.md](architecture.md)
- **Issue Tracker:** https://github.com/TwojNick/participation-architecture/issues
- **Discussions:** https://github.com/TwojNick/participation-architecture/discussions

---

<div align="center">

**Made with 🧠 for healthier DAOs**

[Report Bug](https://github.com/TwojNick/participation-architecture/issues) · [Request Feature](https://github.com/TwojNick/participation-architecture/issues) · [Documentation](architecture.md)

</div>
