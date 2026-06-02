"""
Unit tests for FatigueEngine.compute_per_delegate (per-delegate DFI).

Dissertation grounding: section 5.3.5a (per-delegate operationalization of
the Delegate Fatigue Index, Cognitive Load Theory). The whole point of the
per-delegate variant is to produce BETWEEN-DELEGATE VARIANCE, which the
ecosystem variant lacks by construction (audit 2026-06-01, blocker #1:
zero variance -> Spearman undefined).

Run with: pytest tests/fatigue/test_per_delegate.py -v
"""

import pytest
import sys
import os
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import FatigueEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class MockProposal:
    """Minimal mock of the Proposal ORM model (a proposal a delegate voted on)."""
    start: int
    end: int
    body: str = ""
    title: str = "Test Proposal"
    state: str = "closed"


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    eng = FatigueEngine("fatigue_config.yaml")
    # Make the test independent of config file resolution: ensure the
    # per-delegate references exist even if _default_config kicked in.
    eng.config.setdefault(
        "reference_values_per_delegate",
        {"volume_7d": 3, "volume_30d": 12, "concurrent": 3, "reading_words": 3000},
    )
    return eng


def voted(now: datetime, days_ago_list, body: str = "routine monthly report") -> list:
    """Build a list of proposals the delegate voted on, each starting
    `days_ago` before `now` and lasting 3 days."""
    out = []
    for d in days_ago_list:
        start = int((now - timedelta(days=d)).timestamp())
        end = int((now - timedelta(days=d) + timedelta(days=3)).timestamp())
        out.append(MockProposal(start=start, end=end, body=body))
    return out


# ---------------------------------------------------------------------------
# Core property: BETWEEN-DELEGATE VARIANCE (resolves audit blocker #1)
# ---------------------------------------------------------------------------

def test_per_delegate_produces_variance_between_delegates(engine, now):
    """Three delegates with different voting activity must get different DFI.
    This is the whole reason the per-delegate variant exists."""
    light = engine.compute_per_delegate("0xLIGHT", voted(now, [2, 20]), now=now)            # 2 votes
    medium = engine.compute_per_delegate("0xMED", voted(now, [1, 3, 5, 9, 15, 22]), now=now) # 6 votes
    heavy = engine.compute_per_delegate(
        "0xHEAVY", voted(now, [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 22, 26]), now=now     # 14 votes
    )

    scores = {light.fatigue_score, medium.fatigue_score, heavy.fatigue_score}
    # Variance > 0: not all equal (the ecosystem variant would return one value)
    assert len(scores) == 3, f"expected 3 distinct scores, got {scores}"
    # Monotonic: more voting activity -> higher load
    assert light.fatigue_score < medium.fatigue_score < heavy.fatigue_score


def test_per_delegate_zero_when_no_votes(engine, now):
    """A delegate who voted on nothing in the window has zero load."""
    result = engine.compute_per_delegate("0xIDLE", [], now=now)
    assert result.fatigue_score == 0.0
    assert result.status == "LOW"


def test_per_delegate_deterministic(engine, now):
    """Same input -> same output (reproducibility, grant KPI)."""
    props = voted(now, [1, 4, 9, 16])
    a = engine.compute_per_delegate("0xABC", props, now=now)
    b = engine.compute_per_delegate("0xABC", props, now=now)
    assert a.fatigue_score == b.fatigue_score
    assert a.components == b.components


def test_per_delegate_mode_flag(engine, now):
    """Result must be tagged as per_delegate so callers/snapshots can tell
    the two variants apart."""
    result = engine.compute_per_delegate("0xABC", voted(now, [1, 2, 3]), now=now)
    assert result.mode == "per_delegate"


def test_per_delegate_address_is_used_not_ignored(engine, now):
    """Contrast with the ecosystem variant: here the delegate's own activity
    drives the score. Two delegates with different activity differ; the
    address field is carried through."""
    a = engine.compute_per_delegate("0xAAA", voted(now, [1]), now=now)
    b = engine.compute_per_delegate("0xBBB", voted(now, [1, 2, 3, 4, 5, 6, 7, 8]), now=now)
    assert a.address == "0xAAA"
    assert b.address == "0xBBB"
    assert a.fatigue_score != b.fatigue_score


# ---------------------------------------------------------------------------
# Regression: the ecosystem variant must stay unchanged (address-independent)
# ---------------------------------------------------------------------------

def test_ecosystem_variant_still_address_independent(engine, now):
    """compute() (ecosystem) must remain shared-burden: same proposals ->
    same score regardless of address. We did not break the grant deliverable."""
    props = voted(now, [1, 3, 5, 7, 9])
    a = engine.compute("0xAAA", props, now=now)
    b = engine.compute("0xBBB", props, now=now)
    assert a.fatigue_score == b.fatigue_score
    assert a.mode == "ecosystem"
