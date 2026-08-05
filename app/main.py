import os
import sys
import pathlib
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func

sys.path.append(os.getcwd())

from app.db.session import SessionLocal, engine, Base
from app.db.models import Proposal, FatigueSnapshot

from app.services.rule_engine import (
    RuleEngine,
    ProposalInput,
    TriageResult,
    proposal_from_db_model,
)
from app.services.fatigue_engine import FatigueEngine, merge_stages
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

try:
    fatigue_engine = FatigueEngine("fatigue_config.yaml")
    print(f"✅ Fatigue Engine initialized: v{fatigue_engine.version}")
except Exception as e:
    print(f"⚠️  Fatigue Engine initialization failed: {e}")
    fatigue_engine = None

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


@app.get(
    "/delegates/{address}/per-event-fatigue",
    response_model=PerEventFatigueResponse,
    tags=["Delegates"],
)
async def get_per_event_fatigue(
    address: str,
    proposal_id: Optional[str] = Query(
        None,
        description=(
            "Snapshot id of the proposal to rate. If omitted, the delegate's "
            "most recent vote is used."
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    Per-event Delegate Fatigue Index (dissertation 5.3.5a; per-event pivot).

    Computes DFI for a SINGLE vote by the delegate, matched to the vote time
    (as_of). The unit is one vote, not a 30-day aggregate - this is what aligns
    DFI with the task-specific NASA-TLX (validated to ~24h, Hernandez 2021).

    Flow: fetch the delegate's voted proposals from Snapshot -> pick the target
    (given proposal_id, else the most recent vote) -> compute_per_event with
    as_of = the proposal's start time.

    reading_time/novelty come from the rated proposal (intrinsic load);
    volume/concurrency/burstiness from the delegate's voting context.

    UI note (anti-anchoring, decision D8): the survey must collect NASA-TLX
    BEFORE this score is shown to the delegate.
    """
    if not fatigue_engine:
        raise HTTPException(status_code=503, detail="Fatigue engine not initialized")

    # Merge off-chain (Snapshot) and on-chain votes, THEN collapse the stages of
    # one decision into one event.
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
    snap_votes = await SnapshotClient().fetch_voted_proposals(address, limit=200)
    tally_votes = await TallyClient().fetch_voted_proposals(address, limit=200)
    chain_votes = await GovernorClient().fetch_voted_proposals(address, limit=200)
    voted = merge_stages((snap_votes or []) + (tally_votes or []) + (chain_votes or []))

    # Kategoria z taksonomii DAO dla wszystkiego, co jej jeszcze nie ma. Zdarzenia
    # z kontraktu dostaja ja po identyfikatorze, Snapshot dopiero tutaj - po tytule,
    # bo nadaje propozycjom wlasne identyfikatory. Bez tego `novelty` liczyloby sie
    # z historii, w ktorej kategorie ma jedna pozycja na dwiescie.
    _rejestr = ArbdataClient()
    if await _rejestr.load():
        _rejestr.przypisz_kategorie(voted)
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
    result = fatigue_engine.compute_per_event(
        address=address, target_proposal=target, voted_history=voted, now=ref_time
    )

    # Persist snapshot for reproducibility (same table as ecosystem variant).
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
    )
    db.add(snapshot)
    db.commit()

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
        ),
        weights=FatigueWeightsResponse(**result.weights),
        config_version=result.config_version,
        computed_at=result.computed_at,
        formula=FatigueEngine.FORMULA,
        mode=result.mode,
        target_proposal_id=target.id,
        target_proposal_title=(getattr(target, "title", None) or ""),
        as_of=ref_time,
    )


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
