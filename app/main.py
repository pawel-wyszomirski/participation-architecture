import json
import os
import sys
import pathlib
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

sys.path.append(os.getcwd())

from app.db.session import SessionLocal, engine, Base
from app.db.models import Proposal, FatigueSnapshot

from app.services.rule_engine import (
    RuleEngine,
    ProposalInput,
    TriageResult,
    proposal_from_db_model,
)
from app.services.fatigue_engine import (
    FatigueEngine, InstrumentInvalid, merge_stages, reconcile_observations,
)
from app.services.arbdata_client import ArbdataClient
from app.services.governor_client import GovernorClient
from app.services.snapshot_client import SnapshotClient
from app.services.tally_client import TallyClient

# Create all tables (including fatigue_snapshots)
Base.metadata.create_all(bind=engine)

# --- Singletons ---
try:
    rule_engine = RuleEngine("rulebook.yaml")
    print(f"✅ Rule Engine initialized: v{rule_engine.version}, {len(rule_engine.rulebook['rules'])} rules")
except Exception as e:
    print(f"⚠️  Rule Engine initialization failed: {e}")
    rule_engine = None

fatigue_engine_error: Optional[str] = None
try:
    fatigue_engine = FatigueEngine("fatigue_config.yaml")
    print(f"✅ Fatigue Engine initialized: v{fatigue_engine.version} "
          f"instrument={fatigue_engine.instrument_hash[:12]}")
except InstrumentInvalid as e:
    # Fail closed (closure review point 6): the instrument is INVALID, the
    # per-event endpoint answers 503 INSTRUMENT_INVALID, nothing is computed.
    print(f"⛔ Fatigue Engine: {e}")
    fatigue_engine = None
    fatigue_engine_error = str(e)
except Exception as e:
    print(f"⚠️  Fatigue Engine initialization failed: {e}")
    fatigue_engine = None
    fatigue_engine_error = f"INSTRUMENT_INVALID: {e}"

