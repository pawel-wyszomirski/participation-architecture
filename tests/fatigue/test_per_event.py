"""
Unit tests for FatigueEngine.compute_per_event (per-event DFI).

Dissertation grounding: section 5.3.5a + per-event pivot 2026-05-11. The unit
of analysis is a single vote, not a 30-day aggregate (NASA-TLX is task-specific,
validated only to ~24h - Hernandez 2021). Between-event variance comes mainly
from the intrinsic load of the voted proposal (length, novelty); the context
components (volume/concurrency/burstiness) come from the delegate's history.

Run with: pytest tests/fatigue/test_per_event.py -v
"""

import pytest
import sys
import os
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import FatigueEngine


@dataclass
class MockProposal:
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
    eng.config.setdefault(
        "reference_values_per_event",
        {"volume_7d": 1, "volume_30d": 3, "concurrent": 2, "reading_words": 1500},
    )
    return eng


def history(now: datetime, days_ago_list) -> list:
    """Delegate's voting history: proposals voted on, each starting `days_ago`."""
    out = []
    for d in days_ago_list:
        start = int((now - timedelta(days=d)).timestamp())
        end = int((now - timedelta(days=d) + timedelta(days=3)).timestamp())
        out.append(MockProposal(start=start, end=end, body="routine monthly report"))
    return out


def proposal(words: int = 1000, title="Proposal", body_extra="") -> MockProposal:
    """A target proposal of a given length."""
    return MockProposal(start=0, end=0, title=title, body=("word " * words) + body_extra)


# ---------------------------------------------------------------------------
# Core: between-event variance comes from the voted proposal (length, novelty)
# ---------------------------------------------------------------------------

def test_variance_from_proposal_length(engine, now):
    """Same delegate, same context - different proposal length => different DFI.
    This is the main source of per-event variance."""
    hist = history(now, [1, 5, 12])
    short = engine.compute_per_event("0xA", proposal(words=150), hist, now=now)
    long = engine.compute_per_event("0xA", proposal(words=3000), hist, now=now)
    assert short.fatigue_score < long.fatigue_score
    assert short.components.reading_time < long.components.reading_time


def test_variance_from_novelty(engine, now):
    """A novel-domain proposal scores higher on novelty than a routine one."""
    hist = history(now, [1, 5])
    routine = engine.compute_per_event(
        "0xA", proposal(words=1000, title="Monthly transparency report"), hist, now=now
    )
    novel = engine.compute_per_event(
        "0xA", proposal(words=1000, title="Emergency security council exploit response"), hist, now=now
    )
    assert novel.components.novelty == 1.0
    assert routine.components.novelty == 0.0
    assert novel.fatigue_score > routine.fatigue_score


def test_context_from_history(engine, now):
    """Same proposal, different delegate context (light vs heavy recent voting)
    => different volume/burstiness => different DFI."""
    p = proposal(words=1000)
    light = engine.compute_per_event("0xA", p, history(now, [2]), now=now)            # 1 recent vote
    heavy = engine.compute_per_event("0xB", p, history(now, [0, 1, 2, 3, 4, 6]), now=now)  # 6 recent
    assert light.fatigue_score != heavy.fatigue_score


def test_deterministic(engine, now):
    p = proposal(words=1200)
    hist = history(now, [1, 4, 9])
    a = engine.compute_per_event("0xA", p, hist, now=now)
    b = engine.compute_per_event("0xA", p, hist, now=now)
    assert a.fatigue_score == b.fatigue_score
    assert a.components == b.components


def test_mode_flag(engine, now):
    r = engine.compute_per_event("0xA", proposal(), history(now, [1]), now=now)
    assert r.mode == "per_event"


def test_empty_history_still_scores_proposal(engine, now):
    """A delegate with no recorded history still gets reading_time/novelty from
    the voted proposal; context components are zero."""
    r = engine.compute_per_event("0xA", proposal(words=3000), [], now=now)
    assert r.components.reading_time > 0.0      # from the proposal
    assert r.components.volume == 0.0           # no context
    assert r.fatigue_score > 0.0


def test_avg_word_count_reflects_target(engine, now):
    """metrics.avg_word_count must reflect THE voted proposal, not history."""
    r = engine.compute_per_event("0xA", proposal(words=500), history(now, [1, 2]), now=now)
    assert r.metrics.avg_word_count == 500.0


# ---------------------------------------------------------------------------
# Regression: ecosystem variant untouched
# ---------------------------------------------------------------------------

def test_ecosystem_variant_unchanged(engine, now):
    props = history(now, [1, 3, 5, 7, 9])
    a = engine.compute("0xAAA", props, now=now)
    b = engine.compute("0xBBB", props, now=now)
    assert a.fatigue_score == b.fatigue_score
    assert a.mode == "ecosystem"
