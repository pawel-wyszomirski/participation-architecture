# Video Tutorial 3: Customize the Rulebook

**"Add your own triage rules and run the tests"**

Target audience: Developers who want to extend the rule engine for their own DAO or use case.
Duration: ~12-15 minutes.

Prerequisites: API running locally (see Tutorial 1).

---

## What we'll cover

1. How the rulebook works (YAML structure)
2. Adding a new rule for a specific keyword pattern
3. Writing a test for the new rule
4. Running the full test suite to verify nothing broke
5. Customizing the Fatigue Index weights

Ready-to-use snippets are in the repo:
- Rule: `scripts/tutorial-03-new-rule.yaml`
- Tests: `scripts/tutorial-03-new-tests.py`

---

## Script

### Intro (0:00 - 0:45)

> "In this video, I'll show you how to customize the rulebook - add your own triage rules and verify them with tests. The rule engine is fully deterministic: same input, same output, every time."

> "I've prepared the snippets in the repo so you can follow along without typing everything from scratch."

---

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

> "Each rule has: `id` (used in the `reasons` field of API responses), `phase` (evaluation order), `label` (added to the labels array), `type` (strict = set minimum score; soft = add to score), `keywords` (checked against title and body), `min_score` (for strict rules)."

---

### Adding a new rule (3:00 - 7:00)

> "Let's add a rule that detects developer grant programs. The snippet is ready in the repo."

**Show the snippet first:**

```bash
cat scripts/tutorial-03-new-rule.yaml
```

**Then add it to `rulebook.yaml` after the PROG-001 rule:**

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

> "Using `type: soft` with `base_score: 65` - this contributes a base score, and other rules can add to it. If a proposal mentions both a developer grant and a protocol upgrade, both rules fire and the scores combine."

---

### Writing the tests (7:00 - 10:00)

> "Every rule needs tests - a positive case and a negative case. The test snippets are ready too."

**Show the snippet:**

```bash
cat scripts/tutorial-03-new-tests.py
```

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

> "Always write both positive and negative cases. The positive test checks that our keywords trigger the rule. The negative test makes sure generic grants without developer context don't fire it."

---

### Running the tests (10:00 - 12:00)

```bash
python3 -m pytest tests/ -v
```

> "All existing tests plus our 2 new ones should pass. If any old test breaks, it means our rule conflicts with an existing one - the test suite catches that."

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

> "Weights must sum to 1.0. If your DAO has high volume but proposals are short, you might increase the volume weight and decrease reading_time."

```yaml
reference_values:
  volume_7d: 8       # your DAO: 8 proposals/week as normal
  volume_30d: 30     # your DAO: 30 proposals/month as normal
  concurrent: 8      # your DAO: 8 simultaneous proposals as normal
  reading_words: 3000
```

> "Change `reference_values` to match your DAO's baseline activity. Restart the API to reload config."

```bash
curl http://localhost:8000/debug/fatigue-config | python3 -m json.tool
```

> "Verify the new config loaded correctly."

---

### Wrap up (14:00 - 15:00)

> "Key workflow: edit YAML, write tests, run tests, verify. The rulebook is a versioned institutional artifact - every change is testable and auditable."

> "All snippets from this tutorial are in the `scripts/` folder: `tutorial-03-new-rule.yaml` and `tutorial-03-new-tests.py`. The full rulebook documentation is in `rulebook.md`."

> "Thanks for watching. The repo is open source - issues and PRs are welcome at github.com/pawel-wyszomirski/participation-architecture."

---

## Demo commands summary

```bash
# View ready-made snippets
cat scripts/tutorial-03-new-rule.yaml
cat scripts/tutorial-03-new-tests.py

# Edit the rulebook
nano rulebook.yaml

# Add tests
nano tests/rules/test_rule_engine.py

# Run tests
python3 -m pytest tests/ -v

# Verify configs loaded
curl http://localhost:8000/debug/fatigue-config | python3 -m json.tool
curl http://localhost:8000/debug/rulebook | python3 -m json.tool
```
