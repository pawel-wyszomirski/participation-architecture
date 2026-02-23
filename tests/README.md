# Tests - Participation Architecture

**Status:** 55/55 passing | **Coverage:** Rule Engine (30) + Fatigue Engine (25)

---

## Test Structure

```
tests/
├── README.md              (this file)
├── rules/
│   ├── __init__.py
│   └── test_rule_engine.py    (30 tests - all 21 rules)
└── fatigue/
    ├── __init__.py
    └── test_fatigue_engine.py (25 tests - all 5 components)
```

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Fatigue engine only
pytest tests/fatigue/ -v

# Rule engine only
pytest tests/rules/ -v

# Single test
pytest tests/rules/test_rule_engine.py::test_sec_001_strict_active_incident -v

# With coverage report
pytest --cov=app/services --cov-report=html
# Then open htmlcov/index.html
```

---

## Rule Engine Tests (`tests/rules/test_rule_engine.py`)

**30 test cases** covering all 21 rules (100% coverage).

### Engine initialization (1 test)
- `test_engine_loads_rulebook` - verifies rulebook v2.7.0 loads with >=20 rules

### Security rules (2 tests)
- `test_sec_001_strict_active_incident` - exploit keywords -> EMERGENCY + INCIDENT labels, score >=95
- `test_sec_001_strict_negative` - generic security words without threat -> rule does NOT fire

### Technical rules (2 tests)
- `test_tech_001_protocol_upgrade` - upgrade keywords -> PROTOCOL_UPGRADE, score >=80
- `test_tech_002_parameter_change` - parameter/fee keywords -> PARAMETER_CHANGE, score >=70

### Treasury rules (4 tests)
- `test_tre_010_tier_1_allocation` - >$10M -> TREASURY_TIER_1, score >=85
- `test_tre_010_tier_2_allocation` - >$1M -> TREASURY_TIER_2, score >=75
- `test_tre_010_tier_3_allocation` - >$100K -> TREASURY_TIER_3, score >=60
- `test_tre_021_treasury_keywords_no_amount` - budget keywords without amount -> BUDGET_UNCLEAR

### Governance rules (2 tests)
- `test_gov_030_constitutional` - constitution/bylaws keywords -> GOVERNANCE_FRAMEWORK, score >=75
- `test_prog_001_new_program` - new program/initiative keywords -> NEW_PROGRAM, score >=70

### Other categories (5 tests)
- `test_meta_001_rfc` - RFC/discussion/temperature check -> META_GOV, score <=50
- `test_spon_001_sponsorship` - sponsorship/hackathon keywords -> SPONSORSHIP, score <=60
- `test_rep_001_strict_reporting` - report/transparency keywords -> REPORTING, score <=35
- `test_res_001_research` - research/analysis keywords -> RESEARCH, score <=40
- `test_ops_050_operational` - maintenance/renewal keywords -> OPERATIONS, score <=45

### Context detection (2 tests)
- `test_ctx_002_election_context` - election/nomination keywords -> ELECTIONS label
- `test_ctx_003_hr_context` - salary/compensation keywords -> OPERATIONS + BUDGET labels

### Overrides (3 tests)
- `test_override_closed_critical_protocol` - closed protocol upgrade -> deep_review maintained
- `test_override_closed_general_kill_switch` - closed minor proposal -> score <=50, standard_review
- `test_override_closed_election` - closed election -> score <=30, informational_only

### Modifiers (4 tests)
- `test_time_modifiers_urgent` - <24h remaining -> TIME-MODIFIERS fires (+15 priority)
- `test_time_modifiers_upcoming` - 48-72h remaining -> TIME-MODIFIERS fires (+5 priority)
- `test_workload_modifiers_long` - >3000 words -> LONG_FORM label
- `test_workload_modifiers_very_long` - >5000 words -> VERY_LONG_FORM label

### Default + edge cases (4 tests)
- `test_default_classification` - no matches -> UNCATEGORIZED, score 30-50
- `test_empty_body_proposal` - empty body -> no crash, score >=0
- `test_very_long_title` - 1000-char title -> no crash
- `test_null_optional_fields` - all optional fields None -> no crash

### Determinism (1 test)
- `test_determinism_same_input_same_output` - same proposal -> same score, labels, reasons

---

## Fatigue Engine Tests (`tests/fatigue/test_fatigue_engine.py`)

**25 test cases** covering all 5 components, status thresholds, determinism, and edge cases.

### Engine initialization (2 tests)
- `test_engine_loads_config` - config v1.0.0 loads, weights sum to 1.0
- `test_engine_formula_string` - FORMULA class attribute is present

### Zero-load baseline (2 tests)
- `test_zero_load_empty_proposals` - no proposals -> score = 0.0, status = LOW
- `test_zero_load_old_proposals` - proposals older than 30d -> score = 0.0

### Volume component (2 tests)
- `test_volume_at_reference_produces_moderate_component` - 5 proposals/7d -> volume ~0.5
- `test_volume_above_reference_capped_at_one` - 20 proposals/7d -> volume = 1.0 (capped)

### Concurrency component (2 tests)
- `test_concurrency_all_active` - 10 active proposals -> concurrency = 1.0
- `test_concurrency_zero_when_all_closed` - all closed -> concurrency = 0.0

### Burstiness component (2 tests)
- `test_burstiness_zero_when_volume_at_average` - this week = rolling avg -> burstiness = 0.0
- `test_burstiness_high_on_spike` - 3x spike above avg -> burstiness > 0.5

### Reading time component (3 tests)
- `test_reading_time_zero_for_empty_body` - empty body -> reading_time = 0.0
- `test_reading_time_moderate_at_reference_length` - 3000 words -> reading_time ~0.5
- `test_reading_time_capped_for_very_long_proposal` - 10000 words -> reading_time = 1.0

### Novelty component (3 tests)
- `test_novelty_zero_for_routine_proposals` - report/renewal keywords -> novelty = 0.0
- `test_novelty_nonzero_for_novel_proposals` - exploit/upgrade keywords -> novelty > 0.0
- `test_novelty_zero_for_novel_and_routine_mixed` - both keywords -> routine wins, novelty = 0.0

### Status thresholds (2 tests)
- `test_status_low_on_zero_load` - score < 30 -> status = LOW
- `test_status_critical_on_extreme_load` - maximum load -> status = CRITICAL

### Determinism (2 tests)
- `test_same_input_same_output` - identical proposals -> identical score
- `test_address_does_not_affect_score` - different address, same proposals -> same score

### Result structure (2 tests)
- `test_result_contains_all_fields` - all required fields present in result
- `test_result_weights_match_config` - weights in result match fatigue_config.yaml

### Edge cases (3 tests)
- `test_single_proposal` - exactly one proposal in window -> no crash, valid score
- `test_proposal_starting_right_now` - start == now -> counted in concurrent_active
- `test_proposal_ending_right_now_not_concurrent` - end < now -> NOT counted in concurrent

---

## Writing New Tests

### Rule engine test template

```python
def test_rule_xyz_positive(engine):
    """XYZ-001: Keyword match -> EXPECTED_LABEL, score >= N"""
    proposal = create_test_proposal(
        title="...",
        body="...",
    )
    result = engine.evaluate_proposal(proposal)

    assert "XYZ-001" in result.reasons
    assert "EXPECTED_LABEL" in result.labels
    assert result.priority_score >= 65


