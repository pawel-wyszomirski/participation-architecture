# Participation Architecture — Rulebook v2.5.0 (Context-Aware Deterministic)

**Purpose**  
This rulebook defines a **deterministic, auditable, context-aware** system for:

1) labeling governance items (proposals, votes, forum threads) with standardized **labels**,  
2) producing a **priority_score (0–100)** using transparent point rules, and  
3) returning **reasons** (rule IDs) + a **recommended_handling** value.

**Design goals**
- **No ML / no LLM / no semantic inference.**
- **Context-aware**: uses flags to prevent false positives (e.g., elections blocked from security incidents).
- Every output must be explainable as **"these rule IDs fired."**
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
- `state` (enum: `draft|active|closed|executed|defeated|expired|canceled|unknown`)

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
- `flags`: string[] (internal context flags for explainability)

---

## 4) Rule evaluation model

### 4.1 Evaluation phases (fixed order)

1) **Phase 0: Context Firewall** — set context flags (`STATE_CLOSED`, `CONTEXT_ELECTION`, etc.)
2) **Phase 1: Critical Rules** — security, protocol (respect context blocks)
3) **Phase 2: Standard Classification** — labels and base priorities
4) **Phase 3: Modifiers** — time, workload
5) **Phase 4: State-Based Kill Switch & Exceptions** — override for closed items
6) **Phase 5: Default** — ensure every item has classification
7) Clamp score to **0–100**

### 4.2 Conflict handling
- Labels are additive.
- Flags are additive.
- `min_priority = max(all mins)`
- `max_priority = min(all maxs)` (caps win)
- `score = clamp(score, min_priority, max_priority)`

---

## 5) Label taxonomy

### 5.1 Primary labels
- `SECURITY` / `INCIDENT` / `EMERGENCY`
- `PROTOCOL_UPGRADE`
- `PARAMETER_CHANGE`
- `NEW_PROGRAM` / `STRATEGY`
- `TREASURY`
- `ELECTIONS`
- `GOVERNANCE_FRAMEWORK`
- `OPERATIONS`
- `REPORTING`
- `META_GOV`
- `RESEARCH`
- `SPONSORSHIP`
- `UNCATEGORIZED`

### 5.2 Secondary labels (optional)
- `AUDIT`
- `BUDGET`
- `BUDGET_UNCLEAR`
- `VERY_LONG_FORM` / `LONG_FORM` / `MEDIUM_FORM` / `STANDARD_FORM`
- `TREASURY_TIER_1` / `TREASURY_TIER_2` / `TREASURY_TIER_3` / `TREASURY_TIER_4`

---

## 6) Priority score model

### 6.1 Score mapping
| Handling | Min | Max |
|----------|-----|-----|
| `urgent_deep_review` | 90 | 100 |
| `deep_review` | 70 | 89 |
| `standard_review` | 40 | 69 |
| `fast_track_ok` | 25 | 39 |
| `informational_only` | 0 | 24 |

### 6.2 Treasury tiers
| Min USD | Add | Set Min | Label |
|---------|-----|---------|-------|
| $10M | +25 | 85 | `TREASURY_TIER_1` |
| $1M | +20 | 75 | `TREASURY_TIER_2` |
| $100K | +15 | 60 | `TREASURY_TIER_3` |
| $10K | +10 | 45 | `TREASURY_TIER_4` |
| $1K | +5 | 30 | `TREASURY_TIER_5` |

### 6.3 Time sensitivity (active items only)
| Hours | Add |
|-------|-----|
| ≤ 24h | +15 |
| ≤ 48h | +10 |
| ≤ 72h | +5 |

### 6.4 Workload tiers
| Words | Add | Label |
|-------|-----|-------|
| ≥ 5,000 | +12 | `VERY_LONG_FORM` |
| ≥ 3,000 | +8 | `LONG_FORM` |
| ≥ 1,500 | +5 | `MEDIUM_FORM` |
| ≥ 800 | +2 | `STANDARD_FORM` |

---

## 7) Keyword groups (deterministic matching)

Matching is **case-insensitive** on `title + body`.

