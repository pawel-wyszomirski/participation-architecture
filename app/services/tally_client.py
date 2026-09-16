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
    COV_PARTIAL_DATA,
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
        onchainId
        metadata { title description }
        start { ... on Block { timestamp } }
        end { ... on Block { timestamp } }
      }
    }
    pageInfo { lastCursor count }
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
    pageInfo { lastCursor count }
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


    async def _wszystkie_strony(self, query: str, filtry: dict, klucz: str,
                                sufit_stron: int = 60):
        """Wszystkie strony wyniku, stronicowane po `pageInfo.lastCursor`.

        TALLY TNIE STRONĘ DO 20 POZYCJI NIEZALEŻNIE OD `limit`, a wynik obcięty wygląda
        identycznie jak pełny. Warunek `len(nodes) >= 100`, którego ten klient używał do
        16.09, nie mógł zadziałać ani razu: serwer nigdy nie oddawał stu rekordów, więc
        pokwitowanie mówiło HEALTHY_COMPLETE przy jednej stronie.

        Skutek był mierzalny: `fetch_arbitrum_proposals` widziało 20 propozycji z 87
        deklarowanych przez `pageInfo.count`, a głos Manu z 20.05 - jedyny, który blokował
        jego pomiar brakiem okna głosowania - leżał poza pierwszą stroną.

        Zwraca `(rekordy, urwane, deklarowana_liczba)`. `urwane` jest prawdą TYLKO przy
        sufitem stron, nie przy naturalnym końcu - to rozróżnienie decyduje o pokwitowaniu.
        """
        rekordy, kursor, strony, widziane = [], None, 0, set()
        deklarowana = None
        while strony < sufit_stron:
            strona = {"limit": 20}
            if kursor:
                strona["afterCursor"] = kursor
            dane = await self._post(query, {"in": {**filtry, "page": strona}})
            if dane.get("errors"):
                raise RuntimeError(str(dane["errors"][0].get("message", ""))[:200])
            blok = (dane.get("data", {}) or {}).get(klucz) or {}
            nodes = blok.get("nodes") or []
            info = blok.get("pageInfo") or {}
            if deklarowana is None:
                deklarowana = info.get("count")
            for n in nodes:
                nid = str(n.get("id") or "")
                if nid and nid not in widziane:
                    widziane.add(nid)
                    rekordy.append(n)
            strony += 1
            kursor = info.get("lastCursor")
            if not nodes or not kursor:
                return rekordy, False, deklarowana
        return rekordy, True, deklarowana

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
            nodes, prop_urwane, prop_deklarowana = await self._wszystkie_strony(
                _PROPOSALS_QUERY, {"filters": {"organizationId": ARBITRUM_ORG_ID}}, "proposals")
        except httpx.HTTPStatusError as e:
            print(f"❌ Tally proposals HTTP: {e}")
            return [], SourceReceipt("tally", ERROR, detail=f"HTTP {e.response.status_code}")
        except RuntimeError as e:
            print(f"❌ Tally proposals GraphQL: {e}")
            return [], SourceReceipt("tally", ERROR, detail=str(e)[:200])
        except Exception as e:  # noqa: BLE001
            print(f"❌ Tally proposals error: {e}")
            return [], SourceReceipt("tally", UNAVAILABLE, detail=f"{type(e).__name__}: {e}"[:200])
        props: Dict[str, Dict[str, Any]] = {}
        for p in nodes:
            m = p.get("metadata") or {}
            st = p.get("start") or {}
            props[p["id"]] = {
                "title": m.get("title") or "",
                "body": m.get("description") or "",
                "start": _iso_to_epoch(st.get("timestamp")),
            }
        # Urwane = sufit stron, NIE „tyle, ile zmieściło się na stronie". Stary warunek
        # `len(nodes) >= 100` nie mógł zadziałać, bo Tally oddaje najwyżej 20 na stronę.
        proposals_truncated = prop_urwane or (
            prop_deklarowana is not None and len(nodes) < int(prop_deklarowana))
        if not props:
            return [], SourceReceipt("tally", HEALTHY_EMPTY, detail="no proposals indexed")

        try:
            vote_nodes, votes_urwane, votes_deklarowane = await self._wszystkie_strony(
                _VOTES_QUERY,
                {"filters": {"voter": voter, "proposalIds": list(props.keys())}}, "votes")
        except httpx.HTTPStatusError as e:
            print(f"❌ Tally votes HTTP: {e}")
            return [], SourceReceipt("tally", ERROR, limit=limit,
                                     detail=f"HTTP {e.response.status_code}")
        except RuntimeError as e:
            print(f"❌ Tally votes GraphQL: {e}")
            return [], SourceReceipt("tally", ERROR, limit=limit, detail=str(e)[:200])
        except Exception as e:  # noqa: BLE001
            print(f"❌ Tally votes error: {e}")
            return [], SourceReceipt("tally", UNAVAILABLE, limit=limit,
                                     detail=f"{type(e).__name__}: {e}"[:200])
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
        # URWANIE ORZEKA STRONICOWANIE, NIE DŁUGOŚĆ LISTY (16.09). Warunek
        # `len(vote_nodes) >= limit` opisywał świat, w którym serwer honoruje `limit` -
        # Tally oddaje najwyżej 20 na stronę, więc przy `limit=200` nie mógł trafić ani razu
        # i pokwitowanie mówiło HEALTHY_COMPLETE o jednej stronie wyniku.
        # SPRAWDZENIE KRZYŻOWE DLA OBU ZAPYTAŃ, NIE DLA JEDNEGO (przegląd kodu 16.09).
        # Pierwsza wersja tej naprawy porównywała z `pageInfo.count` wyłącznie PROPOZYCJE,
        # a deklarowaną liczbę GŁOSÓW odrzucała podkreślnikiem - czyli dokładnie ten sam
        # mechanizm awarii, który commit naprawiał, zostawał otwarty o jedną ścieżkę dalej.
        # Rodzina „poprawka jednej ścieżki przy nietkniętej drugiej"; tu znalazł ją przegląd,
        # nie test, bo `fetch_voted_observations` testów nie miało.
        def _niepelne(rekordy, deklarowane):
            return deklarowane is not None and len(rekordy) < int(deklarowane)

        urwane = (prop_urwane or votes_urwane
                  or _niepelne(nodes, prop_deklarowana)
                  or _niepelne(vote_nodes, votes_deklarowane))
        if not vote_nodes:
            state = HEALTHY_EMPTY
        elif urwane:
            state = TRUNCATED
        else:
            state = HEALTHY_COMPLETE
        detail = "; ".join(x for x in (
            f"{unknown} votes on proposals outside the fetched page" if unknown else "",
            (f"proposals: {len(nodes)} of {prop_deklarowana} declared"
             if _niepelne(nodes, prop_deklarowana) else ""),
            (f"votes: {len(vote_nodes)} of {votes_deklarowane} declared"
             if _niepelne(vote_nodes, votes_deklarowane) else ""),
            "page ceiling hit while paging" if (prop_urwane or votes_urwane) else "",
            "index frozen since 2026-06-08 (known)",
        ) if x)
        oldest = min((p.cast_at for p in out if p.cast_at), default=None)
        newest = max((p.cast_at for p in out if p.cast_at), default=None)
        # POKRYCIE tego zrodla NIE jest pelne i nigdy juz nie bedzie (D5=A, 11.09).
        #
        # Do tej daty pokwitowanie mowilo HEALTHY_COMPLETE, wiec `coverage_state` wychodzil
        # z rzutu jako COMPLETE - o zrodle, ktorego indeks stoi od 2026-06-08. Zdanie
        # "kompletne" o zbiorze, ktory swiadomie nie ma nowszych danych, jest mylace dla
        # kazdego, kto czyta manifest, nawet jesli dzis nic nie psuje: `tally` nie stoi
        # w `required_sources`, bo nie pokrywa niczego, czego nie widzi skan kontraktu.
        #
        # To nie jest brak POLA w rekordach, tylko brak ZAKRESU - stad PARTIAL_DATA
        # z jawnym powodem, a nie nowy stan w kontrakcie pokwitowan.
        #
        # Dostepnosc zostaje bez zmian: API odpowiada i oddaje to, co ma.
        return out, SourceReceipt(
            "tally", state, events=len(out), limit=limit, detail=detail,
            oldest_cast_at=oldest, newest_record_at=newest,
            record_count=len(vote_nodes), page_count=None,
            limit_hit=bool(urwane),
            coverage_state=COV_PARTIAL_DATA)
