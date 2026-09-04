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
import json
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import httpx

from app.services.fatigue_engine import (
    SourceReceipt, HEALTHY_COMPLETE, HEALTHY_EMPTY, PARTIAL, UNAVAILABLE, ERROR,
)

ENDPOINT = "https://arbdata.com/api/governance-proposals"

# Last good copy of the registry. Taxonomy does not change for past proposals,
# so a cached registry answers correctly for everything it covers and is
# reported PARTIAL (dated) rather than pretending to be live. Found necessary
# on 2026-09-04: the endpoint started answering 403 {"error":"Forbidden"} and
# the novelty component silently fell back to the keyword list for everyone.
CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cache" / "arbdata-registry.json"


def _klucz(title: str) -> str:
    """Tytul sprowadzony do postaci porownywalnej miedzy zrodlami - nawiasy,
    przedrostek `Constitutional AIP:`, znaki ucieczki i wielkosc liter."""
    t = (title or "").lower()
    t = re.sub(r"\\\\", "", t)
    t = re.sub(r"[\\[\\]()]", " ", t)
    t = re.sub(r"\\b(constitutional|non-constitutional|aip|proposal)\\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\\s+", " ", t).strip()


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

    def __init__(self, endpoint: str = ENDPOINT, cache_path: Path = CACHE_PATH):
        self.endpoint = endpoint
        self.cache_path = Path(cache_path)
        self._rekordy: Dict[int, dict] = {}
        self._po_tytule: Optional[Dict[str, str]] = None
        # Capability receipt of the last load() (closure review point 2). The
        # registry is a SOURCE the instrument depends on - novelty is defined on
        # the DAO's taxonomy - so its failure has to reach the eligibility
        # verdict, not just stdout.
        self.receipt: SourceReceipt = SourceReceipt("taxonomy", UNAVAILABLE, detail="not loaded")

    async def load(self) -> int:
        """Fetch the registry. Returns how many proposals were read and sets
        `self.receipt`.

        Live answer -> HEALTHY_COMPLETE (or HEALTHY_EMPTY), and the rows are
        written to the cache. No live answer -> the cached copy, if any, with
        PARTIAL and the cache date in the detail; without a cache the receipt is
        ERROR (HTTP status / bad shape) or UNAVAILABLE (transport). The index is
        left empty in that last case, so callers fall back to whatever they had -
        and the verdict says so. Silence here must not look like "no proposals
        exist"; that confusion is what let a frozen Tally hide six real votes.
        """
        failure: Optional[SourceReceipt] = None
        rows = None
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(self.endpoint, timeout=45.0)
                r.raise_for_status()
                rows = r.json()
        except httpx.HTTPStatusError as e:
            print(f"❌ arbdata HTTP {e.response.status_code}: {e}")
            failure = SourceReceipt("taxonomy", ERROR, detail=f"HTTP {e.response.status_code}")
        except Exception as e:  # noqa: BLE001
            print(f"❌ arbdata unreachable: {e}")
            failure = SourceReceipt("taxonomy", UNAVAILABLE, detail=f"{type(e).__name__}: {e}"[:200])
        if failure is None and not isinstance(rows, list):
            print("❌ arbdata returned an unexpected shape - index left empty")
            failure = SourceReceipt("taxonomy", ERROR, detail="unexpected shape")

        if failure is None:
            self._index(rows)
            self._write_cache(rows)
            self.receipt = SourceReceipt(
                "taxonomy", HEALTHY_COMPLETE if self._rekordy else HEALTHY_EMPTY,
                events=len(self._rekordy))
            return len(self._rekordy)

        cached, stamp = self._read_cache()
        if cached is not None:
            self._index(cached)
            self.receipt = SourceReceipt(
                "taxonomy", PARTIAL, events=len(self._rekordy),
                detail=f"live: {failure.detail}; cached copy from {stamp}")
            print(f"⚠ arbdata: using cached registry from {stamp} ({len(self._rekordy)} rows)")
            return len(self._rekordy)
        self.receipt = failure
        return 0

    def _index(self, rows) -> None:
        for row in rows:
            try:
                pid = int(str(row.get("proposal_id")))
            except (TypeError, ValueError):
                continue
            self._rekordy[pid] = row

    def _write_cache(self, rows) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps({
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "endpoint": self.endpoint,
                "rows": rows,
            }))
        except OSError as e:
            print(f"⚠ arbdata cache not written: {e}")

    def _read_cache(self):
        try:
            data = json.loads(self.cache_path.read_text())
            return data.get("rows") or [], (data.get("fetched_at") or "?")[:10]
        except (OSError, ValueError):
            return None, None

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

    def kategoria_po_tytule(self, title: str) -> Optional[str]:
        """Kategoria dopasowana po TYTULE, dla zrodel bez identyfikatora on-chain.

        Snapshot nadaje propozycjom wlasne identyfikatory, wiec zlaczenie po
        `proposal_id` obejmuje wylacznie zdarzenia z kontraktu. Bez dopasowania po
        tytule kategorie mialaby garstka propozycji, a skladnik liczony z takiej
        historii zwracalby zero i wygladalby na dzialajacy.
        """
        k = _klucz(title)
        if not k:
            return None
        if self._po_tytule is None:
            self._po_tytule = {}
            for row in self._rekordy.values():
                kk = _klucz(row.get("proposal_title") or "")
                if kk and row.get("proposal_category"):
                    self._po_tytule[kk] = row["proposal_category"]
        return self._po_tytule.get(k)

    def przypisz_kategorie(self, votes) -> int:
        """Dokleja `category` tam, gdzie jej brak. Zwraca liczbe uzupelnien."""
        ile = 0
        for v in votes:
            if getattr(v, "category", None):
                continue
            kat = self.kategoria_po_tytule(getattr(v, "title", "") or "")
            if kat:
                v.category = kat
                ile += 1
        return ile

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
