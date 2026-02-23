# Video Tutorial 3: Customize the Rulebook

**"Add your own triage rules and run the tests"**

Target audience: Developers who want to extend the rule engine for their own DAO or use case.
Duration: ~12-15 minutes.

---

## What we'll cover

1. How the rulebook works (YAML structure)
2. Adding a new rule for a specific keyword pattern
3. Writing a test for the new rule
4. Running the full test suite to verify nothing broke
5. Customizing the Fatigue Index weights

---

## Script

### Understanding the rulebook structure (0:45 - 3:00)

**Open `rulebook.yaml` in the editor:**

```yaml
- id: TECH-001-STRICT
  category: TECHNICAL
  phase: 2
  label: PROTOCOL_UPGRADE
  type: strict
  keywords:
    - hard fork
    - sequencer upgrade
    - arbos
    - upgrade
  min_score: 80
  description: "Protocol upgrades - high impact technical changes"
```

> "Each rule has: `id` (used in `reasons` field), `phase` (evaluation order), `label` (added to labels array), `type` (strict = set minimum score; soft = add to score), `keywords` (checked against title and body), `min_score` (for strict rules)."

---

### Adding a new rule (3:00 - 7:00)

**Edit `rulebook.yaml`, add after the PROG-001 rule:**

```yaml
- id: PROG-002
  category: PROGRAMS
  phase: 3
  label: DEVELOPER_GRANTS
  type: soft
  keywords:
    - developer grant
    - builder program
    - developer incentive
    - build grant
  base_score: 65
  description: "Developer-focused grant programs and builder incentives"
```

> "Using `type: soft` with `base_score: 65` - contributes a base score, other rules can add to it."

---

### Writing the test (7:00 - 10:00)

**Add to `tests/rules/test_rule_engine.py`:**

```python
def test_prog_002_developer_grants(engine):
    """PROG-002: Developer grant keywords -> DEVELOPER_GRANTS label"""
    proposal = create_test_proposal(
        title="Developer Grants Program Q1",
        body="Proposing a new developer incentive and build grant to attract builders."
    )
    result = engine.evaluate_proposal(proposal)

    assert "PROG-002" in result.reasons
    assert "DEVELOPER_GRANTS" in result.labels
    assert result.priority_score >= 65


def test_prog_002_negative(engine):
    """PROG-002: Generic grants without developer context -> Should NOT fire"""
    proposal = create_test_proposal(
        title="Community Grant",
        body="General community funding without developer focus."
    )
    result = engine.evaluate_proposal(proposal)

    assert "PROG-002" not in result.reasons
    assert "DEVELOPER_GRANTS" not in result.labels
```

> "Always write both positive and negative cases."

---

### Running the tests (10:00 - 12:00)

```bash
python3 -m pytest tests/ -v
```

> "55 existing tests plus 2 new ones. I expect 57 to pass."

---

### Customizing the Fatigue Index (12:00 - 14:00)

**Open `fatigue_config.yaml`:**

```yaml
weights:
  volume: 0.40
  concurrency: 0.25
  burstiness: 0.20
  reading_time: 0.10
  novelty: 0.05
```

> "Weights must sum to 1.0. Change `reference_values` if your DAO has different baseline activity."

```yaml
reference_values:
  volume_7d: 8       # your DAO: 8 proposals/week as normal
  volume_30d: 30     # your DAO: 30 proposals/month as normal
  concurrent: 8      # your DAO: 8 simultaneous proposals as normal
  reading_words: 3000
```

> "Restart the API to reload config. Verify with `GET /debug/fatigue-config`."

---

### Wrap up

> "Key workflow: edit YAML -> write test -> run tests -> verify."

> "All documentation is in the docs/ folder. The rulebook.md explains every existing rule in detail."

---

## Demo commands summary

```bash
# Edit the rulebook
nano rulebook.yaml

# Add tests
nano tests/rules/test_rule_engine.py

# Run tests
python3 -m pytest tests/ -v

# Verify fatigue config loaded
curl http://localhost:8000/debug/fatigue-config | python3 -m json.tool

# Verify rulebook loaded
curl http://localhost:8000/debug/rulebook | python3 -m json.tool
```