def test_rule_xyz_negative(engine):
    """XYZ-001: Generic content without keywords -> rule does NOT fire"""
    proposal = create_test_proposal(
        title="Something unrelated",
        body="No relevant keywords here.",
    )
    result = engine.evaluate_proposal(proposal)

    assert "XYZ-001" not in result.reasons
    assert "EXPECTED_LABEL" not in result.labels
```

### Fatigue engine test template

```python
def test_component_name(engine, now):
    """Component X: specific scenario -> expected value"""
    proposals = [
        MockProposal(
            start=now - timedelta(days=3),
            end=now + timedelta(days=4),
            body="test body",
            title="test title",
            state="active",
        )
    ]
    result = engine.compute("0x1234", proposals, now)

    assert result.components.volume == pytest.approx(0.5, abs=0.1)
```

### Best practices

1. Always write both positive and negative cases for rule tests
2. Use the `now` fixture (fixed datetime) in fatigue tests for reproducibility
3. Use `MockProposal` dataclass instead of real DB models in fatigue tests
4. Test one assertion per logical concept
5. Document the expected behavior in the docstring

---

## Troubleshooting

**ModuleNotFoundError:** Run from project root: `cd participation-architecture && pytest`

**RuleEngine not found:** Check that `rulebook.yaml` is in project root: `ls rulebook.yaml`

**FatigueEngine not found:** Check that `fatigue_config.yaml` is in project root: `ls fatigue_config.yaml`

**Python version:** Requires 3.11+: `python3 --version`

---

**Last updated:** 2026-02-23
**Test suite version:** 2.0.0
**Milestones covered:** M1 + M2
