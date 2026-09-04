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


# ---------------------------------------------------------------------------
# Point 3 of the grant review (Arb_Junior, /t/30604 post 18, 2026-08-27):
# separate ECOSYSTEM GOVERNANCE LOAD (all proposals open at time t) from the
# delegate's REVEALED ENGAGEMENT (votes actually cast by that address).
#
# Until 2026-08-28 concurrency counted only proposals the delegate voted on,
# so it measured a slice of the delegate's own activity and called it parallel
# decision pressure. The corpus diagnostic showed the symptom: the component
# moved in a band of 1-2 proposals (0.083-0.167) across 239 events.
# ---------------------------------------------------------------------------

def eco(now: datetime, started_days_ago: float, open_for_days: float = 7.0) -> MockProposal:
    """A proposal open in the space around the target moment - the delegate may
    never have voted on it. That is the point."""
    start = now - timedelta(days=started_days_ago)
    return MockProposal(
        start=int(start.timestamp()),
        end=int((start + timedelta(days=open_for_days)).timestamp()),
    )


def test_ecosystem_proposals_drive_concurrency(engine, now):
    """With the ecosystem list supplied, concurrency counts ALL proposals open
    at t - including ones the delegate never touched."""
    voted = [cast(now, started_days_ago=2, voted_days_ago=2)]
    ecosystem = [eco(now, 1), eco(now, 3), eco(now, 5), eco(now, 40, open_for_days=2)]

    r = engine.compute_per_event("0xA", proposal(), voted, now=now,
                                 ecosystem_proposals=ecosystem)

    assert r.metrics.concurrent_active == 3   # the 40-days-ago one is closed
    assert r.metrics.concurrency_source == "ecosystem:snapshot"


def test_without_ecosystem_list_old_behaviour_and_source_named(engine, now):
    """No ecosystem list = the pre-2026-08-28 construction, and the result SAYS
    so instead of passing the narrower number off as ecosystem load."""
    voted = [cast(now, started_days_ago=1, voted_days_ago=1, open_for_days=5)]

    r = engine.compute_per_event("0xA", proposal(), voted, now=now)

    assert r.metrics.concurrent_active == 1
    assert r.metrics.concurrency_source == "voted_only"


def test_revealed_engagement_reported_alongside_ecosystem_load(engine, now):
    """The two quantities the reviewer asks to separate are BOTH in the result:
    concurrent_active carries the ecosystem load, voted_concurrent carries what
    the delegate's own votes show at t."""
    voted = [cast(now, started_days_ago=1, voted_days_ago=1, open_for_days=5)]
    ecosystem = [eco(now, 1), eco(now, 2), eco(now, 3)]

    r = engine.compute_per_event("0xA", proposal(), voted, now=now,
                                 ecosystem_proposals=ecosystem)

    assert r.metrics.concurrent_active == 3
    assert r.metrics.voted_concurrent == 1


def test_ecosystem_proposal_without_end_is_skipped(engine, now):
    """An ecosystem proposal with an unknown window must not be counted - the
    same rule the voted history already follows."""
    bez_konca = eco(now, 1)
    bez_konca.end = None

    r = engine.compute_per_event("0xA", proposal(),
                                 [cast(now, started_days_ago=2, voted_days_ago=2)],
                                 now=now, ecosystem_proposals=[bez_konca, eco(now, 2)])

    assert r.metrics.concurrent_active == 1


def test_empty_ecosystem_list_is_a_measurement_not_a_fallback(engine, now):
    """An empty list is a real answer (nothing was open at t) and keeps the
    ecosystem source label. Only None means 'source unavailable'."""
    voted = [cast(now, started_days_ago=1, voted_days_ago=1, open_for_days=5)]

    r = engine.compute_per_event("0xA", proposal(), voted, now=now,
                                 ecosystem_proposals=[])

    assert r.metrics.concurrent_active == 0
    assert r.metrics.concurrency_source == "ecosystem:snapshot"


def test_ecosystem_list_does_not_touch_volume_or_burstiness(engine, now):
    """Volume and burstiness stay on the delegate's own votes - that is the
    revealed-engagement side of the separation."""
    voted = [cast(now, started_days_ago=2, voted_days_ago=2),
             cast(now, started_days_ago=9, voted_days_ago=8)]
    bez = engine.compute_per_event("0xA", proposal(), voted, now=now)
    z_eco = engine.compute_per_event("0xA", proposal(), voted, now=now,
                                     ecosystem_proposals=[eco(now, 1), eco(now, 2)])

    assert z_eco.metrics.proposals_7d == bez.metrics.proposals_7d
    assert z_eco.metrics.proposals_30d == bez.metrics.proposals_30d
    assert z_eco.components.volume == bez.components.volume
    assert z_eco.components.burstiness == bez.components.burstiness


