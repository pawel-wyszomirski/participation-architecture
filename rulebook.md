# Participation Architecture — Rulebook v1 (Deterministic)

**Purpose**  
This rulebook defines a **deterministic, auditable** system for:

1) labeling governance items (proposals, votes, forum threads) with standardized **labels**,  
2) producing a **priority_score (0–100)** using transparent point rules, and  
3) returning **reasons** (rule IDs) + a **recommended_handling** value.

**Design goals**
- **No ML / no LLM / no semantic inference.**
- Every output must be explainable as **“these rule IDs fired.”**
- Rules must be stable, versioned, and testable.

**Non-goals**
- Predicting vote outcomes.
- Replacing human judgment.
- Building any UI/dashboard.

---

## 1) Scope

### 1.1 Covered item types
- `proposal` (onchain/offchain)
- `vote` (as an event tied to a proposal)
- `discussion` (forum thread / temperature check)

### 1.2 Supported venues (initial)
- Snapshot-style governance
- Tally-style governance

The ingestion layer maps venue-specific objects into a single normalized schema (below).

---

## 2) Normalized schema (inputs used by rules)

Rules MUST only rely on these normalized fields (if a field is missing, rules must handle it gracefully).

### 2.1 Core fields
- `item_id` (string)
- `venue` (enum: `snapshot|tally|forum|other`)
- `chain` (string; e.g., `arbitrum-one`)
- `item_type` (enum: `proposal|discussion`)
- `title` (string)
- `body` (string)
- `author` (string)
- `created_at` (timestamp)
- `start_at` (timestamp)
- `end_at` (timestamp)
- `status` (enum: `draft|active|closed|executed|canceled|unknown`)

### 2.2 Governance metadata (optional but recommended)
- `proposal_kind` (enum: `constitutional|treasury|election|technical|ops|meta|unknown`)
- `requested_amount_usd` (number | null)
- `requested_amount_arb` (number | null)
- `execution_type` (enum: `onchain|offchain|multisig|informational|unknown`)
- `affects_protocol_parameters` (bool | null)
- `affects_security` (bool | null)
- `affects_treasury` (bool | null)
- `tags` (string[])
- `links` (url[])

### 2.3 Text-derived fields (deterministic)
Derived deterministically during ingestion:
- `word_count` (int)
- `keyword_hits` (map[string]int) — counts for configured keyword groups

---

## 3) Outputs

Every item returns:
- `labels`: string[]
- `priority_score`: integer 0–100
- `recommended_handling`: enum
  - `urgent_deep_review`
  - `deep_review`
  - `standard_review`
  - `fast_track_ok`
  - `informational_only`
- `reasons`: rule_id[]

---

## 4) Rule evaluation model

### 4.1 Determinism
Rules are evaluated in a fixed order:

1) **Label rules** (apply labels)  
2) **Base priority rules** (set minimum/maximum/points)  
3) **Time sensitivity modifiers** (remaining time, status)  
4) **Length / workload modifiers** (word count tiers)  
5) Clamp score to **0–100**  
6) Map to `recommended_handling` by score band

If multiple rules set a minimum/maximum, the engine applies:
- `min_priority = max(all mins)`
- `max_priority = min(all maxs)`
- `score = clamp(score, min_priority, max_priority)`

### 4.2 Conflict handling
- Labels are additive.
- If a rule adds points and another caps the score, the cap wins.
- Any **SECURITY**-class rule forces `recommended_handling = urgent_deep_review` (regardless of points) and enforces a minimum score.

---

## 5) Label taxonomy

Labels are standardized to support integrations.

### 5.1 Primary labels
- `SECURITY`
- `PROTOCOL_UPGRADE`
- `PARAMETER_CHANGE`
- `TREASURY`
- `ELECTIONS`
- `GOVERNANCE_FRAMEWORK`
- `GRANTS_PROGRAM`
- `OPERATIONS`
- `REPORTING`
- `META_GOV`
- `COMMUNICATION`

### 5.2 Secondary labels (optional)
- `EMERGENCY`
- `AUDIT`
- `INCIDENT`
- `BUDGET`
- `RISK`
- `POLICY`

---

## 6) Priority score model (points + caps)

Start with `score = 0`.

### 6.1 Base severity (set minimums)
These rules set **minimum** priority based on impact class.

- SECURITY / INCIDENT / EMERGENCY → min 90
- PROTOCOL UPGRADE / PARAMETER CHANGE (high risk) → min 80
- TREASURY (large) → min 75
- GOVERNANCE FRAMEWORK (constitutional/process changes) → min 70
- ELECTIONS → min 65
- GRANTS PROGRAM (routine) → min 55
- OPERATIONS (routine) → max 40
- REPORTING / STATUS UPDATES → max 30

