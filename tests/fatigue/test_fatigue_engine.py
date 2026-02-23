"""
Unit Tests for FatigueEngine (DFI - Delegate Fatigue Index)

Tests cover:
- Zero-load baseline (empty ecosystem)
- Individual component isolation
- Score determinism (same input -> same output)
- Status thresholds (LOW / MODERATE / HIGH / CRITICAL)
- Burstiness spike detection
- Novelty ratio classification
- Edge cases (single proposal, very long proposal, all concurrent)
- Config injection for reproducible results

Run with: pytest tests/fatigue/test_fatigue_engine.py -v
"""

import pytest
import sys
import os
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import FatigueEngine, FatigueResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class MockProposal:
    """Minimal mock of the Proposal ORM model."""
    start: int
    end: int
    body: str = ""
    title: str = "Test Proposal"
    state: str = "active"


def ts(ref: datetime, days_ago: int = 0, days_ahead: int = 0) -> int:
    """Return a Unix timestamp relative to ref datetime."""
    delta = timedelta(days=days_ago) if days_ago else timedelta(days=-days_ahead)
    return int((ref - delta).timestamp())


def make_proposal(
    ref: datetime,
    started_days_ago: int,
    duration_days: int = 7,
    body: str = "standard proposal body",
    title: str = "Test Proposal",
) -> MockProposal:
    start = ts(ref, days_ago=started_days_ago)
    end = start + duration_days * 86_400
    return MockProposal(start=start, end=end, body=body, title=title)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    """FatigueEngine loaded from the project fatigue_config.yaml."""
    return FatigueEngine("fatigue_config.yaml")


@pytest.fixture
def now() -> datetime:
    """Fixed reference time for all tests."""
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# TEST: Initialization
# ---------------------------------------------------------------------------

def test_engine_loads_config(engine):
    info = engine.get_config_info()
    assert info["version"] == "1.0.0"
    weights = info["weights"]
    assert abs(sum(weights.values()) - 1.0) < 0.01, "Weights must sum to 1.0"


def test_engine_formula_string(engine):
    assert "DFI" in FatigueEngine.FORMULA
    assert "volume" in FatigueEngine.FORMULA


# ---------------------------------------------------------------------------
# TEST: Zero-load baseline
# ---------------------------------------------------------------------------

def test_zero_load_empty_proposals(engine, now):
    """No proposals -> score = 0, status = LOW."""
    result = engine.compute("0xtest", proposals=[], now=now)
    assert result.fatigue_score == 0.0
    assert result.status == "LOW"
    assert result.metrics.proposals_7d == 0
    assert result.metrics.proposals_30d == 0
    assert result.metrics.concurrent_active == 0


def test_zero_load_old_proposals(engine, now):
    """Proposals older than 30d should not affect 7d/30d metrics."""
    old = [make_proposal(now, started_days_ago=45) for _ in range(20)]
    result = engine.compute("0xtest", proposals=old, now=now)
    assert result.metrics.proposals_30d == 0
    assert result.metrics.proposals_7d == 0


# ---------------------------------------------------------------------------
# TEST: Volume component
# ---------------------------------------------------------------------------

def test_volume_at_reference_produces_moderate_component(engine, now):
    """5 proposals in last 7d (= ref_7d) -> component ~0.5."""
    props = [make_proposal(now, started_days_ago=i) for i in range(1, 6)]
    result = engine.compute("0xtest", proposals=props, now=now)
    # v7 = 5/5 = 1.0, /2 = 0.5; v30 = 5/20 = 0.25, /2 = 0.125
    # volume = 0.6*0.5 + 0.4*0.125 = 0.35
    assert 0.3 <= result.components.volume <= 0.5


def test_volume_above_reference_capped_at_one(engine, now):
    """20 proposals in 7d (4× ref_7d) -> volume component capped at 1.0."""
    props = [make_proposal(now, started_days_ago=i % 6 + 1) for i in range(20)]
    result = engine.compute("0xtest", proposals=props, now=now)
    assert result.components.volume <= 1.0
    assert result.components.volume > 0.5


# ---------------------------------------------------------------------------
# TEST: Concurrency component
# ---------------------------------------------------------------------------

def test_concurrency_all_active(engine, now):
    """5 proposals all currently active (start < now < end) -> concurrency ~ 0.5."""
    now_ts = int(now.timestamp())
    props = [
        MockProposal(
            start=now_ts - 86_400,      # started 1 day ago
            end=now_ts + 3 * 86_400,    # ends in 3 days
        )
        for _ in range(5)
    ]
    result = engine.compute("0xtest", proposals=props, now=now)
    assert result.metrics.concurrent_active == 5
    # 5/5 = 1.0, /2 = 0.5
    assert abs(result.components.concurrency - 0.5) < 0.01


