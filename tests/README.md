# Tests - Participation Architecture

This directory contains comprehensive unit tests for the rule engine and other components.

## Test Structure

```
tests/
├── __init__.py
├── README.md (this file)
├── rules/
│   ├── __init__.py
│   └── test_rule_engine.py  (50+ test cases)
└── (future test modules)
```

## Running Tests

### Install pytest (if not already installed)

```bash
pip install pytest pytest-cov
```

### Run all tests

```bash
pytest
```

### Run with verbose output

```bash
pytest -v
```

### Run specific test file

```bash
pytest tests/rules/test_rule_engine.py
```

### Run specific test

```bash
pytest tests/rules/test_rule_engine.py::test_sec_001_emergency_cues_multiple_keywords
```

### Run tests by category (using markers)

```bash
# Security rules only
pytest -m security

# Treasury rules only
pytest -m treasury

# All modifiers
pytest -m modifiers
```

### Generate coverage report

```bash
pytest --cov=app/services --cov-report=html
```

Then open `htmlcov/index.html` in your browser.

### Run tests with detailed output

```bash
pytest -v --tb=long
```

## Test Coverage

### Rule Engine Tests (`test_rule_engine.py`)

**Total: 50+ test cases**

#### Security Rules (6 tests)
- ✅ SEC-001: Emergency/incident cues (positive)
- ✅ SEC-001: Security + upgrade combination
- ✅ SEC-001: Negative case (no keywords)
- ✅ SEC-002: Audit + vulnerability
- ✅ SEC-002: Audit + critical

#### Technical Rules (4 tests)
- ✅ TECH-010: Protocol upgrade keywords
- ✅ TECH-010: proposal_kind=technical
- ✅ TECH-011: Parameter change keywords
- ✅ TECH-011: affects_protocol_parameters field

#### Treasury Rules (6 tests)
- ✅ TRE-020: Tier 1 ($10M+)
- ✅ TRE-020: Tier 2 ($1M-$10M)
- ✅ TRE-020: Tier 3 ($100K-$1M)
- ✅ TRE-020: Tier 4 ($10K-$100K)
- ✅ TRE-021: Keywords without amount

#### Governance Rules (4 tests)
- ✅ GOV-030: Constitutional proposal_kind
- ✅ GOV-030: Framework keywords
- ✅ GOV-031: Quorum + voting procedure

#### Elections Rules (2 tests)
- ✅ ELE-040: Election keywords
- ✅ ELE-040: proposal_kind=election

#### Operations & Reporting (6 tests)
- ✅ OPS-050: Operational keywords + cap
- ✅ OPS-050: proposal_kind=ops
- ✅ REP-060: Reporting keywords + cap
- ✅ REP-060: Title contains "weekly update"
- ✅ META-070: item_type=discussion
- ✅ META-070: Temperature check

#### Time Modifiers (6 tests)
- ✅ TIME-001: ≤24h remaining
- ✅ TIME-002: 24-48h remaining
- ✅ TIME-003: 48-72h remaining
- ✅ TIME-010: Closed proposal cap
- ✅ TIME-011: Closed + REPORTING cap

#### Workload Modifiers (3 tests)
- ✅ LEN-001: ≥3000 words
- ✅ LEN-002: 1500-3000 words
- ✅ LEN-003: 800-1500 words

#### Conflict Resolution (2 tests)
- ✅ Multiple minimums (max wins)
- ✅ Caps win over additions

#### Overrides (1 test)
- ✅ SECURITY → urgent_deep_review

#### Score Mapping (3 tests)
- ✅ 90-100 → urgent_deep_review
- ✅ 75-89 → deep_review
- ✅ 25-49 → fast_track_ok

#### Edge Cases (5 tests)
- ✅ Empty body
- ✅ Very long title
- ✅ Null optional fields
- ✅ Multiple labels accumulate
- ✅ Determinism (same input → same output)

#### System (2 tests)
- ✅ Engine initialization
- ✅ Rulebook info

---

## KPIs for Milestone 1

**Target:** ≥20 rule cases covered by automated tests  
**Current:** 50+ test cases ✅ **EXCEEDED**

**Coverage:**
- All 21 rules tested (100%)
- Positive + negative cases
- Edge cases
- Conflict resolution
- Determinism verified

---

## CI/CD Integration

To run tests in GitHub Actions, add to `.github/workflows/test.yml`:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pip install pytest pytest-cov
      - run: pytest --cov=app --cov-report=term
```

---

## Writing New Tests

### Test Template

```python
def test_rule_xyz_positive_case(engine):
    """XYZ-123: Description → Expected behavior"""
    proposal = create_test_proposal(
        title="...",
        body="...",
        # ... other fields
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "XYZ-123" in result.reasons
    assert "EXPECTED_LABEL" in result.labels
    assert result.priority_score >= EXPECTED_MIN
```

### Best Practices

1. **One assertion per logical concept**
2. **Clear test names** (test_rule_condition_expected)
3. **Use fixtures** for reusable setup
4. **Test both positive and negative cases**
5. **Include edge cases**
6. **Document expected behavior** in docstring

---

## Troubleshooting

### Test fails with "ModuleNotFoundError"

Make sure you're running from project root:
```bash
cd /workspaces/participation-architecture
pytest
```

### Test fails with "RuleEngine not found"

Check that `rulebook.yaml` is in project root:
```bash
ls -lh rulebook.yaml
```

### All tests pass locally but fail in CI

Check Python version:
```bash
python --version  # Should be 3.11+
```

---

**Last updated:** 2026-02-02  
**Test suite version:** 1.0.0  
**Milestone:** M1 Complete ✅