### 6.2 Magnitude tiers (treasury)
If `requested_amount_usd` is known:
- ≥ $10,000,000 → +20 and min 85
- ≥ $1,000,000 → +15 and min 75
- ≥ $100,000 → +10 and min 65
- ≥ $10,000 → +5 and min 55

If amount is unknown but the item contains deterministic budget cues (see keywords), apply **only +5** (no large-tier min).

### 6.3 Time sensitivity modifiers
Based on `end_at` for active proposals.
- ≤ 24h remaining → +15
- ≤ 48h remaining → +10
- ≤ 72h remaining → +5

If status is `executed` or `closed`, apply `max_priority = 50` unless it is labeled `REPORTING` (then max 30) or `INCIDENT` (then min 70).

### 6.4 Workload (length) modifiers
Using `word_count`:
- ≥ 3,000 words → +10
- ≥ 1,500 words → +6
- ≥ 800 words → +3

### 6.5 Recommendation mapping
- 90–100 → `urgent_deep_review`
- 75–89 → `deep_review`
- 50–74 → `standard_review`
- 25–49 → `fast_track_ok`
- 0–24 → `informational_only`

**Override:** Any item labeled `SECURITY` ⇒ `urgent_deep_review`.

---

## 7) Keyword groups (deterministic matching)

Matching is **case-insensitive** and performed on `title + body`.

### 7.1 SECURITY_CUES
`exploit`, `vulnerability`, `attack`, `incident`, `hack`, `emergency`, `critical`, `CVE`, `post-mortem`, `drain`, `compromise`, `security patch`

### 7.2 UPGRADE_CUES
`upgrade`, `deploy`, `migration`, `hard fork`, `soft fork`, `release`, `version`, `audit`, `timelock`, `rollup`, `sequencer`

### 7.3 PARAMETER_CUES
`parameter`, `config`, `fee`, `gas`, `limit`, `threshold`, `quorum`, `timelock`, `delay`, `rate`, `slippage`, `oracle`

### 7.4 TREASURY_CUES
`budget`, `funding`, `grant`, `allocate`, `allocation`, `USD`, `$`, `ARB`, `treasury`, `payment`, `stream`, `invoice`, `retro`

### 7.5 ELECTION_CUES
`election`, `nomination`, `candidate`, `term`, `delegate council`, `committee`, `appoint`, `remove`, `renew`

### 7.6 REPORTING_CUES
`weekly`, `monthly`, `report`, `update`, `retrospective`, `summary`, `status`, `metrics`, `dashboard` (NOTE: keyword only; no UI scope)

### 7.7 OPS_CUES
`housekeeping`, `admin`, `operational`, `maintenance`, `process`, `procedure`, `renewal`, `extension`, `calendar`

---

## 8) Rule definitions (v1)

Each rule has:
- `id`
- `name`
- `when` (conditions)
- `then` (actions)
- `rationale`

Below are the **v1 core rules**. Additions must follow the same pattern.

### 8.1 SECURITY rules

**SEC-001 — Emergency / incident / exploit cues**
- **When:** `SECURITY_CUES` hits ≥ 2 OR (`SECURITY_CUES` hits ≥ 1 AND `UPGRADE_CUES` hits ≥ 1)
- **Then:** add label `SECURITY`, add label `INCIDENT`, set min 90, add +10, set recommendation `urgent_deep_review`
- **Rationale:** Any credible security cue should be escalated.

**SEC-002 — Audit / vulnerability disclosure**
- **When:** `audit` hit ≥ 1 AND (`vulnerability` OR `critical`) hit ≥ 1
- **Then:** add label `SECURITY`, add label `AUDIT`, set min 85, add +5
- **Rationale:** Security posture changes require focused review.

### 8.2 Protocol/parameter rules

**TECH-010 — Protocol upgrade**
- **When:** `UPGRADE_CUES` hits ≥ 2 OR `proposal_kind == technical`
- **Then:** add label `PROTOCOL_UPGRADE`, set min 80, add +5
- **Rationale:** Upgrades can affect system safety and operations.

**TECH-011 — Parameter change**
- **When:** `PARAMETER_CUES` hits ≥ 2 OR `affects_protocol_parameters == true`
- **Then:** add label `PARAMETER_CHANGE`, set min 75, add +5
- **Rationale:** Parameter shifts can change incentives/risk.

