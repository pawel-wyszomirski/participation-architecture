"""Canonical Arbitrum proposal record from arbdata.com (Entropy Advisors).

<!-- catalog-read --> checked app/services: snapshot_client, tally_client and
governor_client all read votes; none carries an authoritative proposal registry
with voting windows.

Why this exists
---------------
A delegate pointed at this source during a research session: it is what the DAO
itself uses. Two things it settles that the contract scan cannot.

1. REAL VOTING WINDOWS. `ProposalCreated` carries startBlock and endBlock as
   ETHEREUM block numbers, so governor_client reconstructs the window
   arithmetically at 12 s per block. Checked against ArbOS61: the arithmetic
   ends the vote on 2026-07-30, the registry says 2026-08-01. Two days off, and
   the error grows with the voting period. Concurrency asks whether decisions
   overlapped, so a two-day error moves real counts.

2. COVERAGE. The registry holds 89 proposals across two governors - 31 core and
   58 treasury. governor_client scans the core contract only, so two thirds of
   the DAO's proposals are invisible to the index. A delegate voting on treasury
   business carries load that the measurement cannot see.

`proposal_id` is the same integer that governor_client decodes from the event
payload, so the join needs no mapping table.

What this is NOT
----------------
Not a vote source. It says which proposals existed and when they were open; who
voted still comes from Snapshot and from the chain. Treasury VOTES additionally
need a scan of the treasury governor contract, which this module does not do.

A third party can go stale exactly the way Tally did, and a stale registry
answers HTTP 200 like a fresh one. `freshest()` exposes the newest record so a
caller can compare it against what the chain reports rather than trusting the
response code.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional, Tuple

import httpx

ENDPOINT = "https://arbdata.com/api/governance-proposals"


def _epoch(stamp: Optional[str]) -> Optional[int]:
    """`2026-07-27 15:30:07` -> epoch. The registry publishes UTC without a zone
    marker; a naive parse would take the server's local zone and shift windows
    by whole hours."""
    if not stamp:
        return None
    try:
        naive = dt.datetime.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S")
        return int(naive.replace(tzinfo=dt.timezone.utc).timestamp())
    except (ValueError, TypeError):
        return None


class ArbdataClient:
    """Proposal registry keyed by the on-chain proposal id."""

    def __init__(self, endpoint: str = ENDPOINT):
        self.endpoint = endpoint
        self._rekordy: Dict[int, dict] = {}

    async def load(self) -> int:
        """Fetch the registry. Returns how many proposals were read.

        A failure returns 0 and leaves the index empty, so callers fall back to
        whatever they had. Silence here must not look like "no proposals exist" -
        that confusion is what let a frozen Tally hide six real votes.
        """
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(self.endpoint, timeout=45.0)
                r.raise_for_status()
                rows = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"❌ arbdata unreachable: {e}")
            return 0

        if not isinstance(rows, list):
            print("❌ arbdata returned an unexpected shape - index left empty")
            return 0

        for row in rows:
            try:
                pid = int(str(row.get("proposal_id")))
            except (TypeError, ValueError):
                continue
            self._rekordy[pid] = row
        return len(self._rekordy)

    def window(self, proposal_id: int) -> Optional[Tuple[int, int]]:
        """Real (opens, closes) for a proposal, or None when unknown.

        None means "this registry does not cover it", never "it had no window".
        Callers must keep those apart: an absent window has to drop out of
        concurrency explicitly, not be counted as an overlap that did not happen.
        """
        row = self._rekordy.get(proposal_id)
        if not row:
            return None
        opens = _epoch(row.get("creation_time"))
        closes = _epoch(row.get("voting_end_time"))
        if opens is None or closes is None or closes <= opens:
            return None
        return opens, closes

    def subject(self, proposal_id: int) -> Optional[Tuple[str, str]]:
        """What the proposal is ABOUT: (category, theme) as the DAO classifies it.

        The registry carries 12 categories - Grants 20, Network Changes 18, DAO
        Operations 16, Incentives 7, DAO Amendments 6, Incident Response 1 among
        them - plus a finer theme on part of the set.

        Two uses, both open rather than wired in.

        First, it answers a question the measurement could not: we read how long
        a proposal is and how many arrived at once, and knew nothing about what
        delegates were deciding. A workload claim that cannot say whether the
        week held an emergency or four routine grant renewals is thin.

        Second, `novelty` currently matches a keyword list of ours against the
        title and body, and scores 0.0 for every Phase A participant. A taxonomy
        the DAO maintains is a better basis for "is this a familiar kind of
        decision" than words we picked ourselves - but swapping it changes the
        instrument, so it needs a decision and a journal entry, not a quiet edit.
        """
        row = self._rekordy.get(proposal_id)
        if not row:
            return None
        return (row.get("proposal_category") or "", row.get("proposal_theme") or "")

    def governor(self, proposal_id: int) -> Optional[str]:
        """`core` or `treasury`. Lets a caller report how much of the DAO's
        business its vote sources actually reach."""
        row = self._rekordy.get(proposal_id)
        return row.get("governor") if row else None

    def freshest(self) -> Optional[int]:
        """Creation time of the newest proposal in the registry.

        Freshness is checked by the date of the newest record, not by the status
        code - a frozen dataset answers 200 exactly like a live one, which is how
        Tally's Arbitrum index went stale unnoticed for two months.
        """
        czasy = [_epoch(r.get("creation_time")) for r in self._rekordy.values()]
        czasy = [c for c in czasy if c]
        return max(czasy) if czasy else None

    def __len__(self) -> int:
        return len(self._rekordy)