### 7.1 ACTIVE_INCIDENT_CUES (strict — only actual incidents)
- `active exploit`
- `under active attack`
- `funds are being drained`
- `funds stolen`
- `emergency pause`
- `bridge compromised`
- `critical breach`
- `post-mortem of incident`
- `security incident`
- `active hack`

### 7.2 UPGRADE_CUES
- `arbos upgrade`, `arbos version`
- `contract upgrade`, `hard fork`, `precompile update`, `sequencer upgrade`
- `implement improvements`, `pricing algorithm`
- `voting system`, `governance contracts`
- `adopt`, `new policy`, `protocol change`, `system upgrade`

### 7.3 PARAMETER_CUES
- `parameter change`, `fee adjustment`, `gas target`, `base fee`
- `threshold change`, `config update`, `technical parameter`
- `quorum threshold`, `min l2 base fee`

### 7.4 NEW_PROGRAM_CUES
- `incentive program`, `pilot program`, `launching a new`
- `program design`, `new initiative`, `program establishment`
- `dip 2.0`, `new program`, `program creation`

### 7.5 TREASURY_CUES
- `budget request`, `funding request`, `grant request`
- `allocation request`, `payment request`, `compensation`
- `treasury spend`, `top-up`, `bonus`, `stipend`, `salary`

### 7.6 GOV_FRAMEWORK_CUES
- `constitution`, `constitutional`, `governance framework`
- `aip`, `bylaws`, `dao constitution`, `governance structure`

### 7.7 ELECTION_CUES
- `election`, `nomination`, `candidate`, `vote for`
- `reconfirmation`, `council seat`, `appoint`, `voting for`

### 7.8 META_GOV_CUES
- `temperature check`, `discussion`, `rfc`
- `community feedback`, `meta-governance`, `request for comments`

### 7.9 REPORTING_STRICT_CUES (requires title match + keyword)
- `monthly report`, `quarterly report`, `transparency report`
- `financial report`, `progress update`, `milestone report`
- `status update`, `research report`

### 7.10 OPS_CUES
- `housekeeping`, `administrative`, `operational`
- `renewal`, `calendar`, `routine`, `maintenance`

### 7.11 SPONSORSHIP_CUES
- `sponsor`, `sponsorship`, `partnership`
- `event support`, `hackathon support`
- `hackathon`, `attackathon`, `conference`, `event sponsor`

---

## 8) Rule definitions (v2.5.0)

### Phase 0: Context Firewall

**CTX-001 — Detect Closed State**
- **When:** `state` in (`closed`, `executed`, `defeated`, `expired`)
- **Then:** set flag `STATE_CLOSED`
- **Priority:** 10000

**CTX-002 — Detect Election Context**
- **When:** title contains (`election`, `nomination`, `reconfirmation`, `candidate`, `appoint`) OR `proposal_kind == election`
- **Then:** set flag `CONTEXT_ELECTION`, add label `ELECTIONS`
- **Priority:** 9999

**CTX-003 — Detect Operational/HR Context**
- **When:** title contains (`compensation`, `salary`, `bonus`, `stipend`, `pay`, `remuneration`)
- **Then:** set flag `CONTEXT_HR`, add labels `OPERATIONS`, `BUDGET`
- **Priority:** 9998

**CTX-004 — Detect Sponsorship Context**
- **When:** title contains (`sponsorship`, `sponsor`, `hackathon`, `attackathon`, `event`)
- **Then:** set flag `CONTEXT_SPONSORSHIP`
- **Priority:** 9997

---

### Phase 1: Critical Rules (context-aware)

**SEC-001-STRICT — Active Security Incident**
- **When:** 
  - NOT `CONTEXT_ELECTION`
  - NOT `STATE_CLOSED`
  - NOT `CONTEXT_SPONSORSHIP`
  - `ACTIVE_INCIDENT_CUES` hits ≥ 1
- **Then:** add labels `INCIDENT`, `EMERGENCY`, set min 95, recommendation `urgent_deep_review`
- **Priority:** 1000