def test_concurrency_zero_when_all_closed(engine, now):
    """Proposals all ended before now -> concurrency = 0."""
    now_ts = int(now.timestamp())
    props = [
        MockProposal(
            start=now_ts - 10 * 86_400,
            end=now_ts - 2 * 86_400,    # ended 2 days ago
        )
        for _ in range(10)
    ]
    result = engine.compute("0xtest", proposals=props, now=now)
    assert result.metrics.concurrent_active == 0
    assert result.components.concurrency == 0.0


# ---------------------------------------------------------------------------
# TEST: Burstiness component
# ---------------------------------------------------------------------------

def test_burstiness_zero_when_volume_at_average(engine, now):
    """Steady 4-week rhythm (same proposals/week) -> burstiness = 0."""
    # 4 proposals/week for 4 weeks = 16 total, this week = 4 -> no spike
    props = []
    for week in range(4):
        for day in range(4):
            props.append(make_proposal(now, started_days_ago=week * 7 + day + 1))
    result = engine.compute("0xtest", proposals=props, now=now)
    # weekly_avg = 16/4.33 ≈ 3.7, proposals_7d = 4
    # burst_ratio = 4/3.7 ≈ 1.08 -> just above 1, burstiness ≈ 0.04
    assert result.components.burstiness < 0.1


def test_burstiness_high_on_spike(engine, now):
    """Only proposals in last 7d, nothing before -> maximum spike."""
    props = [make_proposal(now, started_days_ago=i) for i in range(1, 11)]
    result = engine.compute("0xtest", proposals=props, now=now)
    # proposals_30d = 10, weekly_avg = 10/4.33 ≈ 2.31, proposals_7d = 10
    # burst_ratio = 10/2.31 ≈ 4.3 -> very high
    assert result.components.burstiness > 0.5


# ---------------------------------------------------------------------------
# TEST: Reading time component
# ---------------------------------------------------------------------------

def test_reading_time_zero_for_empty_body(engine, now):
    props = [MockProposal(
        start=int((now - timedelta(days=2)).timestamp()),
        end=int((now + timedelta(days=5)).timestamp()),
        body=""
    )]
    result = engine.compute("0xtest", proposals=props, now=now)
    assert result.components.reading_time == 0.0


def test_reading_time_moderate_at_reference_length(engine, now):
    """3000-word body (= reference) -> reading_time component ~ 0.5."""
    body = "word " * 3000
    props = [make_proposal(now, started_days_ago=3, body=body)]
    result = engine.compute("0xtest", proposals=props, now=now)
    # avg_word_count ≈ 3000, ref = 3000, score = 3000/3000 = 1.0, /2 = 0.5
    assert abs(result.components.reading_time - 0.5) < 0.05


def test_reading_time_capped_for_very_long_proposal(engine, now):
    """Very long proposal (6000+ words) -> reading_time capped at 1.0."""
    body = "word " * 6500
    props = [make_proposal(now, started_days_ago=3, body=body)]
    result = engine.compute("0xtest", proposals=props, now=now)
    assert result.components.reading_time == 1.0


# ---------------------------------------------------------------------------
# TEST: Novelty component
# ---------------------------------------------------------------------------

def test_novelty_zero_for_routine_proposals(engine, now):
    """All proposals contain only routine keywords -> novelty = 0."""
    props = [
        make_proposal(now, started_days_ago=i,
                      body="monthly report and transparency update",
                      title="Quarterly Report")
        for i in range(1, 6)
    ]
    result = engine.compute("0xtest", proposals=props, now=now)
    assert result.metrics.novelty_ratio == 0.0
    assert result.components.novelty == 0.0


def test_novelty_nonzero_for_novel_proposals(engine, now):
    """Proposals with exploit/security keywords -> novelty > 0."""
    props = [
        make_proposal(now, started_days_ago=i,
                      body="active exploit detected draining funds emergency pause",
                      title="Security Incident")
        for i in range(1, 4)
    ]
    result = engine.compute("0xtest", proposals=props, now=now)
    assert result.metrics.novelty_ratio > 0.0
    assert result.components.novelty > 0.0


