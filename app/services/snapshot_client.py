import hashlib
import httpx
import asyncio
import os
import sys
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone

# Add project root to sys.path
sys.path.append(os.getcwd())

from app.db.session import SessionLocal, engine, Base
from app.db.models import Proposal
from app.services.amount_extractor import wyciagnij
from sqlalchemy import func

# Ensure tables exist
Base.metadata.create_all(bind=engine)

SNAPSHOT_GRAPHQL_URL = "https://hub.snapshot.org/graphql"
ARBITRUM_SPACE = "arbitrumfoundation.eth"
#: Snapshot caps a single query at 1000 items, so this is the page size, not a total.
PAGE_SIZE = 1000


class AcquisitionError(RuntimeError):
    """Acquisition failed. NOT the same as "the source has nothing".

    Until v0.2.0 both looked identical: `except Exception: return []` collapsed a
    connection failure, an HTTP error, a GraphQL error, a timeout and a genuinely
    empty result into one empty list. Downstream then treated a broken fetch as an
    empty DAO, and the validation report was generated from whatever survived.

    This is the same confusion that let Tally's Arbitrum index freeze for two
    months unnoticed - a stale source answers exactly like a live one. There we
    were the ones deceived; here we were the ones producing it.
    """


@dataclass
class AcquisitionReceipt:
    """What was actually read, so a caller can tell partial from complete.

    A count alone does not say whether the stream ran out or the caller's cap cut
    it short. Any claim about coverage - and the validation report makes several -
    has to stand on this, not on the fact that a list came back non-empty.
    """
    source: str
    space: str
    state_filter: Optional[str]
    pages: int
    fetched: int
    complete: bool
    fetched_at: datetime

    def __str__(self) -> str:
        zakres = self.state_filter or "all states"
        stan = "complete" if self.complete else "TRUNCATED by caller limit"
        return (f"{self.source}/{self.space} [{zakres}]: {self.fetched} proposals "
                f"in {self.pages} page(s), {stan}")

def _kwota_pola(p: Dict[str, Any]) -> Dict[str, Any]:
    """Kwota wnioskowana wyciagnieta z tytulu i tresci."""
    k = wyciagnij(f"{p.get('title','')}\n{p.get('body','')}")
    return {"requested_amount": k.wartosc if k else None,
            "requested_currency": k.waluta if k else None}


def _odcisk_tresci(p: Dict[str, Any]) -> str:
    """Odcisk tresci propozycji - tytul, tresc i okno glosowania.

    Pozwala odpowiedziec na pytanie, ktore do v0.1.0 nie mialo odpowiedzi: czy
    klasyfikacja opisuje te wersje tekstu, ktora widziala. Bez tego etykieta
    i tresc rozjezdzaly sie po cichu przy kazdym ponownym imporcie.
    """
    surowe = "|".join(str(p.get(k, "")) for k in ("title", "body", "start", "end"))
    return hashlib.sha256(surowe.encode("utf-8", "replace")).hexdigest()[:32]