**TECH-001-STRICT — Protocol Upgrade**
- **When:**
  - NOT `CONTEXT_HR`
  - NOT `CONTEXT_ELECTION`
  - NOT `CONTEXT_SPONSORSHIP`
  - `UPGRADE_CUES` hits ≥ 1
- **Then:** add label `PROTOCOL_UPGRADE`, set min 80
- **Priority:** 900

---

### Phase 2: Standard Classification

**PROG-001 — New Program Creation**
- **When:**
  - NOT `CONTEXT_HR`
  - title contains (`program`, `incentive`, `dip`) OR `NEW_PROGRAM_CUES` hits ≥ 1
- **Then:** add labels `NEW_PROGRAM`, `STRATEGY`, set min 70, add +5
- **Priority:** 860

**TECH-002 — Parameter Change**
- **When:**
  - NOT labeled `PROTOCOL_UPGRADE`
  - NOT labeled `NEW_PROGRAM`
  - `PARAMETER_CUES` hits ≥ 1
- **Then:** add label `PARAMETER_CHANGE`, set min 70, add +5
- **Priority:** 850

**TRE-010 — Treasury Spend (amount known)**
- **When:** `requested_amount_usd` exists
- **Then:** add label `TREASURY`, apply treasury tiers
- **Priority:** 800

**TRE-021 — Treasury Cues (unknown amount)**
- **When:** NOT labeled `TREASURY`, `TREASURY_CUES` hits ≥ 2
- **Then:** add labels `TREASURY`, `BUDGET_UNCLEAR`, set min 45, add +3
- **Priority:** 780

**GOV-030 — Constitutional Change**
- **When:** title contains (`constitutional`, `constitution`) OR `GOV_FRAMEWORK_CUES` hits ≥ 2
- **Then:** add label `GOVERNANCE_FRAMEWORK`, set min 75, add +5
- **Priority:** 700

**META-001 — Meta Governance**
- **When:** `META_GOV_CUES` hits ≥ 1
- **Then:** add label `META_GOV`, set max 50
- **Priority:** 600

**SPON-001 — Sponsorship**
- **When:** `CONTEXT_SPONSORSHIP` OR `SPONSORSHIP_CUES` hits ≥ 1
- **Then:** add label `SPONSORSHIP`, set max 60
- **Priority:** 500

**OPS-050 — Operational**
- **When:** NOT `CONTEXT_HR`, `OPS_CUES` hits ≥ 2
- **Then:** add label `OPERATIONS`, set max 45
- **Priority:** 400

**REP-001-STRICT — Reporting**
- **When:** title contains (`report`, `update`, `summary`) AND `REPORTING_STRICT_CUES` hits ≥ 1 AND NOT `CONTEXT_ELECTION`
- **Then:** add label `REPORTING`, set max 35
- **Priority:** 300

**RES-001 — Research**
- **When:** title contains (`research`, `study`, `analysis`) AND NOT labeled `GOVERNANCE_FRAMEWORK` AND NOT labeled `PROTOCOL_UPGRADE`
- **Then:** add label `RESEARCH`, set min 25, set max 40
- **Priority:** 350

---

### Phase 3: Modifiers

**TIME-MODIFIERS — Time Sensitivity**
- **When:** NOT `STATE_CLOSED`
- **Then:** apply time sensitivity tiers
- **Priority:** 200

**WORKLOAD-MODIFIERS — Content Length**
- **When:** always
- **Then:** apply workload tiers
- **Priority:** 150

---

### Phase 4: State-Based Kill Switch & Exceptions (priority order matters!)

**OVERRIDE-CLOSED-CRITICAL — Critical Closed Items** (Priority 110)
- **When:** `STATE_CLOSED` AND (`TREASURY_TIER_1` OR `TREASURY_TIER_2`) AND (`PROTOCOL_UPGRADE` OR `GOVERNANCE_FRAMEWORK`)
- **Then:** set max 85, set min 75, recommendation `deep_review`

**OVERRIDE-CLOSED-HIGH-VALUE — High Value Closed** (Priority 105)
- **When:** `STATE_CLOSED` AND (`TREASURY_TIER_1` OR `TREASURY_TIER_2`)
- **Then:** set max 75, recommendation `deep_review`