# ---------------------------------------------------------------------------
# Point 4 of the grant review (/t/30604 post 18): each result must bind a
# unique vote-event identity (not only the proposal id), plus instrument
# version, code commit, and source-capability state including unknown windows.
# ---------------------------------------------------------------------------

def test_identity_present_and_deterministic(engine, now):
    voted = [cast(now, started_days_ago=2, voted_days_ago=2)]
    a = engine.compute_per_event("0xA", proposal(), voted, now=now)
    b = engine.compute_per_event("0xA", proposal(), voted, now=now)

    assert a.identity is not None
    assert a.identity.vote_event_id
    assert a.identity.vote_event_id == b.identity.vote_event_id
    assert a.identity.instrument_version == engine.version


def test_identity_differs_between_events_and_addresses(engine, now):
    voted = [cast(now, started_days_ago=2, voted_days_ago=2)]
    t1 = proposal(words=100, title="Alpha")
    t2 = proposal(words=100, title="Beta")
    t2.start = t1.start - 86_400  # inny moment

    a = engine.compute_per_event("0xA", t1, voted, now=now)
    b = engine.compute_per_event("0xA", t2, voted, now=now)
    c = engine.compute_per_event("0xB", t1, voted, now=now)

    assert a.identity.vote_event_id != b.identity.vote_event_id
    assert a.identity.vote_event_id != c.identity.vote_event_id


def test_identity_names_one_vote_and_links_its_lifecycle(engine, now):
    """Closure review 2026-09-03, point 1: the identity is ONE concrete vote.
    Other stages of the same decision are linked through the lifecycle, never
    bound into the id - so the same vote keeps the same id whether or not a
    later stage has been observed yet."""
    t = MockVote(start=int((now - timedelta(days=2)).timestamp()),
                 end=int((now - timedelta(days=1)).timestamp()),
                 voted_at=int((now - timedelta(days=2)).timestamp()))
    t.id = "snap-1"
    t.lifecycle_id = "lc:abc"
    t.lifecycle_stage_ids = ["snap-1", "chain-7"]
    samotny = MockVote(start=t.start, end=t.end, voted_at=t.voted_at)
    samotny.id = "snap-1"

    z_cyklem = engine.compute_per_event("0xA", t, [t], now=now)
    bez = engine.compute_per_event("0xA", samotny, [samotny], now=now)

    assert z_cyklem.identity.vote_event_id == bez.identity.vote_event_id
    assert z_cyklem.identity.stage_ids == ["snap-1"]
    assert z_cyklem.identity.lifecycle_id == "lc:abc"
    assert "chain-7" in z_cyklem.identity.lifecycle_stage_ids


def test_source_state_counts_unknown_windows(engine, now):
    bez_okna = cast(now, started_days_ago=3, voted_days_ago=3)
    bez_okna.end = None
    pelne = cast(now, started_days_ago=2, voted_days_ago=2)

    r = engine.compute_per_event("0xA", proposal(), [bez_okna, pelne], now=now)

    assert r.identity.source_state["history_events"] == 2
    assert r.identity.source_state["events_unknown_window"] == 1
    assert r.identity.source_state["concurrency_source"] == "voted_only"


def test_source_state_passes_endpoint_supplied_sources(engine, now):
    voted = [cast(now, started_days_ago=2, voted_days_ago=2)]
    r = engine.compute_per_event(
        "0xA", proposal(), voted, now=now,
        source_counts={"snapshot": 5, "tally": 0, "governor": 2},
    )
    assert r.identity.source_state["sources"] == {"snapshot": 5, "tally": 0, "governor": 2}


def test_merge_stages_collects_stage_ids(now):
    from app.services.fatigue_engine import merge_stages
    a = MockVote(start=int((now - timedelta(days=10)).timestamp()),
                 end=int((now - timedelta(days=7)).timestamp()),
                 voted_at=int((now - timedelta(days=10)).timestamp()),
                 title="Same Decision")
    a.id = "snap-A"
    b = MockVote(start=int((now - timedelta(days=8)).timestamp()),
                 end=int((now - timedelta(days=5)).timestamp()),
                 voted_at=int((now - timedelta(days=8)).timestamp()),
                 title="Same Decision")
    b.id = "chain-B"

    etapy = merge_stages([a, b])

    assert len(etapy) == 2, "each stage stays a frozen observation"
    assert {e.lifecycle_id for e in etapy} == {etapy[0].lifecycle_id}
    assert sorted(etapy[0].lifecycle_stage_ids) == ["chain-B", "snap-A"]
    assert all(e.stages == 2 for e in etapy)
    assert all(e.stage_ids == [e.id] for e in etapy)