### 8.3 Treasury rules

**TRE-020 — Treasury spend (amount known)**
- **When:** `requested_amount_usd != null`
- **Then:** add label `TREASURY` and apply magnitude tiers (Section 6.2)
- **Rationale:** Larger allocations require more scrutiny.

**TRE-021 — Treasury cues (amount unknown)**
- **When:** `TREASURY_CUES` hits ≥ 2 AND `requested_amount_usd == null`
- **Then:** add label `TREASURY`, add +5, set min 55
- **Rationale:** Budget-like proposals deserve baseline attention even without parsed amounts.

### 8.4 Governance framework rules

**GOV-030 — Constitutional / framework change**
- **When:** `proposal_kind == constitutional` OR keyword hits include (`constitution`, `charter`, `framework`, `AIP`, `SOS`, `bylaws`) ≥ 2
- **Then:** add label `GOVERNANCE_FRAMEWORK`, set min 70, add +5
- **Rationale:** Process/constitution changes have long-term impact.

**GOV-031 — Quorum / voting procedure changes**
- **When:** `PARAMETER_CUES` hits ≥ 2 AND keywords include (`quorum` OR `voting procedure` OR `threshold`) ≥ 1
- **Then:** add label `GOVERNANCE_FRAMEWORK`, set min 75, add +5
- **Rationale:** Decision mechanics are core governance.

### 8.5 Elections rules

**ELE-040 — Elections / nominations**
- **When:** `ELECTION_CUES` hits ≥ 2 OR `proposal_kind == election`
- **Then:** add label `ELECTIONS`, set min 65, add +5
- **Rationale:** Leadership/roles affect execution capacity.

### 8.6 Routine ops / reporting rules (caps)

**OPS-050 — Operational / administrative**
- **When:** `OPS_CUES` hits ≥ 2 OR `proposal_kind == ops`
- **Then:** add label `OPERATIONS`, set max 40, add +0
- **Rationale:** Many ops items can be fast-tracked.

**REP-060 — Reporting / status update**
- **When:** `REPORTING_CUES` hits ≥ 2 OR title contains (`weekly update` OR `monthly report`)
- **Then:** add label `REPORTING`, set max 30
- **Rationale:** Informational items should not crowd high-impact work.

**META-070 — Meta discussion / temperature check**
- **When:** `item_type == discussion` OR title contains `temperature check`
- **Then:** add label `META_GOV`, set max 50
- **Rationale:** Useful context, typically not urgent execution.

---

## 9) Recommended handling definitions

- `urgent_deep_review`: immediate attention; notify delegates/builders; highlight deadlines.
- `deep_review`: allocate focused reading time; seek subject-matter input.
- `standard_review`: normal workflow; may be grouped in weekly digest.
- `fast_track_ok`: safe to batch; quick vote/checklist.
- `informational_only`: archive/record; optional reading.

---

## 10) Fatigue Index (related, deterministic math)

While the rulebook governs **item triage**, the system also exposes a **Delegate Fatigue Index**.

### 10.1 Inputs (all deterministic)
For a given delegate address and time window (7d, 30d):
- `items_active`: number of active proposals in window
- `votes_cast`: votes cast in window
- `concurrency_peak`: max simultaneous active proposals
- `reading_load_words`: sum of `word_count` for active proposals (or top-N by priority)
- `burstiness`: (max daily items − average daily items) / max(1, average daily items)

### 10.2 Example formula (v1)
Normalize each component to 0–1 via caps, then scale to 0–100:

- `V = min(1, items_active / 20)`
- `C = min(1, concurrency_peak / 10)`
- `R = min(1, reading_load_words / 20_000)`
- `B = min(1, burstiness)`

`fatigue = round(100 * (0.35*V + 0.30*C + 0.25*R + 0.10*B))`

Return also `components` so users can see what drove the score.

---

## 11) Versioning & change control

- Rulebook versions follow **SemVer**: `vMAJOR.MINOR.PATCH`.
- Any threshold or mapping change increments MINOR.
- Any label rename or output schema change increments MAJOR.

### 11.1 Required artifacts
- `rulebook.yaml` (machine-readable)
- `rulebook.md` (this document)
- `tests/rules/` (test cases)
- `CHANGELOG.md`

---

## 12) Machine-readable rulebook (YAML template)

Below is a **starter structure** for `rulebook.yaml`.

