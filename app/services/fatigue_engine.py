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

import hashlib
import json
import os
import re
import subprocess
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Instrument state
# ---------------------------------------------------------------------------

class InstrumentInvalid(RuntimeError):
    """The frozen confirmatory instrument cannot be loaded as declared.

    Closure review (/t/30604, 2026-09-03, point 6): a missing or invalid
    fatigue_config.yaml must produce INSTRUMENT_INVALID, not a different
    computation that still calls itself DFI. Until 2026-09-04 the engine fell
    back to built-in defaults with a warning - acceptable for an exploratory
    app, not for an instrument whose reference values are frozen for N=50."""

    code = "INSTRUMENT_INVALID"


# ---------------------------------------------------------------------------
# Source capability receipts (closure review point 2)
# ---------------------------------------------------------------------------

# A count cannot prove source health: a healthy source with zero events, a
# timeout, an HTTP failure, a GraphQL error and a missing API key all used to
# collapse into `0`. Every source now returns one of these explicit states.
HEALTHY_COMPLETE = "HEALTHY_COMPLETE"   # answered, nothing cut off
HEALTHY_EMPTY = "HEALTHY_EMPTY"         # answered, genuinely nothing there
PARTIAL = "PARTIAL"                     # answered, some records lack a field the
                                        # instrument needs (e.g. voting window)
TRUNCATED = "TRUNCATED"                 # answered, hit a page/scan limit - the
                                        # set may be incomplete
UNAVAILABLE = "UNAVAILABLE"             # transport failure: timeout, DNS, RPC down
AUTH_MISSING = "AUTH_MISSING"           # no key/capability to ask at all
ERROR = "ERROR"                         # the source answered with an error
                                        # (HTTP 4xx/5xx, GraphQL errors)
SOURCE_STATES = (HEALTHY_COMPLETE, HEALTHY_EMPTY, PARTIAL, TRUNCATED,
                 UNAVAILABLE, AUTH_MISSING, ERROR)

ELIGIBLE = "PRIMARY_ELIGIBLE"
NOT_ELIGIBLE = "NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS"