app = FastAPI(
    title="Participation Architecture API",
    version="0.7.0",
    description=(
        "Governance Data Pipeline & Deterministic Triage Rules for DAOs. "
        "Includes Delegate Fatigue Index (DFI) — Milestone 2."
    ),
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# DASHBOARD (DFI per-event UI — served at root; arbitrum.wyszomirski.online)
# ============================================================================

_DASHBOARD_HTML = pathlib.Path(__file__).parent / "static" / "dashboard.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    """ACUS Delegate Fatigue Index dashboard (per-event).

    Shown AFTER the NASA-TLX survey (anti-anchoring, D8). The page reads
    ?address=0x... and fetches GET /delegates/{address}/per-event-fatigue.
    """
    try:
        return _DASHBOARD_HTML.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Dashboard asset not found")


# ============================================================================
# RESPONSE MODELS - System
# ============================================================================

class HealthCheck(BaseModel):
    status: str
    version: str
    database: str
    proposals_count: int
    rule_engine: str = "not_initialized"
    rulebook_version: Optional[str] = None
    fatigue_engine: str = "not_initialized"
    fatigue_config_version: Optional[str] = None


# ============================================================================
# RESPONSE MODELS - Proposals
# ============================================================================

class ProposalMetadata(BaseModel):
    author: str
    state: str
    votes: int
    scores_total: float
    created_at: datetime
    start_at: datetime
    end_at: datetime


class ProposalTriageResponse(BaseModel):
    id: str
    title: str
    priority_score: int = Field(..., ge=0, le=100)
    labels: List[str]
    reasons: List[str]
    recommended_handling: str
    metadata: ProposalMetadata


class ProposalDetailResponse(ProposalTriageResponse):
    body: str
    explain: dict


class ProposalsFeedResponse(BaseModel):
    proposals: List[ProposalTriageResponse]
    total: int
    page: int
    limit: int
    has_next: bool


# ============================================================================
# RESPONSE MODELS - Fatigue Index
# ============================================================================

class FatigueComponentsResponse(BaseModel):
    volume: float = Field(
        ..., ge=0.0, le=1.0,
        description="Volume load component (0-1): normalized proposals/7d + proposals/30d"
    )
    concurrency: float = Field(
        ..., ge=0.0, le=1.0,
        description="Concurrency component (0-1): simultaneous active proposals normalized"
    )
    burstiness: float = Field(
        ..., ge=0.0, le=1.0,
        description="Burstiness component (0-1): this-week spike vs. 4-week rolling average"
    )
    reading_time: float = Field(
        ..., ge=0.0, le=1.0,
        description="Reading time component (0-1): avg word count / reference (3000 words)"
    )
    novelty: float = Field(
        ..., ge=0.0, le=1.0,
        description="Novelty component (0-1): novel-domain proposals / total"
    )


class FatigueMetricsResponse(BaseModel):
    proposals_7d: int = Field(..., description="Proposals started in last 7 days")
    proposals_30d: int = Field(..., description="Proposals started in last 30 days")
    concurrent_active: int = Field(..., description="Proposals active right now (start<=now<=end)")
    avg_word_count: float = Field(..., description="Mean word count across 30d proposal window")
    weekly_avg: float = Field(..., description="proposals_30d / 4.33 — rolling weekly average")
    novelty_ratio: float = Field(..., description="Fraction of 30d proposals classified as novel")
    concurrency_source: str = Field(
        default="voted_only",
        description=(
            "What concurrent_active was counted from: 'ecosystem:snapshot' = all "
            "proposals open in the space at t (ecosystem governance load, grant "
            "review point 3); 'voted_only' = only proposals this delegate voted "
            "on (fallback when the ecosystem source is unavailable)"
        ),
    )
    voted_concurrent: int = Field(
        default=0,
        description=(
            "Revealed engagement at t: proposals THIS delegate voted on whose "
            "window covered the moment - reported alongside ecosystem load, "
            "never mixed with it"
        ),
    )


class FatigueWeightsResponse(BaseModel):
    volume: float
    concurrency: float
    burstiness: float
    reading_time: float
    novelty: float


class FatigueResponse(BaseModel):
    address: str
    fatigue_score: float = Field(
        ..., ge=0.0, le=100.0,
        description="Delegate Fatigue Index: 0 (no load) to 100 (maximum load)"
    )
    status: str = Field(..., description="LOW | MODERATE | HIGH | CRITICAL")
    components: FatigueComponentsResponse
    metrics: FatigueMetricsResponse
    weights: FatigueWeightsResponse
    config_version: str = Field(..., description="fatigue_config.yaml version used")
    computed_at: datetime
    formula: str = Field(
        default=FatigueEngine.FORMULA,
        description="Exact formula used to compute fatigue_score"
    )


class MeasurementIdentityResponse(BaseModel):
    """Grant review point 4: what binds this result to the exact circumstances
    it was computed under."""
    vote_event_id: str = Field(..., description=(
        "Deterministic digest of (address, every stage id of the merged "
        "vote-event, vote timestamp) - the unique vote-event, not only the "
        "proposal id"))
    stage_ids: List[str] = Field(..., description="Ids of every merged stage of the event")
    voted_at: int = Field(..., description="Vote timestamp bound into the identity")
    instrument_version: str = Field(..., description="fatigue_config.yaml version")
    code_commit: str = Field(..., description="Git HEAD of the running code, or 'unknown'")
    source_state: Dict[str, Any] = Field(..., description=(
        "Source-capability state: events per source, history size, events "
        "with unknown voting window, and what concurrency was counted from"))
    # Closure review (2026-09-03) points 1-4
    lifecycle_id: str = Field("", description="DecisionLifecycleId linking the stages of one decision")
    lifecycle_stage_ids: List[str] = Field(default_factory=list)
    source_vote_id: str = Field("", description="Native vote id from the source")
    source_domain: str = Field("", description="snapshot | tally | governor:core | governor:treasury")
    native_proposal_id: str = Field("", description="Proposal id as the source knows it")
    target_content_hash: str = Field("", description="sha256 of the rated title + body")
    context_stage_ids: List[str] = Field(default_factory=list)
    context_set_hash: str = Field("")
    ecosystem_ids: List[str] = Field(default_factory=list)
    ecosystem_set_hash: str = Field("")
    source_receipts: List[Dict[str, Any]] = Field(default_factory=list, description=(
        "One capability receipt per source: HEALTHY_COMPLETE | HEALTHY_EMPTY | "
        "PARTIAL | TRUNCATED | UNAVAILABLE | AUTH_MISSING | ERROR"))
    instrument_hash: str = Field("", description="sha256 of fatigue_config.yaml bytes")
    eligibility: str = Field("", description=(
        "PRIMARY_ELIGIBLE | NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS - fail-closed verdict"))
    eligibility_reasons: List[str] = Field(default_factory=list, description="Disqualifying")
    eligibility_notes: List[str] = Field(default_factory=list, description=(
        "Recorded limits that do not disqualify (e.g. history truncated beyond the context window)"))
    measurement_id: str = Field("", description=(
        "Digest of the complete measurement identity; persistence is idempotent on it"))


class PerEventFatigueResponse(FatigueResponse):
    """
    Per-event DFI: the Delegate Fatigue Index for ONE vote (dissertation 5.3.5a,
    per-event pivot 2026-05-11). Extends FatigueResponse with the rated proposal
    and the as_of timestamp (the vote time used as the reference point).

    reading_time/novelty describe the rated proposal (intrinsic load);
    volume/concurrency/burstiness describe the delegate's context around the vote.
    """
    mode: str = Field(default="per_event", description="Always 'per_event'")
    target_proposal_id: str = Field(..., description="Snapshot id of the rated proposal")
    target_proposal_title: str = Field(..., description="Title of the rated proposal")
    as_of: datetime = Field(..., description="Vote timestamp used as the DFI reference point")
    identity: Optional[MeasurementIdentityResponse] = Field(
        None, description="Measurement identity (grant review point 4)")
    eligibility: str = Field("", description=(
        "PRIMARY_ELIGIBLE | NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS (closure review point 2)"))
    measurement_id: str = Field("", description="Digest of the complete measurement identity")
    persisted: Optional[bool] = Field(None, description=(
        "POST only: true when this call registered a new row, false when a row "
        "with the same measurement_id already existed. GET never persists."))


# ============================================================================
# ENDPOINTS - System
# ============================================================================

@app.get("/", tags=["System"])
async def root():
    return {
        "message": "Participation Architecture API v0.7.0",
        "status": "operational",
        "milestone": "M2 - Fatigue Index + Full API",
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthCheck, tags=["System"])
async def health_check(db: Session = Depends(get_db)):
    try:
        count = db.query(Proposal).count()
        db_status = "connected"
    except Exception:
        count = 0
        db_status = "disconnected"

    return HealthCheck(
        status="ok",
        version="0.7.0",
        database=db_status,
        proposals_count=count,
        rule_engine="initialized" if rule_engine else "not_initialized",
        rulebook_version=rule_engine.version if rule_engine else None,
        fatigue_engine="initialized" if fatigue_engine else "not_initialized",
        fatigue_config_version=fatigue_engine.version if fatigue_engine else None,
    )


# ============================================================================
# ENDPOINTS - Proposals
# ============================================================================

@app.get("/proposals/feed", response_model=ProposalsFeedResponse, tags=["Proposals"])
async def get_proposals_feed(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    min_priority: Optional[int] = Query(None, ge=0, le=100),
    label: Optional[str] = Query(None),
    handling: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Normalized proposals feed with deterministic triage scores.
    Sorted by priority_score descending.
    """
    if not rule_engine:
        raise HTTPException(status_code=503, detail="Rule engine not initialized")

    query = db.query(Proposal)
    if status:
        query = query.filter(Proposal.state == status)

    all_proposals = query.order_by(Proposal.start.desc()).all()

    all_results = []
    for db_proposal in all_proposals:
        proposal_input = proposal_from_db_model(db_proposal)
        triage_result = rule_engine.evaluate_proposal(proposal_input)

        if min_priority is not None and triage_result.priority_score < min_priority:
            continue
        if label and label not in triage_result.labels:
            continue
        if handling and triage_result.recommended_handling != handling:
            continue

        all_results.append(ProposalTriageResponse(
            id=db_proposal.id,
            title=db_proposal.title,
            priority_score=triage_result.priority_score,
            labels=triage_result.labels,
            reasons=triage_result.reasons,
            recommended_handling=triage_result.recommended_handling,
            metadata=ProposalMetadata(
                author=db_proposal.author or "unknown",
                state=db_proposal.state or "unknown",
                votes=db_proposal.votes or 0,
                scores_total=db_proposal.scores_total or 0.0,
                created_at=datetime.fromtimestamp(
                    db_proposal.created_at.timestamp()
                    if hasattr(db_proposal.created_at, "timestamp")
                    else db_proposal.start,
                    tz=timezone.utc,
                ),
                start_at=datetime.fromtimestamp(db_proposal.start, tz=timezone.utc),
                end_at=datetime.fromtimestamp(db_proposal.end, tz=timezone.utc),
            ),
        ))

    all_results.sort(key=lambda x: x.priority_score, reverse=True)

    total = len(all_results)
    offset = (page - 1) * limit

    return ProposalsFeedResponse(
        proposals=all_results[offset:offset + limit],
        total=total,
        page=page,
        limit=limit,
        has_next=(offset + limit) < total,
    )


@app.get("/proposals/{proposal_id}", response_model=ProposalDetailResponse, tags=["Proposals"])
async def get_proposal_detail(proposal_id: str, db: Session = Depends(get_db)):
    """Single proposal with full rule audit trail."""
    if not rule_engine:
        raise HTTPException(status_code=503, detail="Rule engine not initialized")

    db_proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not db_proposal:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")

    proposal_input = proposal_from_db_model(db_proposal)
    triage_result = rule_engine.evaluate_proposal(proposal_input)

    return ProposalDetailResponse(
        id=db_proposal.id,
        title=db_proposal.title,
        body=db_proposal.body or "",
        priority_score=triage_result.priority_score,
        labels=triage_result.labels,
        reasons=triage_result.reasons,
        recommended_handling=triage_result.recommended_handling,
        metadata=ProposalMetadata(
            author=db_proposal.author or "unknown",
            state=db_proposal.state or "unknown",
            votes=db_proposal.votes or 0,
            scores_total=db_proposal.scores_total or 0.0,
            created_at=datetime.fromtimestamp(
                db_proposal.created_at.timestamp()
                if hasattr(db_proposal.created_at, "timestamp")
                else db_proposal.start,
                tz=timezone.utc,
            ),
            start_at=datetime.fromtimestamp(db_proposal.start, tz=timezone.utc),
            end_at=datetime.fromtimestamp(db_proposal.end, tz=timezone.utc),
        ),
        explain=triage_result.explain,
    )


# ============================================================================
# ENDPOINTS - Delegates / Fatigue Index
# ============================================================================

@app.get("/delegates/{address}/fatigue", response_model=FatigueResponse, tags=["Delegates"])
async def get_delegate_fatigue(
    address: str,
    as_of: Optional[datetime] = Query(
        None,
        description=(
            "Compute DFI as of this UTC timestamp (ISO 8601, e.g. 2026-04-01T00:00:00Z). "
            "Window of 30/7 days extends backwards from this point. "
            "Defaults to current time. Used for retrospective fatigue measurement "
            "(e.g. matching survey responses to past governance load)."
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    Delegate Fatigue Index (DFI) — ecosystem governance workload score (0-100).

    Reflects how much collective cognitive burden the current governance activity
    imposes on all delegates. A high score indicates that participation friction
    is elevated and that proposals may benefit from prioritization triage.

    Score is ecosystem-level (shared governance burden, same for all delegates).
    The `address` parameter is forward-compatible for future per-delegate signals.

    **Components** (see `components` in response):
    - `volume`       (40%): proposal volume over 7d and 30d windows
    - `concurrency`  (25%): simultaneously active proposals right now
    - `burstiness`   (20%): this-week spike vs. 4-week rolling average
    - `reading_time` (10%): average word count / baseline (cognitive cost proxy)
    - `novelty`       (5%): novel-domain proposals / total (new patterns cost more)

    **Theoretical grounding:**
    - Volume & concurrency: "kolektywna uwaga" as rivalrous commons resource
      (Fogg B=MAP Ability reduction, dissertation 2.3.1)
    - Burstiness: habit disruption — irregular spikes prevent stable participation
      routines (Fogg B=MAP, dissertation 2.2.1)
    - Reading time: direct proxy for Fogg's Ability barrier (dissertation 2.2.1)
    - Novelty: novel governance domains require more cognitive processing than
      routine repeating items (CLT, dissertation 1.4)

    All computation is persisted to `fatigue_snapshots` for reproducibility audit.
    """
    if not fatigue_engine:
        raise HTTPException(status_code=503, detail="Fatigue engine not initialized")

    # Reference time: caller-supplied `as_of` for retrospective computation,
    # or now() for the standard live measurement.
    ref_time = as_of if as_of else datetime.now(timezone.utc)
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=timezone.utc)
    ref_ts = int(ref_time.timestamp())

    # Fetch proposals covering 35d window ending at ref_time (30d window + buffer)
    cutoff_ts = int((ref_time - timedelta(days=35)).timestamp())
    proposals = db.query(Proposal).filter(
        Proposal.start >= cutoff_ts,
        Proposal.start <= ref_ts,
    ).all()

    # Also include proposals active at ref_time that may have started earlier
    active = db.query(Proposal).filter(
        Proposal.start < cutoff_ts,
        Proposal.start <= ref_ts,
        Proposal.end >= ref_ts,
    ).all()
    all_proposals = proposals + active

    result = fatigue_engine.compute(address=address, proposals=all_proposals, now=ref_time)

    # --- Persist snapshot ---
    snapshot = FatigueSnapshot(
        address=address,
        computed_at=result.computed_at,
        fatigue_score=result.fatigue_score,
        status=result.status,
        config_version=result.config_version,
        comp_volume=result.components.volume,
        comp_concurrency=result.components.concurrency,
        comp_burstiness=result.components.burstiness,
        comp_reading_time=result.components.reading_time,
        comp_novelty=result.components.novelty,
        metric_proposals_7d=result.metrics.proposals_7d,
        metric_proposals_30d=result.metrics.proposals_30d,
        metric_concurrent_active=result.metrics.concurrent_active,
        metric_avg_word_count=result.metrics.avg_word_count,
        metric_weekly_avg=result.metrics.weekly_avg,
        metric_novelty_ratio=result.metrics.novelty_ratio,
    )
    db.add(snapshot)
    db.commit()

    return FatigueResponse(
        address=result.address,
        fatigue_score=result.fatigue_score,
        status=result.status,
        components=FatigueComponentsResponse(
            volume=result.components.volume,
            concurrency=result.components.concurrency,
            burstiness=result.components.burstiness,
            reading_time=result.components.reading_time,
            novelty=result.components.novelty,
        ),
        metrics=FatigueMetricsResponse(
            proposals_7d=result.metrics.proposals_7d,
            proposals_30d=result.metrics.proposals_30d,
            concurrent_active=result.metrics.concurrent_active,
            avg_word_count=result.metrics.avg_word_count,
            weekly_avg=result.metrics.weekly_avg,
            novelty_ratio=result.metrics.novelty_ratio,
        ),
        weights=FatigueWeightsResponse(**result.weights),
        config_version=result.config_version,
        computed_at=result.computed_at,
        formula=FatigueEngine.FORMULA,
    )


@app.get("/delegates/{address}/fatigue/history", tags=["Delegates"])
async def get_fatigue_history(
    address: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Historical DFI snapshots for a given address.
    Returns the last N persisted computations, newest first.
    """
    rows = (
        db.query(FatigueSnapshot)
        .filter(FatigueSnapshot.address == address)
        .order_by(FatigueSnapshot.computed_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "computed_at": r.computed_at,
            "fatigue_score": r.fatigue_score,
            "status": r.status,
            "proposals_30d": r.metric_proposals_30d,
            "concurrent_active": r.metric_concurrent_active,
        }
        for r in rows
    ]


_PER_EVENT_PROPOSAL_QUERY = Query(
    None,
    description=(
        "Id of the vote-stage to rate (Snapshot proposal id, `tally:<id>` or "
        "`governor:<core|treasury>:<id>`). If omitted, the delegate's most "
        "recent vote is used."
    ),
)


async def _measure_per_event(address: str, proposal_id: Optional[str]):
    """Compute the per-event DFI for one vote. Shared by GET (read) and POST
    (register): closure review point 5 separates compute/persist from read.

    Returns (result, target, ref_time)."""
    if not fatigue_engine:
        raise HTTPException(
            status_code=503,
            detail=fatigue_engine_error or "INSTRUMENT_INVALID: fatigue engine not initialized",
        )

    # Merge off-chain (Snapshot) and on-chain votes, THEN link the stages of
    # one decision into a lifecycle.
    #
    # This used to be a plain union, justified in a comment as deliberate:
    # "cognitive load is source-agnostic, every decision the delegate makes
    # counts". Two participants refuted the premise on 2026-08-05, independently
    # and with the governance mechanism named.
    #
    #   P01: "mostly a quick review to make sure the text hasn't changed and my
    #         opinion is still valid"
    #   P03: "the workload is 1 time. Arbitrum works with temperature check and
    #         then the real vote. temperature check is an offchain vote, then the
    #         final is onchain"
    #
    # Snapshot is the temperature check and the contract carries the binding
    # vote. They are two stages of one decision, not two decisions. Counting both
    # inflated volume and burstiness for every delegate who goes through the full
    # path - which is all three Phase A participants.
    #
    # Three sources, because on-chain needs two of them (2026-08-03):
    # Tally froze its Arbitrum index on 2026-06-08 while the Governor contract
    # kept accepting votes - six votes by the three pilot participants were
    # missing from both Tally and Snapshot. GovernorClient reads the contract
    # directly and is authoritative for Arbitrum; Tally stays for coverage of
    # anything it still indexes, and duplicate ids cannot collide because each
    # client prefixes its own.
    #
    # Every source answers with a capability receipt (closure review point 2):
    # a zero here is no longer ambiguous between "healthy and empty" and
    # "did not answer" - the receipt says which, and eligibility depends on it.
    # 1000 is Snapshot's page ceiling. 200 cut an active delegate's history at
    # the limit (P02: 408 votes) and disqualified the measurement on 2026-09-04;
    # a truncation beyond the 30-day window is judged by the engine, not here.
    snap_votes, snap_receipt = await SnapshotClient().fetch_voted_observations(address, limit=1000)
    tally_votes, tally_receipt = await TallyClient().fetch_voted_observations(address, limit=200)
    chain_votes, chain_receipt = await GovernorClient().fetch_voted_observations(address, limit=200)
    # Reconciliation is explicit and logged (point 3): only records proven to be
    # the same observation (same voter, source, native proposal id) collapse,
    # and the superseded native ids go into the manifest.
    observations, reconciliations = reconcile_observations(
        (snap_votes or []) + (tally_votes or []) + (chain_votes or []))
    # Okno wiazania etapow z konfiguracji - powtarzalny tytul procesu nie moze
    # laczyc dwoch cykli w jeden (uzasadnienie przy kluczu w YAML). Etapy zostaja
    # osobnymi, zamrozonymi obserwacjami (point 1).
    voted = merge_stages(
        observations,
        okno_dni=fatigue_engine.config.get("stage_merge_window_days", 45),
    )

    # Kategoria z taksonomii DAO dla wszystkiego, co jej jeszcze nie ma. Zdarzenia
    # z kontraktu dostaja ja po identyfikatorze, Snapshot dopiero tutaj - po tytule,
    # bo nadaje propozycjom wlasne identyfikatory. Bez tego `novelty` liczyloby sie
    # z historii, w ktorej kategorie ma jedna pozycja na dwiescie.
    # The registry is a source with a receipt (found 2026-09-04: it answered 403
    # and novelty fell back to the keyword list for everyone, with a clean
    # verdict). Its receipt goes to the engine like the vote sources' do.
    _rejestr = ArbdataClient()
    if await _rejestr.load():
        _rejestr.przypisz_kategorie(voted)
    taxonomy_receipt = _rejestr.receipt
    if not voted:
        raise HTTPException(
            status_code=404,
            detail=f"No Snapshot, Tally or on-chain votes found for delegate {address}",
        )

    if proposal_id:
        target = next((p for p in voted if p.id == proposal_id), None)
        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"Delegate {address} has no vote on proposal {proposal_id}",
            )
    else:
        # Most recent vote = latest by VOTE time (when the delegate voted),
        # not by proposal start. voted_at falls back to start if absent.
        target = max(voted, key=lambda p: (getattr(p, "voted_at", None) or p.start or 0))

    # as_of = the vote timestamp (per-event, dissertation 5.3.5a), not the
    # proposal start. The delegate rated THIS vote, cast at this moment.
    _vote_ts = getattr(target, "voted_at", None) or target.start or 0
    ref_time = datetime.fromtimestamp(_vote_ts, tz=timezone.utc)

    # Ecosystem governance load at the vote moment (grant review point 3):
    # every proposal open in the space at t, not just the delegate's slice.
    # None = the source did not answer; the engine then falls back to the
    # voted-only construction, NAMES it in metrics.concurrency_source AND
    # marks the result NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS - a different
    # construct is not the frozen instrument (closure review point 2).
    ecosystem, eco_receipt = await SnapshotClient().fetch_ecosystem_exposure(_vote_ts)

    result = fatigue_engine.compute_per_event(
        address=address, target_proposal=target, voted_history=voted, now=ref_time,
        ecosystem_proposals=ecosystem,
        source_counts={
            "snapshot": len(snap_votes or []),
            "tally": len(tally_votes or []),
            "governor": len(chain_votes or []),
        },
        source_receipts=[snap_receipt, tally_receipt, chain_receipt, eco_receipt, taxonomy_receipt],
        reconciliations=reconciliations,
    )
    return result, target, ref_time


def _per_event_response(result, target, ref_time, persisted: Optional[bool]) -> "PerEventFatigueResponse":
    return PerEventFatigueResponse(
        address=result.address,
        fatigue_score=result.fatigue_score,
        status=result.status,
        components=FatigueComponentsResponse(
            volume=result.components.volume,
            concurrency=result.components.concurrency,
            burstiness=result.components.burstiness,
            reading_time=result.components.reading_time,
            novelty=result.components.novelty,
        ),
        metrics=FatigueMetricsResponse(
            proposals_7d=result.metrics.proposals_7d,
            proposals_30d=result.metrics.proposals_30d,
            concurrent_active=result.metrics.concurrent_active,
            avg_word_count=result.metrics.avg_word_count,
            weekly_avg=result.metrics.weekly_avg,
            novelty_ratio=result.metrics.novelty_ratio,
            concurrency_source=result.metrics.concurrency_source,
            voted_concurrent=result.metrics.voted_concurrent,
        ),
        weights=FatigueWeightsResponse(**result.weights),
        config_version=result.config_version,
        computed_at=result.computed_at,
        formula=FatigueEngine.FORMULA,
        mode=result.mode,
        target_proposal_id=target.id,
        target_proposal_title=(getattr(target, "title", None) or ""),
        as_of=ref_time,
        identity=(MeasurementIdentityResponse(**result.identity.manifest())
                  if result.identity else None),
        eligibility=result.identity.eligibility if result.identity else "",
        measurement_id=result.identity.measurement_id if result.identity else "",
        persisted=persisted,
    )


@app.get(
    "/delegates/{address}/per-event-fatigue",
    response_model=PerEventFatigueResponse,
    tags=["Delegates"],
)
async def get_per_event_fatigue(
    address: str,
    proposal_id: Optional[str] = _PER_EVENT_PROPOSAL_QUERY,
):
    """
    Per-event Delegate Fatigue Index (dissertation 5.3.5a; per-event pivot).

    Computes DFI for a SINGLE vote by the delegate, matched to the vote time
    (as_of). The unit is one vote, not a 30-day aggregate - this is what aligns
    DFI with the task-specific NASA-TLX (validated to ~24h, Hernandez 2021).

    Flow: fetch the delegate's votes from Snapshot, Tally and the Governor
    contracts (each with a capability receipt) -> reconcile -> link stages into
    lifecycles -> pick the target (given proposal_id, else the most recent
    vote) -> compute_per_event with as_of = the vote timestamp.

    reading_time/novelty come from the rated vote-stage (intrinsic load);
    volume/concurrency/burstiness from the delegate's voting context.

    READ ONLY (closure review point 5): this never writes a row. A browser
    refresh is HTTP traffic, not a measurement. To register a measurement in
    the scientific registry use POST on the same path.

    UI note (anti-anchoring, decision D8): the survey must collect NASA-TLX
    BEFORE this score is shown to the delegate.
    """
    result, target, ref_time = await _measure_per_event(address, proposal_id)
    return _per_event_response(result, target, ref_time, persisted=None)


@app.post(
    "/delegates/{address}/per-event-fatigue",
    response_model=PerEventFatigueResponse,
    tags=["Delegates"],
)
async def register_per_event_fatigue(
    address: str,
    proposal_id: Optional[str] = _PER_EVENT_PROPOSAL_QUERY,
    db: Session = Depends(get_db),
):
    """
    Compute AND register the per-event measurement (closure review point 5).

    Idempotent on the complete measurement identity: the same vote-event on
    the same instrument, code and input sets is ONE row in fatigue_snapshots,
    however many times this is called. `persisted` in the response says
    whether this call created the row (true) or found it (false). A changed
    input set - a new stage observed, a source answering differently - is a
    different measurement and gets its own row, with its own manifest.
    """
    result, target, ref_time = await _measure_per_event(address, proposal_id)
    mid = result.identity.measurement_id
    existing = db.query(FatigueSnapshot).filter(FatigueSnapshot.measurement_id == mid).first()
    if existing is not None:
        return _per_event_response(result, target, ref_time, persisted=False)

    snapshot = FatigueSnapshot(
        address=result.address,
        computed_at=result.computed_at,
        fatigue_score=result.fatigue_score,
        status=result.status,
        config_version=result.config_version,
        comp_volume=result.components.volume,
        comp_concurrency=result.components.concurrency,
        comp_burstiness=result.components.burstiness,
        comp_reading_time=result.components.reading_time,
        comp_novelty=result.components.novelty,
        metric_proposals_7d=result.metrics.proposals_7d,
        metric_proposals_30d=result.metrics.proposals_30d,
        metric_concurrent_active=result.metrics.concurrent_active,
        metric_avg_word_count=result.metrics.avg_word_count,
        metric_weekly_avg=result.metrics.weekly_avg,
        metric_novelty_ratio=result.metrics.novelty_ratio,
        vote_event_id=result.identity.vote_event_id,
        code_commit=result.identity.code_commit,
        source_state=json.dumps(result.identity.source_state),
        measurement_id=mid,
        instrument_hash=result.identity.instrument_hash,
        eligibility=result.identity.eligibility,
        manifest=json.dumps(result.identity.manifest(), sort_keys=True),
    )
    db.add(snapshot)
    try:
        db.commit()
    except IntegrityError:
        # Two concurrent registrations of the same measurement: the unique
        # index decides, this call reports the row as already present.
        db.rollback()
        return _per_event_response(result, target, ref_time, persisted=False)
    return _per_event_response(result, target, ref_time, persisted=True)


# ============================================================================
# ENDPOINTS - Debug
# ============================================================================

@app.get("/debug/proposals", tags=["Debug"])
def get_raw_proposals(limit: int = 5, db: Session = Depends(get_db)):
    return db.query(Proposal).order_by(Proposal.start.desc()).limit(limit).all()


@app.get("/debug/rulebook", tags=["Debug"])
def get_rulebook_info():
    if not rule_engine:
        raise HTTPException(status_code=503, detail="Rule engine not initialized")
    return rule_engine.get_rulebook_info()


@app.get("/debug/fatigue-config", tags=["Debug"])
def get_fatigue_config():
    if not fatigue_engine:
        raise HTTPException(status_code=503, detail="Fatigue engine not initialized")
    return fatigue_engine.get_config_info()


# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
async def startup_event():
    print("\n" + "=" * 70)
    print("🚀 PARTICIPATION ARCHITECTURE API v0.7.0")
    print("=" * 70)
    if rule_engine:
        print(f"⚙️  Rule Engine:    v{rule_engine.version} ({len(rule_engine.rulebook['rules'])} rules)")
    else:
        print("⚠️  Rule Engine:    NOT INITIALIZED")
    if fatigue_engine:
        print(f"📊 Fatigue Engine: v{fatigue_engine.version}")
    else:
        print("⚠️  Fatigue Engine: NOT INITIALIZED")
    print(f"📡 API Docs: http://localhost:8000/docs")
    print("=" * 70 + "\n")
