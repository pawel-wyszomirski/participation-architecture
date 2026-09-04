"""
Tally (on-chain) vote-history client for the per-event DFI.

Why this exists: cognitive load does not care whether a vote is on-chain (Tally)
or off-chain (Snapshot) - the delegate still has to read, weigh and decide.
Including both gives more events per delegate and aligns DFI's source with the
churn outcome (also on-chain). Dissertation 5.3.5a.

Tally's API does NOT expose "votes by voter" directly: votes(...) requires a
proposalId/proposalIds. So we (1) fetch Arbitrum's proposals to get their ids
+ titles/bodies/start, then (2) query votes(proposalIds, voter) to learn which
ones the delegate voted on and when (block.timestamp = as_of). Arbitrum has ~86
on-chain proposals, comfortably inside one page.

Returns transient Proposal instances with two extra attributes set:
    .voted_at  -> int epoch (vote time, on-chain block timestamp)
    .source    -> "tally"
mirroring SnapshotClient.fetch_voted_proposals so the endpoint can merge them.
"""

import os
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from app.db.models import Proposal
from app.services.fatigue_engine import (
    SourceReceipt, HEALTHY_COMPLETE, HEALTHY_EMPTY, TRUNCATED, UNAVAILABLE,
    AUTH_MISSING, ERROR,
)

TALLY_URL = "https://api.tally.xyz/query"
ARBITRUM_ORG_ID = "2206072050315953936"   # Tally organization id for "Arbitrum"
ARBITRUM_CHAIN = "eip155:42161"


def _api_key() -> Optional[str]:
    """Tally API key: env first (production/docker), then ~/.tally_api_key (dev)."""
    k = os.environ.get("TALLY_API_KEY")
    if k:
        return k.strip()
    try:
        with open(os.path.expanduser("~/.tally_api_key")) as f:
            return f.read().strip()
    except OSError:
        return None


def _iso_to_epoch(iso: Optional[str]) -> Optional[int]:
    """Tally returns ISO-8601 with trailing Z; convert to int epoch (UTC)."""
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


_PROPOSALS_QUERY = """
query Props($in: ProposalsInput!) {
  proposals(input: $in) {
    nodes {
      ... on Proposal {
        id
        metadata { title description }
        start { ... on Block { timestamp } }
      }
    }
  }
}
"""

_VOTES_QUERY = """
query Votes($in: VotesInput!) {
  votes(input: $in) {
    nodes {
      ... on OnchainVote {
        id
        block { timestamp }
        proposal { id }
      }
    }
  }
}
"""


