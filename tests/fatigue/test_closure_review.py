"""
Tests for the six repairs required by the Cross-Layer Closure Review
(/t/30604, AIE - Integrity Research, 2026-09-03).

<!-- catalog-read --> tests/fatigue had test_fatigue_engine, test_merge_stages,
test_per_event, test_panel_nazwy - none covers receipts, eligibility,
reconciliation, manifest or the fail-closed instrument.

    1. no leakage through stage merging      -> test_per_event / test_merge_stages
                                                + lifecycle counting here
    2. source capability receipts, fail closed -> eligibility tests
    3. native vote identity before dedup     -> reconcile_observations tests
    4. complete persisted manifest           -> manifest / measurement_id tests
    5. GET does not persist, POST idempotent -> tests/test_api_per_event.py
    6. instrument fails closed on bad config -> InstrumentInvalid tests

Run with: pytest tests/fatigue/test_closure_review.py -v
"""

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import (  # noqa: E402
    ELIGIBLE, NOT_ELIGIBLE, HEALTHY_COMPLETE, HEALTHY_EMPTY, PARTIAL, TRUNCATED,
    UNAVAILABLE, AUTH_MISSING, ERROR,
    FatigueEngine, InstrumentInvalid, SourceReceipt,
    merge_stages, reconcile_observations,
)

DZIEN = 86_400


@dataclass
class Obs:
    id: str
    title: str = "Proposal"
    voted_at: int = 0
    start: int = 0
    end: int = 0
    body: str = "word " * 400
    category: Optional[str] = None
    voter: str = "0xA"
    source_domain: str = "snapshot"
    source_vote_id: str = ""
    native_proposal_id: str = ""


@pytest.fixture
def now():
    return datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    return FatigueEngine("fatigue_config.yaml")


def obs(id_, days_ago, now, **kw):
    t = int((now - timedelta(days=days_ago)).timestamp())
    kw.setdefault("start", t)
    kw.setdefault("end", t + 3 * DZIEN)
    return Obs(id=id_, voted_at=t, **kw)


def healthy_receipts():
    return [
        SourceReceipt("snapshot", HEALTHY_COMPLETE, events=3),
        SourceReceipt("tally", AUTH_MISSING, detail="no key"),
        SourceReceipt("governor", HEALTHY_COMPLETE, events=2),
        SourceReceipt("ecosystem", HEALTHY_COMPLETE, events=2),
    ]


# ---------------------------------------------------------------------------
# 6. Fail closed on instrument
# ---------------------------------------------------------------------------

def test_missing_config_is_instrument_invalid(tmp_path):
    with pytest.raises(InstrumentInvalid) as e:
        FatigueEngine(str(tmp_path / "nope.yaml"))
    assert "INSTRUMENT_INVALID" in str(e.value)