**OVERRIDE-CLOSED-CONSTITUTIONAL — Constitutional Protocol Closed** (Priority 104)
- **When:** `STATE_CLOSED` AND `GOVERNANCE_FRAMEWORK` AND (`PROTOCOL_UPGRADE` OR `PARAMETER_CHANGE` OR `NEW_PROGRAM`)
- **Then:** set max 80, set min 70, recommendation `deep_review`

**OVERRIDE-CLOSED-PROTOCOL — Protocol Closed** (Priority 103)
- **When:** `STATE_CLOSED` AND `PROTOCOL_UPGRADE`
- **Then:** set max 75, set min 65, recommendation `deep_review`

**OVERRIDE-CLOSED-NEW-PROGRAM — New Program Closed** (Priority 102)
- **When:** `STATE_CLOSED` AND `NEW_PROGRAM`
- **Then:** set max 70, set min 60, recommendation `standard_review`

**OVERRIDE-CLOSED-01 — General Closed** (Priority 100)
- **When:** `STATE_CLOSED` AND NOT `TREASURY_TIER_1` AND NOT `TREASURY_TIER_2` AND NOT `PROTOCOL_UPGRADE` AND NOT `GOVERNANCE_FRAMEWORK` AND NOT `NEW_PROGRAM`
- **Then:** set max 50, recommendation `standard_review`

**OVERRIDE-CLOSED-02 — Closed Elections** (Priority 99)
- **When:** `STATE_CLOSED` AND `ELECTIONS`
- **Then:** set max 30, set min 20, recommendation `informational_only`

---

### Phase 5: Default

**DEFAULT-001 — Unclassified**
- **When:** label count &lt; 2
- **Then:** add label `UNCATEGORIZED`, set min 30, set max 50, recommendation `standard_review`
- **Priority:** 1

---

## 9) Machine-readable rulebook (YAML)