class TallyClient:
    """Fetches a delegate's ON-CHAIN Arbitrum votes from Tally."""

    def __init__(self):
        self.url = TALLY_URL
        self.key = _api_key()
        self.headers = {
            "Api-Key": self.key or "",
            "Content-Type": "application/json",
            "User-Agent": "ParticipationArchitecture/1.0",
        }

    async def _post(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.url,
                json={"query": query, "variables": variables},
                headers=self.headers,
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json()

    async def fetch_arbitrum_proposals(self, limit: int = 100) -> Dict[str, Dict[str, Any]]:
        """All Arbitrum on-chain proposals -> {proposal_id: {title, body, start}}."""
        try:
            data = await self._post(
                _PROPOSALS_QUERY,
                {"in": {"filters": {"organizationId": ARBITRUM_ORG_ID},
                        "page": {"limit": limit}}},
            )
        except Exception as e:  # noqa: BLE001 - network/HTTP, degrade gracefully
            print(f"❌ Tally proposals error: {e}")
            return {}
        if data.get("errors"):
            print(f"❌ Tally proposals GraphQL: {data['errors'][0].get('message')}")
            return {}
        nodes = (data.get("data", {}).get("proposals", {}) or {}).get("nodes") or []
        out: Dict[str, Dict[str, Any]] = {}
        for p in nodes:
            m = p.get("metadata") or {}
            st = p.get("start") or {}
            out[p["id"]] = {
                "title": m.get("title") or "",
                "body": m.get("description") or "",
                "start": _iso_to_epoch(st.get("timestamp")),
            }
        return out

    async def fetch_voted_proposals(
        self, voter: str, limit: int = 200
    ) -> List["Proposal"]:
        """List-only wrapper around `fetch_voted_observations`."""
        out, _ = await self.fetch_voted_observations(voter, limit=limit)
        return out

    async def fetch_voted_observations(
        self, voter: str, limit: int = 200
    ) -> "tuple[List[Proposal], SourceReceipt]":
        """
        On-chain proposals the delegate voted on, as transient Proposal
        instances with .voted_at (vote time) and .source="tally", plus a
        capability receipt (closure review point 2). Never raises: AUTH_MISSING
        without a key, UNAVAILABLE/ERROR when Tally does not answer or answers
        with errors, TRUNCATED when a page limit was hit.

        Native identity (point 3): `source_vote_id` = Tally vote id,
        `native_proposal_id` = Tally proposal id. No dedup here.
        """
        if not self.key:
            print("⚠️  Tally API key missing - skipping on-chain votes")
            return [], SourceReceipt("tally", AUTH_MISSING, detail="TALLY_API_KEY missing")

        try:
            data = await self._post(
                _PROPOSALS_QUERY,
                {"in": {"filters": {"organizationId": ARBITRUM_ORG_ID},
                        "page": {"limit": 100}}},
            )
        except httpx.HTTPStatusError as e:
            print(f"❌ Tally proposals HTTP: {e}")
            return [], SourceReceipt("tally", ERROR, detail=f"HTTP {e.response.status_code}")
        except Exception as e:  # noqa: BLE001
            print(f"❌ Tally proposals error: {e}")
            return [], SourceReceipt("tally", UNAVAILABLE, detail=f"{type(e).__name__}: {e}"[:200])
        if data.get("errors"):
            msg = str(data["errors"][0].get("message", ""))[:200]
            print(f"❌ Tally proposals GraphQL: {msg}")
            return [], SourceReceipt("tally", ERROR, detail=msg)
        nodes = (data.get("data", {}).get("proposals", {}) or {}).get("nodes") or []
        props: Dict[str, Dict[str, Any]] = {}
        for p in nodes:
            m = p.get("metadata") or {}
            st = p.get("start") or {}
            props[p["id"]] = {
                "title": m.get("title") or "",
                "body": m.get("description") or "",
                "start": _iso_to_epoch(st.get("timestamp")),
            }
        proposals_truncated = len(nodes) >= 100
        if not props:
            return [], SourceReceipt("tally", HEALTHY_EMPTY, detail="no proposals indexed")

        try:
            data = await self._post(
                _VOTES_QUERY,
                {"in": {"filters": {"voter": voter, "proposalIds": list(props.keys())},
                        "page": {"limit": limit}}},
            )
        except httpx.HTTPStatusError as e:
            print(f"❌ Tally votes HTTP: {e}")
            return [], SourceReceipt("tally", ERROR, limit=limit,
                                     detail=f"HTTP {e.response.status_code}")
        except Exception as e:  # noqa: BLE001
            print(f"❌ Tally votes error: {e}")
            return [], SourceReceipt("tally", UNAVAILABLE, limit=limit,
                                     detail=f"{type(e).__name__}: {e}"[:200])
        if data.get("errors"):
            msg = str(data["errors"][0].get("message", ""))[:200]
            print(f"❌ Tally votes GraphQL: {msg}")
            return [], SourceReceipt("tally", ERROR, limit=limit, detail=msg)

        vote_nodes = (data.get("data", {}).get("votes", {}) or {}).get("nodes") or []
        out: List[Proposal] = []
        unknown = 0
        for v in vote_nodes:
            p = v.get("proposal") or {}
            pid = p.get("id")
            meta = props.get(pid)
            if not pid or not meta:
                unknown += 1
                continue
            # Prefix id so on-chain (Tally) and off-chain (Snapshot) proposals
            # never collide when the two sources are merged.
            prop = Proposal(
                id=f"tally:{pid}",
                title=meta["title"],
                body=meta["body"],
                state="closed",
                start=meta["start"],
            )
            block = v.get("block") or {}
            prop.voted_at = _iso_to_epoch(block.get("timestamp"))
            prop.source = "tally"
            prop.source_domain = "tally"
            prop.source_vote_id = str(v.get("id") or "")
            prop.native_proposal_id = str(pid)
            prop.voter = voter
            prop.cast_at = prop.voted_at
            out.append(prop)
        if not vote_nodes:
            state = HEALTHY_EMPTY
        elif len(vote_nodes) >= limit or proposals_truncated:
            state = TRUNCATED
        else:
            state = HEALTHY_COMPLETE
        detail = "; ".join(x for x in (
            f"{unknown} votes on proposals outside the fetched page" if unknown else "",
            "proposal page full (100)" if proposals_truncated else "",
            "index frozen since 2026-06-08 (known)",
        ) if x)
        oldest = min((p.cast_at for p in out if p.cast_at), default=None)
        return out, SourceReceipt("tally", state, events=len(out), limit=limit, detail=detail,
                                  oldest_cast_at=oldest)
