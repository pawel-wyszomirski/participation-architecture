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
# Temporal validity: the evidence set is frozen at the target vote's timestamp
#
# Raised in the public source-level review on the forum (2026-08-03, thread
# "Participation Architecture - Final Grant Report"). The context windows were
# computed from `proposal.start`, but the delegate may have voted on that
# proposal days later, so a proposal opened before the target vote could enter
# the target's history even though the vote had not been cast yet. The
# invariant to hold:
#
#     same target event + same evidence available at target time
#     + same instrument version = same measurement forever
# ---------------------------------------------------------------------------

@dataclass
class MockVote:
    """A proposal the delegate voted on. `start`/`end` describe the proposal,
    `voted_at` describes the delegate's own act of voting - in practice the two
    differ by days, which is what these tests are about."""
    start: int
    end: int
    voted_at: int
    body: str = "routine monthly report"
    title: str = "Test Proposal"
    state: str = "closed"


def cast(now: datetime, started_days_ago: float, voted_days_ago: float,
         open_for_days: float = 3.0) -> MockVote:
    """One vote positioned relative to the target vote. A negative
    `voted_days_ago` places the vote AFTER the target."""
    start = now - timedelta(days=started_days_ago)
    return MockVote(
        start=int(start.timestamp()),
        end=int((start + timedelta(days=open_for_days)).timestamp()),
        voted_at=int((now - timedelta(days=voted_days_ago)).timestamp()),
    )


def test_later_vote_on_earlier_proposal_leaves_frozen_measurement_intact(engine, now):
    """Proposal B opens BEFORE the target vote, but the delegate votes on it
    five days AFTER. Adding that vote must not move the target's measurement."""
    at_target = [
        cast(now, started_days_ago=2, voted_days_ago=2),
        cast(now, started_days_ago=10, voted_days_ago=9),
    ]
    cast_later = cast(now, started_days_ago=1, voted_days_ago=-5)

    frozen = engine.compute_per_event("0xA", proposal(), at_target, now=now)
    recomputed = engine.compute_per_event(
        "0xA", proposal(), at_target + [cast_later], now=now
    )

    assert recomputed.fatigue_score == frozen.fatigue_score
    assert recomputed.components == frozen.components
    assert recomputed.metrics.proposals_7d == frozen.metrics.proposals_7d


def test_window_counts_the_vote_not_the_proposal_start(engine, now):
    """A proposal opened 40 days before the target but voted on 3 days before it
    belongs INSIDE the 7-day window. Counting by proposal start drops it out of
    both windows and understates the delegate's workload."""
    late_vote_on_old_proposal = cast(
        now, started_days_ago=40, voted_days_ago=3, open_for_days=45
    )
    r = engine.compute_per_event("0xA", proposal(), [late_vote_on_old_proposal], now=now)

    assert r.metrics.proposals_7d == 1
    assert r.metrics.proposals_30d == 1


def test_vote_after_target_is_excluded_from_every_window(engine, now):
    """A vote cast after the target counts nowhere, whatever the proposal's own
    timing."""
    r = engine.compute_per_event(
        "0xA", proposal(), [cast(now, started_days_ago=3, voted_days_ago=-1)], now=now
    )

    assert r.metrics.proposals_7d == 0
    assert r.metrics.proposals_30d == 0
    assert r.metrics.concurrent_active == 0
    assert r.components.volume == 0.0


def test_proposal_without_known_window_is_skipped_not_counted(engine, now):
    """Źródło, które nie podaje końca propozycji, nie może uchodzić za źródło
    mówiące „nic się nie nakładało". Do 2026-08-05 brak końca wypadał ze
    współbieżności przez `or 0`, czyli przez przypadek, a nie z decyzji."""
    bez_konca = cast(now, started_days_ago=1, voted_days_ago=1)
    bez_konca.end = None
    z_koncem = cast(now, started_days_ago=1, voted_days_ago=1, open_for_days=5)

    tylko_bez = engine.compute_per_event("0xA", proposal(), [bez_konca], now=now)
    z_oknem = engine.compute_per_event("0xA", proposal(), [z_koncem], now=now)

    assert tylko_bez.metrics.concurrent_active == 0
    assert z_oknem.metrics.concurrent_active == 1


def test_concurrency_still_uses_proposal_timing(engine, now):
    """Concurrency is a proposal-time concept - how many decisions stood open
    around the delegate at the target moment. It keeps using start/end; only the
    freezing rule (vote already cast) is added."""
    open_at_target = cast(now, started_days_ago=1, voted_days_ago=1, open_for_days=5)
    already_closed = cast(now, started_days_ago=20, voted_days_ago=19, open_for_days=2)
    r = engine.compute_per_event(
        "0xA", proposal(), [open_at_target, already_closed], now=now
    )

    assert r.metrics.concurrent_active == 1


def test_history_without_vote_time_falls_back_to_proposal_start(engine, now):
    """Sources that carry no vote timestamp must keep working - the ecosystem
    variant passes proposals with `start` only."""
    r = engine.compute_per_event("0xA", proposal(), history(now, [2]), now=now)

    assert r.metrics.proposals_7d == 1


# ---------------------------------------------------------------------------
# Regression: ecosystem variant untouched
# ---------------------------------------------------------------------------

def test_ecosystem_variant_unchanged(engine, now):
    props = history(now, [1, 3, 5, 7, 9])
    a = engine.compute("0xAAA", props, now=now)
    b = engine.compute("0xBBB", props, now=now)
    assert a.fatigue_score == b.fatigue_score
    assert a.mode == "ecosystem"