def test_novelty_zero_for_novel_and_routine_mixed(engine, now):
    """Novel keywords + routine keywords in same proposal -> NOT counted as novel."""
    p = make_proposal(
        now, started_days_ago=2,
        body="monthly report on the security upgrade progress",
        title="Report"
    )
    result = engine.compute("0xtest", proposals=[p], now=now)
    assert result.metrics.novelty_ratio == 0.0


# ---------------------------------------------------------------------------
# TEST: Status thresholds
# ---------------------------------------------------------------------------

def test_status_low_on_zero_load(engine, now):
    result = engine.compute("0x0", proposals=[], now=now)
    assert result.status == "LOW"


def test_status_critical_on_extreme_load(engine, now):
    """Massive concurrent spike of long novel proposals -> CRITICAL."""
    now_ts = int(now.timestamp())
    body = ("exploit " + "word ") * 2000  # long + novel
    props = [
        MockProposal(
            start=now_ts - 86_400,
            end=now_ts + 86_400,
            body=body,
            title="Security exploit emergency pause upgrade",
        )
        for _ in range(30)
    ]
    result = engine.compute("0xtest", proposals=props, now=now)
    assert result.status == "CRITICAL"
    assert result.fatigue_score >= 85


# ---------------------------------------------------------------------------
# TEST: Determinism
# ---------------------------------------------------------------------------

def test_same_input_same_output(engine, now):
    """Running compute twice on identical input must return identical output."""
    props = [
        make_proposal(now, started_days_ago=i, body="protocol upgrade hard fork")
        for i in range(1, 8)
    ]
    r1 = engine.compute("0xtest", proposals=props, now=now)
    r2 = engine.compute("0xtest", proposals=props, now=now)

    assert r1.fatigue_score == r2.fatigue_score
    assert r1.status == r2.status
    assert r1.components.volume == r2.components.volume
    assert r1.components.concurrency == r2.components.concurrency
    assert r1.components.burstiness == r2.components.burstiness
    assert r1.components.reading_time == r2.components.reading_time
    assert r1.components.novelty == r2.components.novelty


def test_address_does_not_affect_score(engine, now):
    """Score is ecosystem-level: different address -> same score."""
    props = [make_proposal(now, started_days_ago=i) for i in range(1, 5)]
    r1 = engine.compute("0xalice", proposals=props, now=now)
    r2 = engine.compute("0xbob",   proposals=props, now=now)
    assert r1.fatigue_score == r2.fatigue_score


# ---------------------------------------------------------------------------
# TEST: Result structure
# ---------------------------------------------------------------------------

def test_result_contains_all_fields(engine, now):
    props = [make_proposal(now, started_days_ago=3)]
    result = engine.compute("0xtest", proposals=props, now=now)

    assert isinstance(result.fatigue_score, float)
    assert 0.0 <= result.fatigue_score <= 100.0
    assert result.status in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    assert result.config_version == "1.0.0"
    assert result.computed_at == now
    assert result.address == "0xtest"
    assert all(
        0.0 <= v <= 1.0
        for v in [
            result.components.volume,
            result.components.concurrency,
            result.components.burstiness,
            result.components.reading_time,
            result.components.novelty,
        ]
    )


def test_result_weights_match_config(engine, now):
    """Weights in result must match what's in config."""
    result = engine.compute("0x0", proposals=[], now=now)
    assert result.weights["volume"] == 0.40
    assert result.weights["concurrency"] == 0.25
    assert result.weights["burstiness"] == 0.20
    assert result.weights["reading_time"] == 0.10
    assert result.weights["novelty"] == 0.05


# ---------------------------------------------------------------------------
# TEST: Edge cases
# ---------------------------------------------------------------------------

def test_single_proposal(engine, now):
    """Single proposal should not crash and should return a valid result."""
    result = engine.compute("0xtest", proposals=[make_proposal(now, started_days_ago=1)], now=now)
    assert result is not None
    assert 0.0 <= result.fatigue_score <= 100.0


def test_proposal_starting_right_now(engine, now):
    """Proposal that just started (start = now) should count."""
    now_ts = int(now.timestamp())
    p = MockProposal(start=now_ts, end=now_ts + 7 * 86_400, body="")
    result = engine.compute("0xtest", proposals=[p], now=now)
    assert result.metrics.proposals_7d == 1


def test_proposal_ending_right_now_not_concurrent(engine, now):
    """Proposal where end == now is still counted as concurrent (start <= now <= end)."""
    now_ts = int(now.timestamp())
    p = MockProposal(start=now_ts - 7 * 86_400, end=now_ts, body="")
    result = engine.compute("0xtest", proposals=[p], now=now)
    assert result.metrics.concurrent_active == 1


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