def test_weights_not_summing_to_one_is_instrument_invalid(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: '9'\nweights: {volume: 0.5, concurrency: 0.5, burstiness: 0.5, "
        "reading_time: 0.1, novelty: 0.05}\n"
        "reference_values: {volume_7d: 5, volume_30d: 20, concurrent: 5, reading_words: 3000}\n"
        "reference_values_per_event: {volume_7d: 7, volume_30d: 18, concurrent: 2, reading_words: 710}\n"
        "thresholds: {low: 30, moderate: 70, high: 85}\n")
    with pytest.raises(InstrumentInvalid) as e:
        FatigueEngine(str(bad))
    assert "sum" in str(e.value)


def test_missing_per_event_references_is_instrument_invalid(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: '9'\nweights: {volume: 0.4, concurrency: 0.25, burstiness: 0.2, "
        "reading_time: 0.1, novelty: 0.05}\n"
        "reference_values: {volume_7d: 5, volume_30d: 20, concurrent: 5, reading_words: 3000}\n"
        "thresholds: {low: 30, moderate: 70, high: 85}\n")
    with pytest.raises(InstrumentInvalid) as e:
        FatigueEngine(str(bad))
    assert "reference_values_per_event" in str(e.value)


def test_boolean_weight_is_rejected_not_coerced():
    """YAML `yes` reads as True and int(True) is 1 - a silent number change."""
    problems = FatigueEngine.validate_config({
        "version": "9",
        "weights": {"volume": True, "concurrency": 0.25, "burstiness": 0.2,
                    "reading_time": 0.1, "novelty": 0.05},
        "reference_values": {"volume_7d": 5, "volume_30d": 20, "concurrent": 5, "reading_words": 3000},
        "reference_values_per_event": {"volume_7d": 7, "volume_30d": 18, "concurrent": 2, "reading_words": 710},
        "thresholds": {"low": 30, "moderate": 70, "high": 85},
    })
    assert any("volume" in p for p in problems)


def test_instrument_hash_is_bytes_of_the_file(engine):
    import hashlib
    raw = open("fatigue_config.yaml", "rb").read()
    assert engine.instrument_hash == hashlib.sha256(raw).hexdigest()


def test_canonical_config_is_valid():
    assert FatigueEngine.validate_config(FatigueEngine("fatigue_config.yaml").config) == []


# ---------------------------------------------------------------------------
# 2. Receipts and eligibility
# ---------------------------------------------------------------------------

def test_receipt_rejects_unknown_state():
    with pytest.raises(ValueError):
        SourceReceipt("snapshot", "FINE")


def test_all_required_sources_healthy_is_primary_eligible(engine, now):
    target = obs("0xt", 0, now)
    r = engine.compute_per_event("0xA", target, [target], now=now,
                                 ecosystem_proposals=[obs("e1", 1, now)],
                                 source_receipts=healthy_receipts())
    assert r.identity.eligibility == ELIGIBLE
    assert r.identity.eligibility_reasons == []


def test_tally_auth_missing_does_not_disqualify(engine, now):
    """Tally is recorded, not required: its index is frozen and the governor
    scan covers what it would."""
    target = obs("0xt", 0, now)
    r = engine.compute_per_event("0xA", target, [target], now=now,
                                 ecosystem_proposals=[],
                                 source_receipts=healthy_receipts())
    assert r.identity.eligibility == ELIGIBLE
    assert any(x["source"] == "tally" and x["state"] == AUTH_MISSING
               for x in r.identity.source_receipts)


@pytest.mark.parametrize("state", [TRUNCATED, UNAVAILABLE, ERROR, AUTH_MISSING])
def test_required_source_in_bad_state_is_not_eligible(engine, now, state):
    receipts = healthy_receipts()
    receipts[2] = SourceReceipt("governor", state, detail="rpc")
    target = obs("0xt", 0, now)
    r = engine.compute_per_event("0xA", target, [target], now=now,
                                 ecosystem_proposals=[],
                                 source_receipts=receipts)
    assert r.identity.eligibility == NOT_ELIGIBLE
    assert any("governor" in x and state in x for x in r.identity.eligibility_reasons)


def test_partial_history_stays_eligible_and_is_counted(engine, now):
    receipts = healthy_receipts()
    receipts[2] = SourceReceipt("governor", PARTIAL, events=2, unknown_window=1)
    target = obs("0xt", 0, now)
    r = engine.compute_per_event("0xA", target, [target], now=now,
                                 ecosystem_proposals=[],
                                 source_receipts=receipts)
    assert r.identity.eligibility == ELIGIBLE


def test_healthy_empty_is_eligible(engine, now):
    receipts = healthy_receipts()
    receipts[3] = SourceReceipt("ecosystem", HEALTHY_EMPTY, events=0)
    target = obs("0xt", 0, now)
    r = engine.compute_per_event("0xA", target, [target], now=now,
                                 ecosystem_proposals=[],
                                 source_receipts=receipts)
    assert r.identity.eligibility == ELIGIBLE


def test_voted_only_fallback_is_a_different_construct_and_not_eligible(engine, now):
    """Naming the fallback in concurrency_source is transparent but does not
    make it the frozen instrument (review point 2)."""
    target = obs("0xt", 0, now)
    r = engine.compute_per_event("0xA", target, [target], now=now,
                                 ecosystem_proposals=None,
                                 source_receipts=healthy_receipts())
    assert r.metrics.concurrency_source == "voted_only"
    assert r.identity.eligibility == NOT_ELIGIBLE
    assert any("construct" in x for x in r.identity.eligibility_reasons)


def test_no_receipts_at_all_is_not_eligible(engine, now):
    target = obs("0xt", 0, now)
    r = engine.compute_per_event("0xA", target, [target], now=now, ecosystem_proposals=[])
    assert r.identity.eligibility == NOT_ELIGIBLE
    assert any("no source receipts" in x for x in r.identity.eligibility_reasons)


def test_eligibility_rules_come_from_config(engine, now):
    """logic_as_data: change the rule in the config, the verdict follows."""
    engine.config["eligibility"] = {"required_sources": ["tally"],
                                    "eligible_states": [HEALTHY_COMPLETE]}
    target = obs("0xt", 0, now)
    r = engine.compute_per_event("0xA", target, [target], now=now,
                                 ecosystem_proposals=[],
                                 source_receipts=healthy_receipts())
    assert r.identity.eligibility == NOT_ELIGIBLE
    assert any("tally" in x for x in r.identity.eligibility_reasons)


# ---------------------------------------------------------------------------
# 3. Native identity before reconciliation
# ---------------------------------------------------------------------------

def test_reconcile_keeps_latest_cast_and_records_superseded(now):
    a = obs("snap-1", 5, now, source_vote_id="v1", native_proposal_id="p1")
    b = obs("snap-2", 4, now, source_vote_id="v2", native_proposal_id="p1")
    kept, log = reconcile_observations([a, b])
    assert [k.id for k in kept] == ["snap-2"]
    assert kept[0].superseded_source_vote_ids == ["v1"]
    assert log == [{"kept": "v2", "superseded": "v1",
                    "reason": "same voter, source and native proposal id"}]


def test_reconcile_never_crosses_sources_or_voters(now):
    a = obs("snap-1", 5, now, source_vote_id="v1", native_proposal_id="p1")
    b = obs("gov-1", 4, now, source_vote_id="tx1", native_proposal_id="p1",
            source_domain="governor:core")
    c = obs("snap-9", 3, now, source_vote_id="v9", native_proposal_id="p1", voter="0xB")
    kept, log = reconcile_observations([a, b, c])
    assert len(kept) == 3 and log == []


def test_reconcile_leaves_records_without_native_id_alone(now):
    a = obs("x", 5, now)
    b = obs("y", 4, now)
    kept, log = reconcile_observations([a, b])
    assert len(kept) == 2 and log == []


def test_reconciliations_land_in_the_manifest(engine, now):
    target = obs("0xt", 0, now)
    r = engine.compute_per_event("0xA", target, [target], now=now, ecosystem_proposals=[],
                                 reconciliations=[{"kept": "v2", "superseded": "v1", "reason": "x"}])
    assert r.identity.source_state["reconciliations"][0]["superseded"] == "v1"


def test_manifest_carries_native_identity(engine, now):
    target = obs("0xt", 0, now, source_vote_id="0xdeadbeef", native_proposal_id="0xprop",
                 source_domain="governor:treasury")
    r = engine.compute_per_event("0xA", target, [target], now=now, ecosystem_proposals=[])
    m = r.identity.manifest()
    assert m["source_vote_id"] == "0xdeadbeef"
    assert m["native_proposal_id"] == "0xprop"
    assert m["source_domain"] == "governor:treasury"


# ---------------------------------------------------------------------------
# 1. Lifecycle counting on frozen observations
# ---------------------------------------------------------------------------

def test_two_stages_count_as_one_decision_at_the_first_stage(engine, now):
    """Snapshot stage 10 days ago, binding stage 2 days ago, target today.
    Volume over 7 days must NOT count the binding stage as new work."""
    a = obs("snap", 10, now, title="Same Decision")
    b = obs("gov", 2, now, title="Same Decision", source_domain="governor:core")
    t = obs("0xt", 0, now, title="Other")
    history = merge_stages([a, b, t])
    target = next(p for p in history if p.id == "0xt")
    r = engine.compute_per_event("0xA", target, history, now=now, ecosystem_proposals=[])
    assert r.metrics.proposals_7d == 1      # the target only
    assert r.metrics.proposals_30d == 2     # target + ONE decision
    assert r.identity.source_state["history_events"] == 3
    assert r.identity.source_state["history_decisions"] == 2


def test_measuring_the_first_stage_ignores_the_later_stage_entirely(engine, now):
    """as_of = t1: the later stage is not in the frozen set, its body and
    category cannot reach the measurement."""
    a = obs("snap", 10, now, title="Same Decision", body="short")
    b = obs("gov", 2, now, title="Same Decision", body="x " * 5000,
            category="protocol", source_domain="governor:core")
    history = merge_stages([a, b])
    target = next(p for p in history if p.id == "snap")
    at_t1 = datetime.fromtimestamp(target.voted_at, tz=timezone.utc)
    r = engine.compute_per_event("0xA", target, history, now=at_t1, ecosystem_proposals=[])
    assert r.metrics.avg_word_count == 1.0          # "short"
    assert r.identity.source_state["history_events"] == 1
    assert "gov" not in r.identity.context_stage_ids
    assert "gov" in r.identity.lifecycle_stage_ids   # linked, not bound


def test_first_vote_in_a_category_is_novel(engine, now):
    """Regression for the self-inclusion defect found on 2026-09-04: the target
    sat inside its own history, so a first exposure scored 0.0."""
    earlier = obs("e", 20, now, title="Grants Round", category="grants")
    target = obs("0xt", 0, now, title="Security Upgrade", category="security")
    r = engine.compute_per_event("0xA", target, [earlier, target], now=now, ecosystem_proposals=[])
    assert r.components.novelty == 1.0


def test_own_lifecycle_does_not_count_as_prior_exposure(engine, now):
    a = obs("snap", 10, now, title="Same Decision", category="security")
    b = obs("gov", 0, now, title="Same Decision", category="security",
            source_domain="governor:core")
    history = merge_stages([a, b, obs("e", 20, now, title="Grants", category="grants")])
    target = next(p for p in history if p.id == "gov")
    r = engine.compute_per_event("0xA", target, history, now=now, ecosystem_proposals=[])
    assert r.components.novelty == 1.0


# ---------------------------------------------------------------------------
# 4. Manifest and measurement identity
# ---------------------------------------------------------------------------

def test_measurement_id_is_deterministic_and_complete(engine, now):
    target = obs("0xt", 0, now)
    hist = [target, obs("h1", 3, now)]
    eco = [obs("e1", 1, now)]
    a = engine.compute_per_event("0xA", target, hist, now=now, ecosystem_proposals=eco,
                                 source_receipts=healthy_receipts())
    b = engine.compute_per_event("0xA", target, hist, now=now, ecosystem_proposals=eco,
                                 source_receipts=healthy_receipts())
    assert a.identity.measurement_id == b.identity.measurement_id
    assert len(a.identity.measurement_id) == 32


def test_measurement_id_changes_when_any_input_set_changes(engine, now):
    target = obs("0xt", 0, now)
    hist = [target, obs("h1", 3, now)]
    eco = [obs("e1", 1, now)]
    base = engine.compute_per_event("0xA", target, hist, now=now, ecosystem_proposals=eco,
                                    source_receipts=healthy_receipts())
    more_context = engine.compute_per_event("0xA", target, hist + [obs("h2", 5, now)], now=now,
                                            ecosystem_proposals=eco,
                                            source_receipts=healthy_receipts())
    more_eco = engine.compute_per_event("0xA", target, hist, now=now,
                                        ecosystem_proposals=eco + [obs("e2", 1, now)],
                                        source_receipts=healthy_receipts())
    bad_receipts = healthy_receipts()
    bad_receipts[2] = SourceReceipt("governor", ERROR, detail="500")
    worse = engine.compute_per_event("0xA", target, hist, now=now, ecosystem_proposals=eco,
                                     source_receipts=bad_receipts)
    ids = {base.identity.measurement_id, more_context.identity.measurement_id,
           more_eco.identity.measurement_id, worse.identity.measurement_id}
    assert len(ids) == 4
    # the vote-event itself did not change
    assert base.identity.vote_event_id == more_context.identity.vote_event_id


def test_manifest_lists_every_field_the_review_asks_for(engine, now):
    target = obs("0xt", 0, now, source_vote_id="v", native_proposal_id="p")
    r = engine.compute_per_event("0xA", target, [target], now=now,
                                 ecosystem_proposals=[obs("e1", 1, now)],
                                 source_receipts=healthy_receipts())
    m = r.identity.manifest()
    for key in ("vote_event_id", "source_vote_id", "lifecycle_id", "lifecycle_stage_ids",
                "voted_at", "target_content_hash", "context_stage_ids", "context_set_hash",
                "ecosystem_ids", "ecosystem_set_hash", "source_receipts",
                "instrument_hash", "instrument_version", "code_commit",
                "eligibility", "measurement_id"):
        assert key in m, key
    assert m["ecosystem_ids"] == ["e1"]
    assert m["target_content_hash"]


def test_target_content_hash_tracks_the_rated_text(engine, now):
    t1 = obs("0xt", 0, now, body="one text")
    t2 = obs("0xt", 0, now, body="another text")
    a = engine.compute_per_event("0xA", t1, [t1], now=now, ecosystem_proposals=[])
    b = engine.compute_per_event("0xA", t2, [t2], now=now, ecosystem_proposals=[])
    assert a.identity.target_content_hash != b.identity.target_content_hash