```yaml
version: 1.0.0
metadata:
  owner: "Participation Architecture"
  default_locale: "en"
  notes: "Deterministic triage rules. No ML."

keyword_groups:
  SECURITY_CUES: ["exploit", "vulnerability", "attack", "incident", "hack", "emergency", "critical", "cve", "post-mortem", "drain", "compromise", "security patch"]
  UPGRADE_CUES: ["upgrade", "deploy", "migration", "hard fork", "soft fork", "release", "version", "audit", "timelock", "rollup", "sequencer"]
  PARAMETER_CUES: ["parameter", "config", "fee", "gas", "limit", "threshold", "quorum", "timelock", "delay", "rate", "slippage", "oracle"]
  TREASURY_CUES: ["budget", "funding", "grant", "allocate", "allocation", "usd", "$", "arb", "treasury", "payment", "stream", "invoice", "retro"]
  ELECTION_CUES: ["election", "nomination", "candidate", "term", "committee", "appoint", "remove", "renew"]
  REPORTING_CUES: ["weekly", "monthly", "report", "update", "retrospective", "summary", "status", "metrics", "dashboard"]
  OPS_CUES: ["housekeeping", "admin", "operational", "maintenance", "process", "procedure", "renewal", "extension", "calendar"]

score_mapping:
  urgent_deep_review: {min: 90, max: 100}
  deep_review: {min: 75, max: 89}
  standard_review: {min: 50, max: 74}
  fast_track_ok: {min: 25, max: 49}
  informational_only: {min: 0, max: 24}

treasury_tiers_usd:
  - {min_usd: 10000000, add: 20, min_priority: 85}
  - {min_usd: 1000000, add: 15, min_priority: 75}
  - {min_usd: 100000, add: 10, min_priority: 65}
  - {min_usd: 10000, add: 5, min_priority: 55}

rules:
  - id: "SEC-001"
    name: "Emergency / incident / exploit cues"
    when:
      any:
        - keyword_group_hits: {group: "SECURITY_CUES", gte: 2}
        - all:
            - keyword_group_hits: {group: "SECURITY_CUES", gte: 1}
            - keyword_group_hits: {group: "UPGRADE_CUES", gte: 1}
    then:
      add_labels: ["SECURITY", "INCIDENT"]
      set_min_priority: 90
      add_priority: 10
      set_recommended_handling: "urgent_deep_review"
    rationale: "Escalate credible security cues."

  - id: "TECH-010"
    name: "Protocol upgrade"
    when:
      any:
        - keyword_group_hits: {group: "UPGRADE_CUES", gte: 2}
        - field_equals: {field: "proposal_kind", value: "technical"}
    then:
      add_labels: ["PROTOCOL_UPGRADE"]
      set_min_priority: 80
      add_priority: 5
    rationale: "Upgrades require focused review."

  - id: "TRE-020"
    name: "Treasury spend (amount known)"
    when:
      field_exists: {field: "requested_amount_usd"}
    then:
      add_labels: ["TREASURY"]
      apply_treasury_tiers_usd: true
    rationale: "Larger allocations require more scrutiny."

  - id: "OPS-050"
    name: "Operational / administrative"
    when:
      any:
        - keyword_group_hits: {group: "OPS_CUES", gte: 2}
        - field_equals: {field: "proposal_kind", value: "ops"}
    then:
      add_labels: ["OPERATIONS"]
      set_max_priority: 40
    rationale: "Routine ops can be fast-tracked."
```

---

## 13) Test strategy (required for acceptance)

Every rule must include at least:
- **1 positive test case** (rule should fire)
- **1 negative test case** (rule should not fire)

Tests should validate:
- labels
- priority min/max
- points added
- recommended_handling
- reasons list includes correct rule IDs

---

## 14) How this connects to participation architecture (short rationale)

This rulebook operationalizes a key dissertation claim: participation is constrained by **attention and institutional clarity**. A deterministic rulebook is an institutional artifact: explicit boundaries, monitoring logic, and predictable coordination cues—implemented as code and exposed via API.

---

## 15) Appendix — Example outputs (JSON)

```json
{
  "item_id": "snapshot:0xabc...",
  "labels": ["TREASURY", "GOVERNANCE_FRAMEWORK"],
  "priority_score": 78,
  "recommended_handling": "deep_review",
  "reasons": ["TRE-020", "GOV-030", "TIME-002", "LEN-001"],
  "explain": {
    "min_priority": 70,
    "max_priority": 100,
    "points": [
      {"rule": "TRE-020", "add": 15},
      {"rule": "GOV-030", "add": 5},
      {"rule": "TIME-002", "add": 10},
      {"rule": "LEN-001", "add": 6}
    ]
  }
}
```