class SnapshotClient:
    """Client for fetching data from Snapshot.org GraphQL API"""
    def __init__(self):
        self.url = SNAPSHOT_GRAPHQL_URL
        self.headers = {
            "User-Agent": "ParticipationArchitecture/1.0",
            "Content-Type": "application/json"
        }

    async def fetch_proposals(
        self,
        state: Optional[str] = None,
        max_items: Optional[int] = None,
        page_size: int = PAGE_SIZE,
    ) -> Tuple[List[Dict[str, Any]], AcquisitionReceipt]:
        """
        Fetch proposals from Snapshot, paginating until the stream is exhausted.

        Returns (proposals, receipt). RAISES AcquisitionError on any failure.

        Three defects fixed here, reported in an external source-level review of
        v0.1.0 and each confirmed in this code before the change.

        1. STATE WAS HARDCODED TO "closed". The product is described as triage for
           incoming proposals, and the ingestion could not see an open one. `state`
           is a parameter now and defaults to None, meaning every state.

        2. ONE FIXED PAGE. The query asked `first: limit, skip: 0` exactly once, so
           anything past the first page silently did not exist. A loop walks `skip`
           until a short page arrives.

        3. FAILURE WAS INDISTINGUISHABLE FROM EMPTY. See AcquisitionError.
        """
        query = """
        query Proposals($space: String!, $first: Int!, $skip: Int!, $state: String) {
          proposals(
            first: $first,
            skip: $skip,
            where: { space_in: [$space], state: $state },
            orderBy: "created",
            orderDirection: desc
          ) {
            id
            title
            body
            start
            end
            state
            author
            votes
            scores_total
          }
        }
        """
        zebrane: List[Dict[str, Any]] = []
        stron = 0
        skip = 0

        async with httpx.AsyncClient() as client:
            while True:
                pytaj = page_size
                if max_items is not None:
                    pytaj = min(page_size, max_items - len(zebrane))
                    if pytaj <= 0:
                        break

                payload = {"query": query,
                           "variables": {"space": ARBITRUM_SPACE, "first": pytaj,
                                         "skip": skip, "state": state}}
                try:
                    response = await client.post(
                        self.url, json=payload, headers=self.headers, timeout=60.0)
                except Exception as e:  # noqa: BLE001
                    raise AcquisitionError(
                        f"transport failure on page {stron + 1} (skip={skip}): {e}"
                    ) from e

                if response.status_code >= 400:
                    raise AcquisitionError(
                        f"HTTP {response.status_code} on page {stron + 1} "
                        f"(skip={skip}): {response.text[:200]}")
                try:
                    data = response.json()
                except Exception as e:  # noqa: BLE001
                    raise AcquisitionError(
                        f"page {stron + 1} is not JSON: {e}") from e
                if data.get("errors"):
                    raise AcquisitionError(
                        f"GraphQL errors on page {stron + 1}: {data['errors']}")

                strona = (data.get("data") or {}).get("proposals")
                if strona is None:
                    raise AcquisitionError(
                        f"page {stron + 1} carries no `proposals` field - schema "
                        f"change or partial response: {str(data)[:200]}")

                stron += 1
                zebrane.extend(strona)
                if len(strona) < pytaj:
                    break            # short page = stream exhausted
                skip += pytaj

        return zebrane, AcquisitionReceipt(
            source="snapshot", space=ARBITRUM_SPACE, state_filter=state,
            pages=stron, fetched=len(zebrane),
            complete=(max_items is None or len(zebrane) < max_items),
            fetched_at=datetime.now(timezone.utc))

    def save_to_db(self, proposals_data: List[Dict[str, Any]]):
        """Persists proposals to the local database (Upsert logic)"""
        session = SessionLocal()
        new_count = 0
        updated_count = 0
        content_changed = 0
        
        try:
            for p in proposals_data:
                existing = session.query(Proposal).filter(Proposal.id == p['id']).first()
                
                if existing:
                    existing.votes = p['votes']
                    existing.scores_total = p['scores_total']
                    existing.state = p['state']
                    # Do v0.1.0 aktualizowano WYLACZNIE trzy pola powyzej. Tytul,
                    # tresc i okno zostawaly z pierwszego pobrania, wiec swiezy stan
                    # glosowania stal przy starym tekscie propozycji - a klasyfikacja
                    # liczy sie z tekstu. Etykieta mogla wiec opisywac wersje, ktorej
                    # juz nie ma, i nic tego nie sygnalizowalo.
                    nowy_odcisk = _odcisk_tresci(p)
                    if getattr(existing, 'content_hash', None) != nowy_odcisk:
                        existing.title = p['title']
                        existing.body = p['body']
                        existing.start = p['start']
                        existing.end = p['end']
                        existing.content_hash = nowy_odcisk
                        existing.content_updated_at = datetime.now(timezone.utc)
                        k = wyciagnij(f"{p.get('title','')}\n{p.get('body','')}")
                        existing.requested_amount = k.wartosc if k else None
                        existing.requested_currency = k.waluta if k else None
                        content_changed += 1
                    updated_count += 1
                else:
                    new_proposal = Proposal(
                        id=p['id'],
                        title=p['title'],
                        body=p['body'],
                        state=p['state'],
                        author=p['author'],
                        votes=p['votes'],
                        scores_total=p['scores_total'],
                        start=p['start'],
                        end=p['end'],
                        content_hash=_odcisk_tresci(p),
                        content_updated_at=datetime.now(timezone.utc),
                        **_kwota_pola(p),
                    )
                    session.add(new_proposal)
                    new_count += 1
            
            session.commit()
            print(f"💾 Database Updated: +{new_count} new, ^{updated_count} updated, "
                  f"{content_changed} with changed proposal text.")
        except Exception as e:
            print(f"❌ Database Error: {e}")
            session.rollback()
        finally:
            session.close()

class FatigueEngine:
    """Core logic for calculating Delegate Fatigue Index"""
    
    def __init__(self, db_session):
        self.db = db_session

    def calculate_global_fatigue(self, days_back: int = 30) -> float:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff_timestamp = int(cutoff_date.timestamp())

        count = self.db.query(Proposal).filter(Proposal.start >= cutoff_timestamp).count()
        
        if days_back == 0: return 0.0
        
        fatigue_index = count / days_back
        
        # Optional debug print (can be removed for production)
        # print(f"📊 Analysis ({days_back}d): {count} proposals.")
        return round(fatigue_index, 2)

    def get_fatigue_status(self, score: float) -> str:
        # Threshold: > 0.5 proposals/day is considered high load
        if score > 0.5: return "🔴 CRITICAL"
        if score > 0.2: return "🟡 MODERATE"
        return "🟢 LOW"


if __name__ == "__main__":
    async def main():
        print(f"🔄 [STEP 1] Ingestor: Fetching historical data ({ARBITRUM_SPACE})...")
        client = SnapshotClient()
        proposals, receipt = await client.fetch_proposals()
        print(f"📥 {receipt}")
        if proposals:
            client.save_to_db(proposals)
        
        print(f"\n🧠 [STEP 2] Fatigue Engine: Multi-dimensional Analysis...")
        db = SessionLocal()
        engine_logic = FatigueEngine(db)
        
        # Time-window analysis
        windows = [7, 30, 90, 360, 1095]
        results = {}
        
        for w in windows:
            score = engine_logic.calculate_global_fatigue(days_back=w)
            status = engine_logic.get_fatigue_status(score)
            results[w] = (score, status)

        print("-" * 65)
        print(f"📉 FATIGUE INDEX REPORT (Arbitrum DAO - Historical Context)")
        print("-" * 65)
        print(f"📅 7 days    (Current):   Index {results[7][0]}  | {results[7][1]}")
        print(f"📅 30 days   (Month):     Index {results[30][0]}  | {results[30][1]}")
        print(f"📅 90 days   (Quarter):   Index {results[90][0]} | {results[90][1]}")
        print(f"📅 360 days  (Year):      Index {results[360][0]} | {results[360][1]}")
        print(f"📅 1095 days (3 Years):   Index {results[1095][0]} | {results[1095][1]}")
        print("-" * 65)
        
        db.close()

    asyncio.run(main())