@dataclass
class SourceReceipt:
    """What one source could and could not deliver for THIS measurement."""
    source: str                       # snapshot | tally | governor | ecosystem
    state: str                        # one of SOURCE_STATES
    events: int = 0                   # records delivered
    detail: str = ""                  # human-readable cause (error text, limit)
    unknown_window: int = 0           # records without a usable voting window
    limit: Optional[int] = None       # page/scan limit the query ran with

    def __post_init__(self) -> None:
        if self.state not in SOURCE_STATES:
            raise ValueError(f"unknown source state {self.state!r}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
    # Separation required by the grant review (point 3, /t/30604 post 18):
    # ecosystem governance load vs the delegate's revealed engagement.
    # concurrency_source names what concurrent_active was counted from -
    # "ecosystem:snapshot" (all proposals open in the space at t, Snapshot
    # layer) or "voted_only" (only proposals this delegate voted on; the
    # pre-2026-08-28 construction, kept as the explicit fallback when the
    # ecosystem source is unavailable). voted_concurrent always carries the
    # revealed-engagement count, whichever source drove the component.
    concurrency_source: str = "voted_only"
    voted_concurrent: int = 0


@dataclass
class MeasurementIdentity:
    """What binds one per-event result to the exact circumstances it was
    computed under (grant review point 4, /t/30604 post 18): the unique
    vote-event - not only the proposal id - plus instrument version, code
    commit, and the source-capability state including unknown windows.

    vote_event_id is a deterministic digest of (address, THIS stage's id, vote
    timestamp). Since the closure review (2026-09-03, point 1) the identity
    names ONE concrete vote - the task the NASA-TLX rating belongs to. Other
    stages of the same decision are linked through lifecycle_id and listed in
    lifecycle_stage_ids; they never enter this vote's identity or its
    computation. Two results with the same id measured the same event; a
    re-run after a source or instrument change keeps the same id and differs
    in instrument_hash/code_commit/receipts - which is the point: the registry
    can tell WHAT changed between two numbers.

    measurement_id is the digest of the COMPLETE identity (vote-event +
    instrument + code + every input set): persistence is idempotent on it
    (closure review point 5)."""
    vote_event_id: str
    stage_ids: List[str]           # THIS vote's stage id (one element)
    voted_at: int                  # vote timestamp bound into the identity
    instrument_version: str        # fatigue_config.yaml version
    code_commit: str               # git HEAD at compute time, or "unknown"
    source_state: Dict[str, Any]   # sources + history_events +
                                   # events_unknown_window + concurrency_source
    # --- complete, reconstructable manifest (closure review point 4) ---
    lifecycle_id: str = ""                       # DecisionLifecycleId
    lifecycle_stage_ids: List[str] = field(default_factory=list)
    source_vote_id: str = ""                     # native id from the source
    source_domain: str = ""                      # snapshot | tally | governor:*
    native_proposal_id: str = ""                 # proposal id as the source knows it
    target_content_hash: str = ""                # sha256 of title + body rated
    context_stage_ids: List[str] = field(default_factory=list)
    context_set_hash: str = ""                   # sha256 over context_stage_ids
    ecosystem_ids: List[str] = field(default_factory=list)
    ecosystem_set_hash: str = ""                 # sha256 over ecosystem_ids
    source_receipts: List[Dict[str, Any]] = field(default_factory=list)
    instrument_hash: str = ""                    # sha256 of fatigue_config.yaml bytes
    eligibility: str = ELIGIBLE                  # PRIMARY_ELIGIBLE | NOT_ELIGIBLE_...
    eligibility_reasons: List[str] = field(default_factory=list)
    measurement_id: str = ""                     # digest of the whole manifest

    def manifest(self) -> Dict[str, Any]:
        """The manifest as persisted: everything needed to reconstruct what
        was measured, without re-running anything."""
        return asdict(self)


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
    mode: str = "ecosystem"        # "ecosystem" (shared burden) | "per_delegate" (revealed activity)
    identity: Optional[MeasurementIdentity] = None  # per-event only (review point 4)


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

    # Every key the frozen instrument needs. A config missing any of them is
    # INSTRUMENT_INVALID - not "close enough".
    REQUIRED_WEIGHTS = ("volume", "concurrency", "burstiness", "reading_time", "novelty")
    REQUIRED_REFERENCES = ("volume_7d", "volume_30d", "concurrent", "reading_words")
    REQUIRED_THRESHOLDS = ("low", "moderate", "high")

    def __init__(self, config_path: str = "fatigue_config.yaml"):
        self.config_path = Path(config_path)
        self.config, self.instrument_hash = self._load_config()
        self.version = str(self.config["version"])
        self.code_commit = self._read_code_commit()
        logger.info(f"FatigueEngine initialized v{self.version} "
                    f"instrument={self.instrument_hash[:12]}")

    @staticmethod
    def _read_code_commit() -> str:
        """Git HEAD of the running code, for the measurement identity (review
        point 4). Containers built without .git fall back to the GIT_COMMIT
        env var; when neither answers, the honest value is "unknown" - a
        missing capability is reported, never guessed."""
        env = os.environ.get("GIT_COMMIT")
        if env:
            return env.strip()
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path(__file__).resolve().parent,
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:  # noqa: BLE001
            pass
        return "unknown"

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_config(self) -> Tuple[Dict, str]:
        """Load and VALIDATE the instrument. Fails closed (closure review
        point 6): no file, unreadable YAML, missing keys or weights that do not
        sum to 1.0 raise InstrumentInvalid instead of degrading to defaults.

        Returns (config, instrument_hash) - the hash is sha256 of the file's
        bytes, so two measurements made on byte-identical configs share it and
        any edit, including a comment, produces a new one. That is deliberate:
        the manifest must say which file was in force, not which values."""
        if not self.config_path.exists():
            raise InstrumentInvalid(
                f"INSTRUMENT_INVALID: {self.config_path} not found - refusing to "
                "compute DFI on built-in defaults"
            )
        raw = self.config_path.read_bytes()
        try:
            config = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            raise InstrumentInvalid(f"INSTRUMENT_INVALID: {self.config_path} is not "
                                    f"valid YAML: {e}") from e
        problems = self.validate_config(config)
        if problems:
            raise InstrumentInvalid("INSTRUMENT_INVALID: " + "; ".join(problems))
        return config, hashlib.sha256(raw).hexdigest()

    @classmethod
    def validate_config(cls, config: Any) -> List[str]:
        """Every defect found, as text. Empty list = valid instrument."""
        problems: List[str] = []
        if not isinstance(config, dict):
            return ["config is not a mapping"]
        if not config.get("version"):
            problems.append("missing version")
        weights = config.get("weights")
        if not isinstance(weights, dict):
            problems.append("missing weights")
        else:
            for k in cls.REQUIRED_WEIGHTS:
                if not isinstance(weights.get(k), (int, float)) or isinstance(weights.get(k), bool):
                    problems.append(f"weight {k} missing or not numeric")
            if not problems:
                total = sum(float(weights[k]) for k in cls.REQUIRED_WEIGHTS)
                if abs(total - 1.0) > 0.01:
                    problems.append(f"weights sum to {total:.3f}, expected 1.0")
        for section in ("reference_values", "reference_values_per_event"):
            ref = config.get(section)
            if not isinstance(ref, dict):
                problems.append(f"missing {section}")
                continue
            for k in cls.REQUIRED_REFERENCES:
                v = ref.get(k)
                if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                    problems.append(f"{section}.{k} missing or not a positive number")
        thr = config.get("thresholds")
        if not isinstance(thr, dict):
            problems.append("missing thresholds")
        else:
            for k in cls.REQUIRED_THRESHOLDS:
                if not isinstance(thr.get(k), (int, float)) or isinstance(thr.get(k), bool):
                    problems.append(f"threshold {k} missing or not numeric")
        return problems

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

        fatigue_score = self._aggregate_score(components, weights)
        status = self._determine_status(fatigue_score)

        logger.info(
            f"FatigueEngine[ecosystem]: address={address} score={fatigue_score} "
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
            mode="ecosystem",
        )

    def compute_per_event(
        self,
        address: str,
        target_proposal: Any,
        voted_history: List[Any],
        now: Optional[datetime] = None,
        ecosystem_proposals: Optional[List[Any]] = None,
        source_counts: Optional[Dict[str, int]] = None,
        source_receipts: Optional[List[SourceReceipt]] = None,
        reconciliations: Optional[List[Dict[str, str]]] = None,
    ) -> FatigueResult:
        """
        Per-event Delegate Fatigue Index (dissertation 5.3.5a; per-event pivot
        2026-05-11).

        The unit of analysis is a SINGLE vote, not a 30-day aggregate. NASA-TLX
        is task-specific and validated only up to ~24h (Hernandez 2021), so the
        survey rates one concrete vote and DFI is matched to it via
        as_of = vote timestamp (`now`). Grounded in Cognitive Load Theory
        (Sweller 1988; Klepsch et al. 2017):

          - reading_time, novelty : INTRINSIC load of THE voted proposal
            (its length and whether it is a novel governance domain). This is
            the main source of between-event variance (proposal length on
            Arbitrum ranges ~150-6000 words).
          - volume, concurrency, burstiness : EXTRANEOUS/context load - how
            much the delegate had on their plate around the vote, computed from
            their voting history in the window ending at `now`.

        Args:
            address:         Delegate wallet address.
            target_proposal: The proposal the vote (and the NASA-TLX rating)
                             refers to. Needs .body / .title.
            voted_history:   Proposals the delegate voted on up to `now`
                             (e.g. from Snapshot `votes`). Drives the context
                             components. Should cover >=30 days before `now`.
            now:             Vote timestamp (as_of). Defaults to now(UTC).
                             Pass explicitly in tests for deterministic results.
            ecosystem_proposals:
                             ALL proposals of the space whose voting window may
                             cover `now` - not just the ones this delegate voted
                             on. When given (an empty list is a real answer:
                             nothing was open), concurrency measures ECOSYSTEM
                             governance load, per point 3 of the grant review
                             (/t/30604 post 18). When None, the source is
                             unavailable and concurrency falls back to the
                             delegate's own voted proposals - the result then
                             says so in metrics.concurrency_source instead of
                             passing the narrower number off as ecosystem load.
            source_receipts: One SourceReceipt per source consulted (closure
                             review point 2). Decides eligibility: a required
                             source outside the eligible states, or the
                             voted_only concurrency fallback, marks the result
                             NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS. None (offline
                             use, tests) is itself a reason: without receipts
                             nothing proves the inputs were complete.
            reconciliations: What reconcile_observations merged, for the manifest.

        Unit of analysis (closure review point 1): ONE concrete vote. Stages of
        the same decision found in voted_history are counted as one decision in
        the volume/burstiness windows (at the moment of the FIRST stage, where
        the reading happened) but no stage lends anything to another: the
        target's body, category and timestamp are its own.

        Returns:
            FatigueResult with mode="per_event".

        Limitations (dissertation 5.3.5a): vote activity is endogenous (both
        exposure and a possible response to load); off-vote reading and
        forum/Discord load are not captured; Snapshot data is off-chain. See 6.5.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        now_ts = int(now.timestamp())
        weights = self.config["weights"]
        ref = self.config.get(
            "reference_values_per_event", self.config["reference_values"]
        )

        # Freeze the evidence set at the target vote before anything is counted.
        # A proposal may open before the target vote and be voted on days after
        # it; without this filter that later vote would enter the target's
        # history and the historical DFI would depend on information that did
        # not exist at the declared as_of boundary.
        frozen_history = [p for p in voted_history if self._vote_ts(p) <= now_ts]

        # One decision = one workload event. Stages of a lifecycle collapse to
        # the EARLIEST frozen stage for counting only - a view over immutable
        # observations, not a merged object (closure review point 1).
        decisions = self._decision_representatives(frozen_history)

        # Context components from the delegate's history around the vote.
        ctx = self._compute_metrics(decisions, now_ts, by_vote_time=True)

        # Separation of the two quantities (grant review point 3): what the
        # delegate's own votes show at t is REVEALED ENGAGEMENT and is always
        # kept; ECOSYSTEM LOAD replaces it as the concurrency driver whenever
        # the space-wide proposal list is available. The same unknown-window
        # rule applies: a proposal without `end` is skipped, not counted.
        voted_concurrent = ctx.concurrent_active
        if ecosystem_proposals is not None:
            ctx.concurrent_active = sum(
                1 for p in ecosystem_proposals
                if getattr(p, "end", None) and (p.start or 0) <= now_ts <= p.end
            )
            concurrency_source = "ecosystem:snapshot"
        else:
            concurrency_source = "voted_only"

        ctx_components = self._compute_components(ctx, ref)

        # Intrinsic components from THE voted proposal (per-event).
        ref_words = max(ref.get("reading_words", 1500), 1)
        words = len((getattr(target_proposal, "body", None) or "").split())
        reading_time = round(min(min(words / ref_words, 2.0) / 2.0, 1.0), 4)
        novelty = round(self._novelty_per_event(target_proposal, frozen_history), 4)

        components = FatigueComponents(
            volume=ctx_components.volume,
            concurrency=ctx_components.concurrency,
            burstiness=ctx_components.burstiness,
            reading_time=reading_time,
            novelty=novelty,
        )

        fatigue_score = self._aggregate_score(components, weights)
        status = self._determine_status(fatigue_score)

        # Measurement identity (review point 4): THIS vote-event - its own
        # stage id plus the vote timestamp - bound to the instrument, the code
        # commit and the source-capability receipts. Other stages of the same
        # decision are linked, never bound.
        own_id = _stage_id(target_proposal)
        if not own_id:
            # A source that carries no event id must not collapse two different
            # events into one identity - fall back to the decision key + start,
            # both deterministic properties of the proposal itself.
            own_id = (f"~{_klucz_decyzji(target_proposal)}"
                      f"@{getattr(target_proposal, 'start', 0) or 0}")
        stage_ids = [own_id]
        identity_raw = f"{address.lower()}|{own_id}|{now_ts}"
        vote_event_id = hashlib.sha256(identity_raw.encode()).hexdigest()[:16]

        receipts = [r.to_dict() if isinstance(r, SourceReceipt) else dict(r)
                    for r in (source_receipts or [])]
        eligibility, reasons = self._eligibility(receipts, concurrency_source)

        title = getattr(target_proposal, "title", None) or ""
        body = getattr(target_proposal, "body", None) or ""
        context_ids = sorted(_stage_id(p) or f"~{_klucz_decyzji(p)}@{getattr(p, 'start', 0) or 0}"
                             for p in frozen_history)
        ecosystem_ids = (sorted(str(getattr(p, "id", "") or "") for p in ecosystem_proposals)
                         if ecosystem_proposals is not None else [])
        manifest_core = {
            "vote_event_id": vote_event_id,
            "instrument_hash": self.instrument_hash,
            "instrument_version": self.version,
            "code_commit": self.code_commit,
            "target_content_hash": _sha(title + "\n" + body),
            "context_set_hash": _sha("|".join(context_ids)),
            "ecosystem_set_hash": (_sha("|".join(ecosystem_ids))
                                   if ecosystem_proposals is not None else ""),
            "receipts_hash": _sha(json.dumps(receipts, sort_keys=True)),
            "eligibility": eligibility,
        }
        identity = MeasurementIdentity(
            vote_event_id=vote_event_id,
            stage_ids=stage_ids,
            voted_at=now_ts,
            instrument_version=self.version,
            code_commit=self.code_commit,
            source_state={
                "sources": source_counts or {},
                "history_events": len(frozen_history),
                "history_decisions": len(decisions),
                "events_unknown_window": sum(
                    1 for p in frozen_history if not getattr(p, "end", None)),
                "concurrency_source": concurrency_source,
                "reconciliations": list(reconciliations or []),
            },
            lifecycle_id=str(getattr(target_proposal, "lifecycle_id", "") or ""),
            lifecycle_stage_ids=[str(s) for s in
                                 (getattr(target_proposal, "lifecycle_stage_ids", None) or stage_ids)],
            source_vote_id=str(getattr(target_proposal, "source_vote_id", "") or ""),
            source_domain=str(getattr(target_proposal, "source_domain", "")
                              or getattr(target_proposal, "source", "") or ""),
            native_proposal_id=str(getattr(target_proposal, "native_proposal_id", "") or ""),
            target_content_hash=manifest_core["target_content_hash"],
            context_stage_ids=context_ids,
            context_set_hash=manifest_core["context_set_hash"],
            ecosystem_ids=ecosystem_ids,
            ecosystem_set_hash=manifest_core["ecosystem_set_hash"],
            source_receipts=receipts,
            instrument_hash=self.instrument_hash,
            eligibility=eligibility,
            eligibility_reasons=reasons,
            measurement_id=_sha(json.dumps(manifest_core, sort_keys=True))[:32],
        )

        # Metrics reflect the per-event view: context counts + THIS proposal's length.
        metrics = FatigueMetrics(
            proposals_7d=ctx.proposals_7d,
            proposals_30d=ctx.proposals_30d,
            concurrent_active=ctx.concurrent_active,
            avg_word_count=float(words),
            weekly_avg=ctx.weekly_avg,
            novelty_ratio=novelty,
            concurrency_source=concurrency_source,
            voted_concurrent=voted_concurrent,
        )

        logger.info(
            f"FatigueEngine[per_event]: address={address} score={fatigue_score} "
            f"status={status} words={words} ctx_voted_30d={ctx.proposals_30d} "
            f"concurrent={ctx.concurrent_active}"
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
            mode="per_event",
            identity=identity,
        )

    @staticmethod
    def _decision_representatives(history: List[Any]) -> List[Any]:
        """One observation per decision lifecycle: the earliest frozen stage.
        Observations without a lifecycle are their own decision."""
        pierwsze: Dict[str, Any] = {}
        for p in history:
            k = _lifecycle_key(p)
            if k not in pierwsze or FatigueEngine._vote_ts(p) < FatigueEngine._vote_ts(pierwsze[k]):
                pierwsze[k] = p
        return list(pierwsze.values())

    def _eligibility(self, receipts: List[Dict[str, Any]],
                     concurrency_source: str) -> Tuple[str, List[str]]:
        """Fail closed (closure review points 2 and 6): a confirmatory
        measurement is PRIMARY_ELIGIBLE only when every required source
        answered in an eligible state and concurrency was measured on the
        construct the instrument declares (ecosystem exposure). Rules live in
        fatigue_config.yaml#eligibility; this method only applies them."""
        rules = self.config.get("eligibility") or {}
        required = list(rules.get("required_sources") or [])
        ok_states = set(rules.get("eligible_states") or [HEALTHY_COMPLETE, HEALTHY_EMPTY])
        reasons: List[str] = []
        if not receipts:
            reasons.append("no source receipts supplied - completeness of inputs unproven")
        by_source = {r.get("source"): r for r in receipts}
        for name in required:
            r = by_source.get(name)
            if r is None:
                reasons.append(f"required source {name}: no receipt")
            elif r.get("state") not in ok_states:
                reasons.append(f"required source {name}: {r.get('state')}"
                               + (f" ({r.get('detail')})" if r.get("detail") else ""))
        if concurrency_source != "ecosystem:snapshot":
            reasons.append(f"concurrency measured as {concurrency_source}, not ecosystem "
                           "exposure - a different construct than the frozen instrument")
        return (ELIGIBLE if not reasons else NOT_ELIGIBLE), reasons

    def _novelty_per_event(self, target: Any, history: List[Any]) -> float:
        """Na ile ten RODZAJ decyzji jest nowy DLA TEGO delegata.

        Do 2026-08-05 składnik pytał o właściwość samej propozycji: czy w tytule
        albo treści stoi słowo z naszej listy „nowych domen". Wychodziło 0,0
        u wszystkich trzech uczestników Phase A, więc składnik nie różnicował
        nikogo - a przy wadze 5% nikt tego nie zauważył.

        Dwa powody zmiany. Po pierwsze, teoria: obciążenie poznawcze przy nowości
        jest z definicji względne wobec doświadczenia osoby (CLT, Sweller 1988) -
        propozycja o awarii jest nowa dla kogoś, kto pierwszy raz się z tym mierzy,
        i rutynowa dla kogoś, kto przerabiał to pięć razy. Lista słów mierzyła
        cechę tekstu, nie stan czytającego.

        Po drugie, dane: DAO utrzymuje własną taksonomię propozycji (12 kategorii,
        `arbdata`), wskazaną przez uczestnika badania jako źródło używane przez
        społeczność. Klasyfikacja, którą prowadzi teren, broni się lepiej niż
        słowa, które sami wybraliśmy - i sami przyznaliśmy, że nie działają.

        Wynik: udział głosów TEGO delegata w TEJ kategorii wśród jego głosów
        wcześniejszych, odjęty od jedynki. Pierwsze zetknięcie z kategorią daje
        1,0, kategoria stanowiąca całość jego dorobku daje 0,0.

        Bez znanej kategorii wracamy do dopasowania po słowach. Zamiana braku
        klasyfikacji na zero byłaby twierdzeniem, że decyzja jest rutynowa - a to
        inna rzecz niż „nie wiemy".
        """
        kat = (getattr(target, "category", None) or "").strip().lower()
        if kat:
            # Own lifecycle excluded (closure review 2026-09-03, found while
            # separating stages): the endpoint hands the target inside its own
            # history, so until 2026-09-04 a delegate's FIRST vote in a category
            # scored 1 - 1/1 = 0.0 - "routine" - instead of 1.0. The component
            # could only reach its ceiling through the keyword fallback.
            wlasny = _lifecycle_key(target)
            # Jedna decyzja = jedno wcześniejsze zetknięcie. Kategoria cyklu to
            # pierwsza znana wśród jego ZAMROŻONYCH etapów (wszystkie <= now,
            # więc to informacja, która w chwili głosu istniała).
            kategorie_cykli: Dict[str, str] = {}
            for p in history:
                k = _lifecycle_key(p)
                if k == wlasny:
                    continue
                c = (getattr(p, "category", None) or "").strip().lower()
                if c and not kategorie_cykli.get(k):
                    kategorie_cykli[k] = c
                else:
                    kategorie_cykli.setdefault(k, "")
            wczesniej = [c for c in kategorie_cykli.values() if c]
            if wczesniej:
                w_tej = sum(1 for c in wczesniej if c == kat)
                return 1.0 - min(w_tej / len(wczesniej), 1.0)
            return 1.0  # brak historii z kategoriami = wszystko jest nowe
        return self._proposal_is_novel(target)

    def _proposal_is_novel(self, proposal: Any) -> float:
        """
        Zapas, gdy kategoria nieznana: 1.0 gdy tytuł albo treść zawiera słowo
        z listy nowych domen i żadnego z listy rutynowych, inaczej 0.0.
        Ta sama logika co w wariancie ekosystemowym, zastosowana do jednej pozycji.
        """
        novel_kw = [k.lower() for k in self.config.get("novel_keywords", [])]
        routine_kw = [k.lower() for k in self.config.get("routine_keywords", [])]
        text = (
            (getattr(proposal, "title", None) or "")
            + " "
            + (getattr(proposal, "body", None) or "")
        ).lower()
        has_novel = any(kw in text for kw in novel_kw)
        has_routine = any(kw in text for kw in routine_kw)
        return 1.0 if (has_novel and not has_routine) else 0.0

    @staticmethod
    def _aggregate_score(
        components: "FatigueComponents", weights: Dict[str, float]
    ) -> float:
        """Weighted aggregate of component scores -> DFI in [0, 100].
        Shared by compute() and compute_per_event() so the formula
        lives in exactly one place."""
        raw = (
            weights["volume"]        * components.volume
            + weights["concurrency"]  * components.concurrency
            + weights["burstiness"]   * components.burstiness
            + weights["reading_time"] * components.reading_time
            + weights["novelty"]      * components.novelty
        )
        return round(min(raw * 100, 100.0), 1)

    # ------------------------------------------------------------------
    # Metrics computation
    # ------------------------------------------------------------------

    @staticmethod
    def _vote_ts(item: Any) -> int:
        """When the delegate acted on this item. Falls back to the proposal's
        start for sources that carry no vote timestamp (the ecosystem variant
        counts proposals, not votes)."""
        return int(getattr(item, "voted_at", None) or getattr(item, "start", None) or 0)

    def _compute_metrics(
        self, proposals: List[Any], now_ts: int, by_vote_time: bool = False
    ) -> FatigueMetrics:
        """
        Volume windows measure votes per week/month when `by_vote_time` is set
        (per-event variant): the window anchors on when the delegate voted, not
        on when the proposal opened. A proposal that opened 40 days out but was
        voted on yesterday is yesterday's workload.

        Concurrency stays on proposal start/end in both variants - it asks how
        many decisions stood open around the delegate at `now_ts`, which is a
        proposal-time concept and not a substitute for the vote timestamp.
        """
        cutoff_7d  = now_ts - (7  * 86_400)
        cutoff_30d = now_ts - (30 * 86_400)

        def window_ts(p: Any) -> int:
            return self._vote_ts(p) if by_vote_time else (p.start or 0)

        # Upper bound (<= now_ts) lets caller pass `now` in the past
        # to compute DFI retrospectively (see endpoint `as_of` parameter).
        proposals_7d  = sum(1 for p in proposals if cutoff_7d  <= window_ts(p) <= now_ts)
        proposals_30d = sum(1 for p in proposals if cutoff_30d <= window_ts(p) <= now_ts)

        # Concurrent: proposals where start <= now <= end.
        #
        # A proposal whose voting window is unknown is SKIPPED, deliberately.
        # Sources differ in what they can supply (Tally omits the end timestamp;
        # the on-chain client cannot reconstruct it when ProposalCreated falls
        # outside its scan window), and an absent window must not be read as
        # "did not overlap". Until 2026-08-05 this happened by accident - the
        # `or 0` turned a missing end into the epoch, so the comparison was
        # false and every on-chain vote scored zero concurrency in silence.
        concurrent_active = sum(
            1 for p in proposals
            if getattr(p, "end", None) and (p.start or 0) <= now_ts <= p.end
        )

        # Average word count across 30d window
        recent = [p for p in proposals if cutoff_30d <= window_ts(p) <= now_ts]
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


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _klucz_decyzji(p: Any) -> str:
    r"""Tytuł sprowadzony do postaci porównywalnej między źródłami.

    Snapshot i kontrakt zapisują ten sam tytuł inaczej: nawiasy kwadratowe,
    przedrostek `Constitutional AIP:`, wielkość liter, znaki ucieczki w opisie
    ze zdarzenia (`[Constitutional\] AIP:`). Porównanie znak w znak dałoby zero
    trafień i cichy brak scalania - czyli stan sprzed poprawki, tylko z kodem,
    który wygląda, jakby coś robił.
    """
    t = (getattr(p, "title", None) or "").lower()
    t = re.sub(r"\\", "", t)
    t = re.sub(r"[\[\]()]", " ", t)
    t = re.sub(r"\b(constitutional|non-constitutional|aip|proposal)\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _czas_glosu(p: Any) -> float:
    """Moment głosu w sekundach. Gdy brak `voted_at` - start propozycji."""
    v = getattr(p, "voted_at", None) or getattr(p, "start", None) or 0
    return v if isinstance(v, (int, float)) else 0


def _lifecycle_key(p: Any) -> str:
    """Identyfikator cyklu decyzji, do którego należy obserwacja. Obserwacja
    spoza `merge_stages` (testy, korpus) jest własnym cyklem."""
    return str(getattr(p, "lifecycle_id", None) or getattr(p, "id", "") or id(p))


def _stage_id(p: Any) -> str:
    return str(getattr(p, "id", "") or "")


def reconcile_observations(votes: List[Any]) -> Tuple[List[Any], List[Dict[str, str]]]:
    """Scala WYŁĄCZNIE rekordy dowiedzione jako ta sama obserwacja: ten sam
    głosujący, to samo źródło, ta sama propozycja w tym źródle (closure review
    2026-09-03, punkt 3). Klienci źródeł do 2026-09-04 robili to same, po cichu,
    ZANIM powstał identyfikator zdarzenia - i identyfikator nazywał się
    „unikalny" dla obiektu, który już wchłonął inne rekordy.

    Zostaje rekord o NAJPÓŹNIEJSZYM `cast_at` (ponowne głosowanie zastępuje
    poprzednie - tak też zachowywały się klienci, które brały pierwszy rekord
    z listy sortowanej od najnowszego). Wchłonięte identyfikatory nie giną:
    trafiają do `superseded_source_vote_ids` obserwacji i do zwracanej listy
    uzgodnień, z której manifest je zapisze.

    Rekordy bez natywnego identyfikatora propozycji nie są uzgadniane z niczym.
    """
    grupy: Dict[Tuple[str, str, str], List[Any]] = {}
    luzem: List[Any] = []
    for v in votes:
        klucz = (str(getattr(v, "voter", "") or "").lower(),
                 str(getattr(v, "source_domain", "") or getattr(v, "source", "") or ""),
                 str(getattr(v, "native_proposal_id", "") or ""))
        if not klucz[2]:
            luzem.append(v)
            continue
        grupy.setdefault(klucz, []).append(v)
    wynik: List[Any] = list(luzem)
    uzgodnienia: List[Dict[str, str]] = []
    for czlonkowie in grupy.values():
        czlonkowie.sort(key=lambda x: (int(getattr(x, "cast_at", None) or _czas_glosu(x) or 0),
                                       str(getattr(x, "source_vote_id", "") or "")))
        zwyciezca = czlonkowie[-1]
        zwyciezca.superseded_source_vote_ids = [
            str(getattr(x, "source_vote_id", "") or _stage_id(x)) for x in czlonkowie[:-1]]
        for x in czlonkowie[:-1]:
            uzgodnienia.append({
                "kept": str(getattr(zwyciezca, "source_vote_id", "") or _stage_id(zwyciezca)),
                "superseded": str(getattr(x, "source_vote_id", "") or _stage_id(x)),
                "reason": "same voter, source and native proposal id",
            })
        wynik.append(zwyciezca)
    return wynik, uzgodnienia


def merge_stages(votes: List[Any], okno_dni: int = 45) -> List[Any]:
    """Wiąże etapy JEDNEJ decyzji w cykl (lifecycle), NIE mutując żadnego etapu.

    Arbitrum prowadzi propozycję przez sondę nastrojów na Snapshocie, a potem
    przez wiążący głos na kontrakcie. Do 2026-08-05 liczyliśmy to jako dwa
    zdarzenia, z komentarzem w kodzie, że tak ma być, bo „obciążenie nie zależy
    od tego, w którym systemie oddano głos". Dwaj uczestnicy obalili tę przesłankę
    niezależnie i z nazwanym mechanizmem: P03 - „the workload is 1 time.
    Arbitrum works with temperature check and then the real vote"; P01 - drugie
    przejście to „quick review to make sure the text hasn't changed".

    DO 2026-09-04 ta funkcja SCALAŁA etapy w jeden obiekt: zostawał etap
    o najwcześniejszym głosie, dostawał najdłuższą treść i kategorię z etapu,
    który ją znał. Closure review (/t/30604, 2026-09-03, punkt 1) pokazał,
    że to przeciek w przyszłość drugą drogą: obiekt o `voted_at` = t1 niósł
    treść i klasyfikację z etapu o t2 > t1, a `compute_per_event(as_of=t1)`
    liczył reading_time i novelty z informacji, która w t1 nie istniała.
    Do tego jednostka analizy przestawała być jednym głosem - a NASA-TLX
    ocenia jedno konkretne zadanie.

    OD 2026-09-04: każdy etap zostaje osobną, ZAMROŻONĄ obserwacją
    (`TaskObservation` w języku recenzji) z własnym `id`, `voted_at`, `body`
    i `category`. Przynależność do cyklu zapisują pola:
      - `lifecycle_id`      - DecisionLifecycleId (skrót klucza decyzji i
                              momentu pierwszego etapu),
      - `lifecycle_stage_ids` - identyfikatory wszystkich etapów cyklu,
      - `stage_index`       - pozycja etapu w cyklu (1 = pierwsze czytanie),
      - `stages`            - liczba etapów (zgodność z dotychczasowym API).
    Zliczanie obciążenia po cyklach (jedna decyzja = jedno zdarzenie w oknie
    volume/burstiness) robi `compute_per_event`, na zamrożonych obserwacjach.

    OKNO CZASOWE (od 2026-08-06). Sam tytuł nie wystarczy do orzeczenia, że dwa
    głosy są etapami tej samej decyzji. Governance powtarza procesy cyklicznie
    pod niezmienioną nazwą - „Security Council Election Process Improvements"
    wraca co roku. Bez ograniczenia czasowego wybory z 2025 i z 2026 lądowały
    w jednym zdarzeniu, a ono dziedziczyło znacznik starszego etapu. Zmierzone
    na dwóch uczestnikach Phase A: głos P02 z 2026-07-30 wchłonięty przez głos
    z 2025-09-10 (odstęp 323 dni), głos P01 z 2026-08-03 przez 2025-09-08
    (329 dni). W obu wypadkach zniknął NAJNOWSZY głos uczestnika, więc endpoint
    bez `proposal_id` wskazywał zdarzenie sprzed tygodnia, a zapytanie o właściwy
    identyfikator on-chain zwracało 404.

    Próg wzięty z rozkładu odstępów, nie z wyczucia. U obu uczestników odstępy
    układają się w skupisko do 33 dni (najdłuższy wiarygodny: 32,2), a następna
    wartość to dopiero 65,7 dnia. 45 dni leży w tej przerwie: mieści pełną drogę
    sonda-głos wiążący razem z zapasem i odcina powtórzenia cyklu.

    Ograniczeniem jest to, że odstępy 65-112 dni też przestają się scalać.
    Nie wiem, czy któreś z nich było prawdziwym dwuetapowym przejściem - przy
    takim odstępie „szybkie sprawdzenie, czy tekst się nie zmienił" przestaje
    być wiarygodnym opisem pracy delegata.
    """
    okno = okno_dni * 86_400
    # kubełek: klucz decyzji -> lista cykli; cykl = lista etapów rosnąco po czasie
    kubelki: Dict[str, List[List[Any]]] = {}
    # Sortowanie po momencie głosu, a przy remisie po identyfikatorze. Bez tego
    # wynik zależałby od kolejności, w jakiej odpowiedziały trzy źródła - a
    # niezmiennik z 05.08 mówi: ten sam cel i te same dowody dają ten sam pomiar.
    for p in sorted(votes, key=lambda x: (_czas_glosu(x), _stage_id(x))):
        k = _klucz_decyzji(p)
        if not k:
            k = f"__bez_tytulu__{id(p)}"
        czas = _czas_glosu(p)
        cykl = None
        # Od najnowszego cyklu w tej rodzinie - etap dokleja się do cyklu,
        # który trwa, nie do zamkniętego sprzed roku. Odstęp liczy się od
        # OSTATNIEGO etapu cyklu, jak przed zmianą (kubełek trzymał najnowszy
        # obiekt rodziny, a ten miał czas najwcześniejszego etapu - stąd
        # porównanie z pierwszym etapem, zachowane tu co do wartości).
        for kandydat in reversed(kubelki.setdefault(k, [])):
            pierwszy = _czas_glosu(kandydat[0])
            if czas and pierwszy and (czas - pierwszy) <= okno:
                cykl = kandydat
                break
        if cykl is None:
            kubelki[k].append([p])
        else:
            cykl.append(p)

    wynik: List[Any] = []
    for rodzina in kubelki.values():
        for cykl in rodzina:
            ids = [_stage_id(s) for s in cykl]
            pierwszy = cykl[0]
            surowe = f"{_klucz_decyzji(pierwszy)}|{int(_czas_glosu(pierwszy))}|{ids[0]}"
            lifecycle_id = "lc:" + hashlib.sha256(surowe.encode()).hexdigest()[:16]
            for i, s in enumerate(cykl, start=1):
                # Etap NIE dostaje niczego od innych etapów - ani treści, ani
                # kategorii, ani czasu. Tylko przynależność.
                s.lifecycle_id = lifecycle_id
                s.lifecycle_stage_ids = list(ids)
                s.stage_index = i
                s.stages = len(cykl)
                s.lifecycle_started_at = int(_czas_glosu(pierwszy))
                s.stage_ids = [_stage_id(s)]
                wynik.append(s)
    return wynik
