"""
Delegate Fatigue Index (DFI) Engine
====================================
Computes a deterministic, reproducible governance workload score (0-100)
grounded in the theoretical framework of the participation-architecture dissertation.

Theoretical Foundations
-----------------------
The DFI operationalizes two core theoretical constructs:

1. Collective Attention as a Rivalrous Commons (dissertation 2.3.1)
   "Kolektywna uwaga i zdolność do podejmowania decyzji" is explicitly identified
   as a scarce, rivalrous resource in the DAO commons. Volume and concurrency
   components directly measure the depletion rate of this shared resource.

2. Fogg B=MAP: Ability Reduction via Cognitive Load (dissertation 2.2.1)
   "W DAO barierą jest często rozproszenie informacji, niejasne opisy propozycji
   czy brak zwięzłych podsumowań." The reading_time and burstiness components
   operationalize reduced Ability in the behavioral model - more cognitive cost
   means less effective capacity to participate, regardless of motivation.

Component Design
----------------
  Volume       (40%): proposals/7d + proposals/30d, weighted toward recent
  Concurrency  (25%): simultaneously active proposals (parallel decision pressure)
  Burstiness   (20%): this-week spike vs. 4-week rolling average
  Reading Time (10%): avg word count / baseline (proxy for cognitive cost per item)
  Novelty       (5%): novel-domain proposals / total (new patterns cost more)

Formula
-------
  DFI = (0.40×volume + 0.25×concurrency + 0.20×burstiness
         + 0.10×reading_time + 0.05×novelty) × 100

Design Principles
-----------------
- Deterministic: same input always produces same output
- Auditable: response includes all raw metrics and component scores
- Configurable: all weights and reference values in fatigue_config.yaml
- Reproducible: computation is persisted to DB (FatigueSnapshot)
- Ecosystem-level: score reflects shared governance burden (not per-delegate)
  Address parameter is forward-compatible for future per-delegate personalization.
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class FatigueComponents:
    """Individual component scores, each in [0.0, 1.0]."""
    volume: float        # normalized volume load
    concurrency: float   # normalized concurrency pressure
    burstiness: float    # spike magnitude vs. rolling average
    reading_time: float  # normalized cognitive cost per item
    novelty: float       # ratio of novel vs. routine proposals


@dataclass
class FatigueMetrics:
    """Raw metrics used to derive component scores.
    Included in API response for full auditability."""
    proposals_7d: int          # proposals started in last 7 days
    proposals_30d: int         # proposals started in last 30 days
    concurrent_active: int     # proposals where start <= now <= end
    avg_word_count: float      # mean word count across 30d window
    weekly_avg: float          # proposals_30d / 4.33 (4-week rolling avg)
    novelty_ratio: float       # novel proposals / total in 30d window


@dataclass
class FatigueResult:
    """Full output of fatigue computation.
    All fields needed to reproduce the score are included."""
    address: str
    fatigue_score: float           # final DFI score: 0.0 - 100.0
    status: str                    # LOW | MODERATE | HIGH | CRITICAL
    components: FatigueComponents  # per-component scores (0-1)
    metrics: FatigueMetrics        # raw source metrics
    weights: Dict[str, float]      # weights used (from fatigue_config.yaml)
    config_version: str            # config version for reproducibility
    computed_at: datetime          # UTC timestamp of computation


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class FatigueEngine:
    """
    Deterministic Delegate Fatigue Index computation.

    All parameters are loaded from fatigue_config.yaml.
    Pass `now` explicitly in compute() to enable reproducible testing.
    """

    FORMULA = (
        "DFI = (0.40×volume + 0.25×concurrency + 0.20×burstiness "
        "+ 0.10×reading_time + 0.05×novelty) × 100"
    )

    def __init__(self, config_path: str = "fatigue_config.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.version = self.config.get("version", "unknown")
        logger.info(f"FatigueEngine initialized v{self.version}")

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_config(self) -> Dict:
        if not self.config_path.exists():
            logger.warning(
                f"fatigue_config.yaml not found at {self.config_path}, using defaults"
            )
            return self._default_config()
        with open(self.config_path, "r") as f:
            config = yaml.safe_load(f)
        self._validate_weights(config.get("weights", {}))
        return config

    def _default_config(self) -> Dict:
        return {
            "version": "1.0.0",
            "weights": {
                "volume": 0.40,
                "concurrency": 0.25,
                "burstiness": 0.20,
                "reading_time": 0.10,
                "novelty": 0.05,
            },
            "reference_values": {
                "volume_7d": 5,
                "volume_30d": 20,
                "concurrent": 5,
                "reading_words": 3000,
            },
            "thresholds": {"low": 30, "moderate": 70, "high": 85},
            "novel_keywords": [
                "exploit", "hack", "drain", "vulnerability", "hard fork",
                "upgrade", "emergency", "pause", "security council",
                "new program", "pilot", "constitution", "amendment",
            ],
            "routine_keywords": [
                "report", "transparency", "renewal", "housekeeping",
                "maintenance", "salary", "stipend", "compensation",
                "monthly", "quarterly", "routine", "operational",
            ],
        }

    def _validate_weights(self, weights: Dict) -> None:
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(
                f"Fatigue weights sum to {total:.3f}, expected 1.0. "
                "Scores may be outside 0-100 range."
            )

    # ------------------------------------------------------------------
    # Main computation
    # ------------------------------------------------------------------

    def compute(
        self,
        address: str,
        proposals: List[Any],
        now: Optional[datetime] = None,
    ) -> FatigueResult:
        """
        Compute the Delegate Fatigue Index.

        Args:
            address:   Delegate wallet address. Currently used as an identifier
                       for future per-delegate personalization. The score itself
                       is ecosystem-level (shared governance burden).
            proposals: List of Proposal ORM instances from the DB.
                       Should cover at least the last 30 days.
            now:       Reference UTC datetime. Defaults to datetime.now(UTC).
                       Pass explicitly in tests for deterministic results.

        Returns:
            FatigueResult with score, status, components, and raw metrics.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        now_ts = int(now.timestamp())
        weights = self.config["weights"]
        ref = self.config["reference_values"]

        metrics = self._compute_metrics(proposals, now_ts)
        components = self._compute_components(metrics, ref)

        raw = (
            weights["volume"]       * components.volume
            + weights["concurrency"]  * components.concurrency
            + weights["burstiness"]   * components.burstiness
            + weights["reading_time"] * components.reading_time
            + weights["novelty"]      * components.novelty
        )
        fatigue_score = round(min(raw * 100, 100.0), 1)
        status = self._determine_status(fatigue_score)

        logger.info(
            f"FatigueEngine: address={address} score={fatigue_score} "
            f"status={status} proposals_30d={metrics.proposals_30d} "
            f"concurrent={metrics.concurrent_active}"
        )

        return FatigueResult(
            address=address,
            fatigue_score=fatigue_score,
            status=status,
            components=components,
            metrics=metrics,
            weights=weights,
            config_version=self.version,
            computed_at=now,
        )

    # ------------------------------------------------------------------
    # Metrics computation
    # ------------------------------------------------------------------

    def _compute_metrics(self, proposals: List[Any], now_ts: int) -> FatigueMetrics:
        cutoff_7d  = now_ts - (7  * 86_400)
        cutoff_30d = now_ts - (30 * 86_400)

        # Upper bound (start <= now_ts) lets caller pass `now` in the past
        # to compute DFI retrospectively (see endpoint `as_of` parameter).
        proposals_7d  = sum(1 for p in proposals if cutoff_7d  <= (p.start or 0) <= now_ts)
        proposals_30d = sum(1 for p in proposals if cutoff_30d <= (p.start or 0) <= now_ts)

        # Concurrent: proposals where start <= now <= end
        concurrent_active = sum(
            1 for p in proposals
            if (p.start or 0) <= now_ts <= (p.end or 0)
        )

        # Average word count across 30d window
        recent = [p for p in proposals if cutoff_30d <= (p.start or 0) <= now_ts]
        if recent:
            word_counts = [len((p.body or "").split()) for p in recent]
            avg_word_count = sum(word_counts) / len(word_counts)
        else:
            avg_word_count = 0.0

        # 4-week rolling average (proposals_30d / 4.33 weeks)
        weekly_avg = proposals_30d / 4.33

        novelty_ratio = self._compute_novelty_ratio(recent)

        return FatigueMetrics(
            proposals_7d=proposals_7d,
            proposals_30d=proposals_30d,
            concurrent_active=concurrent_active,
            avg_word_count=round(avg_word_count, 1),
            weekly_avg=round(weekly_avg, 2),
            novelty_ratio=round(novelty_ratio, 3),
        )

    def _compute_novelty_ratio(self, proposals: List[Any]) -> float:
        """
        Proportion of recent proposals classified as novel (not routine).

        Novel = contains at least one novel keyword AND no routine keywords.
        This proxies the extra cognitive cost of processing genuinely new
        governance domains vs. familiar, repeating patterns.
        """
        if not proposals:
            return 0.0

        novel_kw   = [k.lower() for k in self.config.get("novel_keywords", [])]
        routine_kw = [k.lower() for k in self.config.get("routine_keywords", [])]

        novel_count = 0
        for p in proposals:
            text = ((p.title or "") + " " + (p.body or "")).lower()
            has_novel   = any(kw in text for kw in novel_kw)
            has_routine = any(kw in text for kw in routine_kw)
            if has_novel and not has_routine:
                novel_count += 1

        return novel_count / len(proposals)

    # ------------------------------------------------------------------
    # Component score normalization
    # ------------------------------------------------------------------

    def _compute_components(
        self, metrics: FatigueMetrics, ref: Dict
    ) -> FatigueComponents:
        """
        Normalize raw metrics into [0.0, 1.0] component scores.

        Each component is designed to return 0.5 at the reference value
        and approach 1.0 at 2× the reference (capped there).
        """
        ref_7d         = max(ref.get("volume_7d", 5), 1)
        ref_30d        = max(ref.get("volume_30d", 20), 1)
        ref_concurrent = max(ref.get("concurrent", 5), 1)
        ref_words      = max(ref.get("reading_words", 3000), 1)

        # Volume: weighted average of normalized 7d and 30d rates
        # Recent week weighted 60%, monthly context 40%
        v7  = min(metrics.proposals_7d  / ref_7d,  2.0) / 2.0
        v30 = min(metrics.proposals_30d / ref_30d, 2.0) / 2.0
        volume = 0.6 * v7 + 0.4 * v30

        # Concurrency: normalize against reference concurrent count
        concurrency = min(metrics.concurrent_active / ref_concurrent, 2.0) / 2.0

        # Burstiness: how much this week exceeds the rolling weekly average
        # Score = 0 when at or below average, 1 when 3× the average (2 std above)
        if metrics.weekly_avg > 0:
            burst_ratio = metrics.proposals_7d / metrics.weekly_avg
        else:
            burst_ratio = 1.0 if metrics.proposals_7d > 0 else 0.0
        burstiness = min(max(burst_ratio - 1.0, 0.0) / 2.0, 1.0)

        # Reading time: normalize average word count
        reading_time = min(metrics.avg_word_count / ref_words, 2.0) / 2.0

        # Novelty: directly a ratio in [0, 1]
        novelty = metrics.novelty_ratio

        return FatigueComponents(
            volume=round(min(volume, 1.0), 4),
            concurrency=round(min(concurrency, 1.0), 4),
            burstiness=round(min(burstiness, 1.0), 4),
            reading_time=round(min(reading_time, 1.0), 4),
            novelty=round(novelty, 4),
        )

    # ------------------------------------------------------------------
    # Status mapping
    # ------------------------------------------------------------------

    def _determine_status(self, score: float) -> str:
        t = self.config.get("thresholds", {})
        if score < t.get("low", 30):
            return "LOW"
        elif score < t.get("moderate", 70):
            return "MODERATE"
        elif score < t.get("high", 85):
            return "HIGH"
        return "CRITICAL"

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_config_info(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "formula": self.FORMULA,
            "weights": self.config["weights"],
            "reference_values": self.config["reference_values"],
            "thresholds": self.config["thresholds"],
        }
