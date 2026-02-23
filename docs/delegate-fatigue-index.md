# Delegate Fatigue Index (DFI)

The Delegate Fatigue Index is a deterministic, reproducible score (0-100) measuring the cognitive workload that current governance activity imposes on DAO delegates.

---

## Why it exists

DAO governance suffers from **attention overload**: too many proposals, arriving too fast, with too little prioritization support. This causes:

- Delegates voting on more proposals than they can meaningfully analyze
- Participation quality declining as volume increases
- Burnout and eventual disengagement from governance

The DFI operationalizes this problem as a **measurable, auditable signal** that governance tools can use to triage workload and schedule reviews.

### Theoretical grounding

The DFI is grounded in two frameworks from the participation-architecture dissertation:

**1. Collective attention as a rivalrous commons (dissertation 2.3.1)**

"Kolektywna uwaga i zdolnosc do podejmowania decyzji" is explicitly identified as a scarce, rivalrous resource in DAO governance. Like a shared fishery, collective attention has a sustainable yield - exceeding it degrades quality for everyone. The `volume` and `concurrency` components directly measure the depletion rate of this shared resource.

**2. Fogg B=MAP: Ability reduction via cognitive load (dissertation 2.2.1)**

In the Fogg Behavioral Model, Behavior = Motivation x Ability x Prompt. For DAO governance, the barrier is often reduced **Ability** - information fragmentation, unclear proposal descriptions, simultaneous decision pressure. The DFI operationalizes Ability reduction:
- `reading_time` proxies per-item cognitive cost
- `burstiness` measures habit disruption (irregular spikes prevent stable participation routines)
- `novelty` captures the extra processing cost of novel vs. routine governance domains (Cognitive Load Theory, dissertation 1.4)

---

## Formula

```
DFI = (0.40 x volume
     + 0.25 x concurrency
     + 0.20 x burstiness
     + 0.10 x reading_time
     + 0.05 x novelty) x 100
```

Each component is a normalized value in **[0.0, 1.0]**. The formula is returned in every API response in the `formula` field.

---

## Components

### Volume (40%)

Measures total proposal load over recent time windows.

**Metric sources:**
- `proposals_7d` - proposals started in the last 7 days
- `proposals_30d` - proposals started in the last 30 days

**Normalization:**
```
v7  = min(proposals_7d  / ref_7d,  2.0) / 2.0
v30 = min(proposals_30d / ref_30d, 2.0) / 2.0
volume = 0.6 x v7 + 0.4 x v30
```

The recent week is weighted 60% vs. monthly context 40%, because recent overload matters more than historical average.

**Reference values** (from `fatigue_config.yaml`):
- `volume_7d`: 5 proposals/week = reference load
- `volume_30d`: 20 proposals/month = reference load

At the reference level, `volume = 0.5`. At 2x reference, `volume = 1.0` (capped).

---

### Concurrency (25%)

Measures simultaneous active proposals - the parallel decision pressure at any given moment.

**Metric:** `concurrent_active` - proposals where `start <= now <= end`

**Normalization:**
```
concurrency = min(concurrent_active / ref_concurrent, 2.0) / 2.0
```

**Reference value:** `concurrent: 5` simultaneous proposals.

High concurrency forces delegates to split attention across multiple votes in parallel, which is more cognitively costly than sequential review.

---

### Burstiness (20%)

Measures how much this week's volume spikes above the rolling 4-week average. Irregular spikes disrupt stable participation habits.

**Metrics:**
- `proposals_7d` - this week's count
- `weekly_avg` = `proposals_30d / 4.33` - rolling weekly baseline

**Normalization:**
```
burst_ratio = proposals_7d / weekly_avg
burstiness  = min(max(burst_ratio - 1.0, 0.0) / 2.0, 1.0)
```

- `burstiness = 0.0` when at or below the rolling average
- `burstiness = 0.5` when 2x the rolling average
- `burstiness = 1.0` when 3x the rolling average

---

### Reading Time (10%)

Proxies the cognitive cost per proposal based on word count. Longer proposals require more time and effort to analyze.

**Metric:** `avg_word_count` - mean word count across the 30-day window

**Normalization:**
```
reading_time = min(avg_word_count / ref_reading_words, 2.0) / 2.0
```

**Reference value:** `reading_words: 3000` words = reference cost (about 10-15 minutes of careful reading).

---

### Novelty (5%)

Proxies the extra cognitive cost of processing genuinely novel governance domains vs. familiar routine patterns. New governance areas require more research and contextual understanding.

**Classification:**
- **Novel**: contains at least one novel keyword AND no routine keywords
- **Routine**: contains at least one routine keyword (regardless of novel keywords)

**Novel keywords:** `exploit`, `hack`, `drain`, `vulnerability`, `hard fork`, `upgrade`, `emergency`, `pause`, `security council`, `new program`, `pilot`, `constitution`, `amendment`

**Routine keywords:** `report`, `transparency`, `renewal`, `housekeeping`, `maintenance`, `salary`, `stipend`, `compensation`, `monthly`, `quarterly`, `routine`, `operational`

**Metric:** `novelty_ratio` = `novel_proposals / total_proposals_30d`

This is used directly as the component score (no additional normalization needed; it's already in [0, 1]).

---

## Status thresholds

| Status | Score | Interpretation | Suggested action |
|---|---|---|---|
| `LOW` | < 30 | Healthy load, normal participation | All proposal types manageable |
| `MODERATE` | 30-69 | Elevated but manageable | Focus on `deep_review` items first |
| `HIGH` | 70-84 | Significant workload | Prioritize triage; fast-track routines |
| `CRITICAL` | >= 85 | Overload risk | Consider batching proposals or extending voting periods |

---

## Ecosystem-level score

The DFI reflects **shared governance burden** - the same score applies to all delegates because collective attention is a shared resource. One delegate's review capacity being consumed by a wave of proposals reduces the quality of governance for all.

The `address` parameter in the API is **forward-compatible** for future per-delegate personalization (e.g., adjusting for a delegate's stated focus areas or historical participation patterns). In the current implementation, the score is identical for all addresses given the same governance state.

---

## Reproducibility

Every DFI computation is **persisted to the `fatigue_snapshots` table** in SQLite. This supports:

1. **Audit trail** - you can verify any historical score by fetching `/delegates/{address}/fatigue/history`
2. **Research reproducibility** - the exact formula, weights, and raw metrics are stored alongside each score
3. **Config versioning** - `config_version` in each snapshot tracks which `fatigue_config.yaml` version was used

---

## Configuration

All parameters live in `fatigue_config.yaml`:

```yaml
version: "1.0.0"

weights:
  volume: 0.40
  concurrency: 0.25
  burstiness: 0.20
  reading_time: 0.10
  novelty: 0.05

reference_values:
  volume_7d: 5        # proposals/week considered "normal"
  volume_30d: 20      # proposals/month considered "normal"
  concurrent: 5       # simultaneous proposals considered "normal"
  reading_words: 3000 # word count considered "reference cost"

thresholds:
  low: 30
  moderate: 70
  high: 85

novel_keywords:
  - exploit
  - hack
  - drain
  - ...

routine_keywords:
  - report
  - transparency
  - ...
```

**Changing weights:** Edit `fatigue_config.yaml`. Weights must sum to 1.0 (the engine logs a warning if they don't). Restart the API server to reload. Use `GET /debug/fatigue-config` to verify the loaded configuration.

**Important:** Changing weights changes scores. If you change them in production, existing `fatigue_snapshots` rows were computed with the old weights - the `config_version` field tracks this.