```yaml
version: 2.5.0
metadata:
  owner: "Participation Architecture"
  created_at: "2026-02-04"
  updated_at: "2026-02-04"
  notes: "Context-aware with intelligent closed-state handling."
  description: "Complete deterministic rule engine with false-positive prevention."

keyword_groups:
  ACTIVE_INCIDENT_CUES: ["active exploit", "under active attack", "funds are being drained", "funds stolen", "emergency pause", "bridge compromised", "critical breach", "post-mortem of incident", "security incident", "active hack"]
  UPGRADE_CUES: ["arbos upgrade", "arbos version", "contract upgrade", "hard fork", "precompile update", "sequencer upgrade", "implement improvements", "pricing algorithm", "voting system", "governance contracts", "adopt", "new policy", "protocol change", "system upgrade"]
  PARAMETER_CUES: ["parameter change", "fee adjustment", "gas target", "base fee", "threshold change", "config update", "technical parameter", "quorum threshold", "min l2 base fee"]
  NEW_PROGRAM_CUES: ["incentive program", "pilot program", "launching a new", "program design", "new initiative", "program establishment", "dip 2.0", "new program", "program creation"]
  TREASURY_CUES: ["budget request", "funding request", "grant request", "allocation request", "payment request", "compensation", "treasury spend", "top-up", "bonus", "stipend", "salary"]
  GOV_FRAMEWORK_CUES: ["constitution", "constitutional", "governance framework", "aip", "bylaws", "dao constitution", "governance structure"]
  ELECTION_CUES: ["election", "nomination", "candidate", "vote for", "reconfirmation", "council seat", "appoint", "voting for"]
  META_GOV_CUES: ["temperature check", "discussion", "rfc", "community feedback", "meta-governance", "request for comments"]
  REPORTING_STRICT_CUES: ["monthly report", "quarterly report", "transparency report", "financial report", "progress update", "milestone report", "status update", "research report"]
  OPS_CUES: ["housekeeping", "administrative", "operational", "renewal", "calendar", "routine", "maintenance"]
  SPONSORSHIP_CUES: ["sponsor", "sponsorship", "partnership", "event support", "hackathon support", "hackathon", "attackathon", "conference", "event sponsor"]

score_mapping:
  urgent_deep_review: {min: 90, max: 100}
  deep_review: {min: 70, max: 89}
  standard_review: {min: 40, max: 69}
  fast_track_ok: {min: 25, max: 39}
  informational_only: {min: 0, max: 24}

treasury_tiers_usd:
  - {min_usd: 10000000, add_priority: 25, set_min_priority: 85, label: "TREASURY_TIER_1"}
  - {min_usd: 1000000, add_priority: 20, set_min_priority: 75, label: "TREASURY_TIER_2"}
  - {min_usd: 100000, add_priority: 15, set_min_priority: 60, label: "TREASURY_TIER_3"}
  - {min_usd: 10000, add_priority: 10, set_min_priority: 45, label: "TREASURY_TIER_4"}
  - {min_usd: 1000, add_priority: 5, set_min_priority: 30, label: "TREASURY_TIER_5"}

time_sensitivity_tiers:
  - {max_hours_remaining: 24, add_priority: 15}
  - {max_hours_remaining: 48, add_priority: 10}
  - {max_hours_remaining: 72, add_priority: 5}

workload_tiers:
  - {min_word_count: 5000, add_priority: 12, label: "VERY_LONG_FORM"}
  - {min_word_count: 3000, add_priority: 8, label: "LONG_FORM"}
  - {min_word_count: 1500, add_priority: 5, label: "MEDIUM_FORM"}
  - {min_word_count: 800, add_priority: 2, label: "STANDARD_FORM"}

conflict_resolution:
  max_priority: "min"
  min_priority: "max"
  labels: "additive"
  flags: "additive"

rules:
  # Phase 0: Context Firewall
  - id: "CTX-001"
    name: "Detect Closed State"
    category: "CONTEXT"
    priority: 10000
    when: {field_in: {field: "state", values: ["closed", "executed", "defeated", "expired"]}}
    then: {set_flag: "STATE_CLOSED"}

  - id: "CTX-002"
    name: "Detect Election Context"
    category: "CONTEXT"
    priority: 9999
    when:
      any:
        - title_contains: {keywords: ["election", "nomination", "reconfirmation", "candidate", "appoint"], min_hits: 1}
        - field_equals: {field: "proposal_kind", value: "election"}
    then: {set_flag: "CONTEXT_ELECTION", add_labels: ["ELECTIONS"]}

  - id: "CTX-003"
    name: "Detect Operational/HR Context"
    category: "CONTEXT"
    priority: 9998
    when: {title_contains: {keywords: ["compensation", "salary", "bonus", "stipend", "pay", "remuneration"], min_hits: 1}}
    then: {set_flag: "CONTEXT_HR", add_labels: ["OPERATIONS", "BUDGET"]}

  - id: "CTX-004"
    name: "Detect Sponsorship Context"
    category: "CONTEXT"
    priority: 9997
    when: {title_contains: {keywords: ["sponsorship", "sponsor", "hackathon", "attackathon", "event"], min_hits: 1}}
    then: {set_flag: "CONTEXT_SPONSORSHIP"}

  # Phase 1: Critical
  - id: "SEC-001-STRICT"
    name: "Active Security Incident"
    category: "SECURITY"
    priority: 1000
    when:
      all:
        - not_flag: "CONTEXT_ELECTION"
        - not_flag: "STATE_CLOSED"
        - not_flag: "CONTEXT_SPONSORSHIP"
        - keyword_group_hits: {group: "ACTIVE_INCIDENT_CUES", gte: 1}
    then: {add_labels: ["INCIDENT", "EMERGENCY"], set_min_priority: 95, set_recommended_handling: "urgent_deep_review"}

  - id: "TECH-001-STRICT"
    name: "Protocol Upgrade"
    category: "TECHNICAL"
    priority: 900
    when:
      all:
        - not_flag: "CONTEXT_HR"
        - not_flag: "CONTEXT_ELECTION"
        - not_flag: "CONTEXT_SPONSORSHIP"
        - keyword_group_hits: {group: "UPGRADE_CUES", gte: 1}
    then: {add_labels: ["PROTOCOL_UPGRADE"], set_min_priority: 80}

  # Phase 2: Standard Classification
  - id: "PROG-001"
    name: "New Program Creation"
    category: "STRATEGY"
    priority: 860
    when:
      all:
        - not_flag: "CONTEXT_HR"
        - any:
            - title_contains: {keywords: ["program", "incentive", "dip"], min_hits: 1}
            - keyword_group_hits: {group: "NEW_PROGRAM_CUES", gte: 1}
    then: {add_labels: ["NEW_PROGRAM", "STRATEGY"], set_min_priority: 70, add_priority: 5}

  - id: "TECH-002"
    name: "Parameter Change"
    category: "TECHNICAL"
    priority: 850
    when:
      all:
        - not_labeled: ["PROTOCOL_UPGRADE"]
        - not_labeled: ["NEW_PROGRAM"]
        - keyword_group_hits: {group: "PARAMETER_CUES", gte: 1}
    then: {add_labels: ["PARAMETER_CHANGE"], set_min_priority: 70, add_priority: 5}

  - id: "TRE-010"
    name: "Treasury Spend"
    category: "TREASURY"
    priority: 800
    when: {field_exists: {field: "requested_amount_usd"}}
    then: {add_labels: ["TREASURY"], apply_treasury_tiers_usd: true}

  - id: "TRE-021"
    name: "Treasury Cues"
    category: "TREASURY"
    priority: 780
    when:
      all:
        - not_labeled: ["TREASURY"]
        - keyword_group_hits: {group: "TREASURY_CUES", gte: 2}
    then: {add_labels: ["TREASURY", "BUDGET_UNCLEAR"], set_min_priority: 45, add_priority: 3}

  - id: "GOV-030"
    name: "Constitutional Change"
    category: "GOVERNANCE"
    priority: 700
    when:
      any:
        - title_contains: {keywords: ["constitutional", "constitution"], min_hits: 1}
        - keyword_group_hits: {group: "GOV_FRAMEWORK_CUES", gte: 2}
    then: {add_labels: ["GOVERNANCE_FRAMEWORK"], set_min_priority: 75, add_priority: 5}

  - id: "META-001"
    name: "Meta Governance"
    category: "META_GOV"
    priority: 600
    when: {keyword_group_hits: {group: "META_GOV_CUES", gte: 1}}
    then: {add_labels: ["META_GOV"], set_max_priority: 50}

  - id: "SPON-001"
    name: "Sponsorship"
    category: "SPONSORSHIP"
    priority: 500
    when:
      any:
        - flag_set: "CONTEXT_SPONSORSHIP"
        - keyword_group_hits: {group: "SPONSORSHIP_CUES", gte: 1}
    then: {add_labels: ["SPONSORSHIP"], set_max_priority: 60}

  - id: "OPS-050"
    name: "Operational"
    category: "OPERATIONS"
    priority: 400
    when:
      all:
        - not_flag: "CONTEXT_HR"
        - keyword_group_hits: {group: "OPS_CUES", gte: 2}
    then: {add_labels: ["OPERATIONS"], set_max_priority: 45}

  - id: "REP-001-STRICT"
    name: "Reporting"
    category: "REPORTING"
    priority: 300
    when:
      all:
        - title_contains: {keywords: ["report", "update", "summary"], min_hits: 1}
        - keyword_group_hits: {group: "REPORTING_STRICT_CUES", gte: 1}
        - not_flag: "CONTEXT_ELECTION"
    then: {add_labels: ["REPORTING"], set_max_priority: 35}

  - id: "RES-001"
    name: "Research"
    category: "RESEARCH"
    priority: 350
    when:
      all:
        - title_contains: {keywords: ["research", "study", "analysis"], min_hits: 1}
        - not_labeled: ["GOVERNANCE_FRAMEWORK"]
        - not_labeled: ["PROTOCOL_UPGRADE"]
    then: {add_labels: ["RESEARCH"], set_min_priority: 25, set_max_priority: 40}

  # Phase 3: Modifiers
  - id: "TIME-MODIFIERS"
    name: "Time Sensitivity"
    category: "TIME_MODIFIER"
    priority: 200
    when: {not_flag: "STATE_CLOSED"}
    then: {apply_time_sensitivity_tiers: true}

  - id: "WORKLOAD-MODIFIERS"
    name: "Content Length"
    category: "WORKLOAD_MODIFIER"
    priority: 150
    when: {always: true}
    then: {apply_workload_tiers: true}

  # Phase 4: State-Based Kill Switch & Exceptions
  - id: "OVERRIDE-CLOSED-CRITICAL"
    name: "Critical Closed Items"
    category: "OVERRIDE"
    priority: 110
    when:
      all:
        - flag_set: "STATE_CLOSED"
        - any:
            - has_label: "TREASURY_TIER_1"
            - has_label: "TREASURY_TIER_2"
        - any:
            - has_label: "PROTOCOL_UPGRADE"
            - has_label: "GOVERNANCE_FRAMEWORK"
    then: {set_max_priority: 85, set_min_priority: 75, set_recommended_handling: "deep_review"}

  - id: "OVERRIDE-CLOSED-HIGH-VALUE"
    name: "High Value Closed"
    category: "OVERRIDE"
    priority: 105
    when:
      all:
        - flag_set: "STATE_CLOSED"
        - any:
            - has_label: "TREASURY_TIER_1"
            - has_label: "TREASURY_TIER_2"
    then: {set_max_priority: 75, set_recommended_handling: "deep_review"}

  - id: "OVERRIDE-CLOSED-CONSTITUTIONAL"
    name: "Constitutional Protocol Closed"
    category: "OVERRIDE"
    priority: 104
    when:
      all:
        - flag_set: "STATE_CLOSED"
        - has_label: "GOVERNANCE_FRAMEWORK"
        - any:
            - has_label: "PROTOCOL_UPGRADE"
            - has_label: "PARAMETER_CHANGE"
            - has_label: "NEW_PROGRAM"
    then: {set_max_priority: 80, set_min_priority: 70, set_recommended_handling: "deep_review"}

  - id: "OVERRIDE-CLOSED-PROTOCOL"
    name: "Protocol Closed"
    category: "OVERRIDE"
    priority: 103
    when:
      all:
        - flag_set: "STATE_CLOSED"
        - has_label: "PROTOCOL_UPGRADE"
    then: {set_max_priority: 75, set_min_priority: 65, set_recommended_handling: "deep_review"}

  - id: "OVERRIDE-CLOSED-NEW-PROGRAM"
    name: "New Program Closed"
    category: "OVERRIDE"
    priority: 102
    when:
      all:
        - flag_set: "STATE_CLOSED"
        - has_label: "NEW_PROGRAM"
    then: {set_max_priority: 70, set_min_priority: 60, set_recommended_handling: "standard_review"}

  - id: "OVERRIDE-CLOSED-01"
    name: "General Closed"
    category: "OVERRIDE"
    priority: 100
    when:
      all:
        - flag_set: "STATE_CLOSED"
        - not_labeled: ["TREASURY_TIER_1"]
        - not_labeled: ["TREASURY_TIER_2"]
        - not_labeled: ["PROTOCOL_UPGRADE"]
        - not_labeled: ["GOVERNANCE_FRAMEWORK"]
        - not_labeled: ["NEW_PROGRAM"]
    then: {set_max_priority: 50, set_recommended_handling: "standard_review"}

  - id: "OVERRIDE-CLOSED-02"
    name: "Closed Elections"
    category: "OVERRIDE"
    priority: 99
    when:
      all:
        - flag_set: "STATE_CLOSED"
        - has_label: "ELECTIONS"
    then: {set_max_priority: 30, set_min_priority: 20, set_recommended_handling: "informational_only"}

  # Phase 5: Default
  - id: "DEFAULT-001"
    name: "Unclassified"
    category: "DEFAULT"
    priority: 1
    when: {label_count: {lt: 2}}
    then: {add_labels: ["UNCATEGORIZED"], set_min_priority: 30, set_max_priority: 50, set_recommended_handling: "standard_review"}