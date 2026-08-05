import httpx
import asyncio
import os
import sys
import json
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone

# Add project root to sys.path
sys.path.append(os.getcwd())

from app.db.session import SessionLocal, engine, Base
from app.db.models import Proposal, Vote
from sqlalchemy import func

# Ensure tables exist
Base.metadata.create_all(bind=engine)

SNAPSHOT_GRAPHQL_URL = "https://hub.snapshot.org/graphql"
ARBITRUM_SPACE = "arbitrumfoundation.eth" 

class SnapshotClient:
    """Client for fetching data from Snapshot.org GraphQL API"""
    def __init__(self):
        self.url = SNAPSHOT_GRAPHQL_URL
        self.headers = {
            "User-Agent": "ParticipationArchitecture/1.0",
            "Content-Type": "application/json"
        }

    async def fetch_proposals(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """
        Fetches proposals from Snapshot API.
        Limit set to 1000 (Snapshot.org max for a single query).
        """
        query = """
        query Proposals($space: String!, $limit: Int!) {
          proposals(
            first: $limit,
            skip: 0,
            where: {
              space_in: [$space],
              state: "closed"
            },
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
        
        variables = {"space": ARBITRUM_SPACE, "limit": limit}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.url,
                    json={"query": query, "variables": variables},
                    headers=self.headers,
                    timeout=60.0 # Increased timeout for large dataset
                )
                response.raise_for_status()
                data = response.json()
                return data.get("data", {}).get("proposals") or []
            except Exception as e:
                print(f"❌ Connection Error: {str(e)}")
                return []

    def save_to_db(self, proposals_data: List[Dict[str, Any]]):
        """Persists proposals to the local database (Upsert logic)"""
        session = SessionLocal()
        new_count = 0
        updated_count = 0
        
        try:
            for p in proposals_data:
                existing = session.query(Proposal).filter(Proposal.id == p['id']).first()
                
                if existing:
                    existing.votes = p['votes']
                    existing.scores_total = p['scores_total']
                    existing.state = p['state']
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
                        end=p['end']
                    )
                    session.add(new_proposal)
                    new_count += 1
            
            session.commit()
            print(f"💾 Database Updated: +{new_count} new, ^{updated_count} updated.")
        except Exception as e:
            print(f"❌ Database Error: {e}")
            session.rollback()
        finally:
            session.close()

    async def fetch_space_voters(
        self, space: str = ARBITRUM_SPACE, limit: int = 40, scan: int = 1000
    ) -> List[str]:
        """Distinct addresses that voted in a space, most recent first.

        Used to calibrate the DFI reference values against the field's own
        activity distribution rather than against constants. The current
        constants saturate two components for any delegate voting more than
        once a week, so half the scale is fixed regardless of who is measured -
        a property of the calibration, not of the DAO, which is why the
        procedure has to run per field site.

        `scan` bounds how many recent votes are read before distinct voters are
        taken. Sampling recent votes biases toward currently active delegates,
        which is the intended population: a reference value is meant to answer
        "busy compared to whom", and the comparison group is people who vote.
        """
        query = """
        query SpaceVotes($space: String!, $first: Int!) {
          votes(
            first: $first,
            where: { space: $space },
            orderBy: "created",
            orderDirection: desc
          ) {
            voter
          }
        }
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.url,
                    json={"query": query,
                          "variables": {"space": space, "first": min(scan, 1000)}},
                    headers=self.headers,
                    timeout=60.0,
                )
                response.raise_for_status()
                raw = response.json().get("data", {}).get("votes") or []
            except Exception as e:  # noqa: BLE001
                print(f"❌ Connection Error (space voters): {e}")
                return []

        seen: List[str] = []
        for v in raw:
            addr = v.get("voter")
            if addr and addr not in seen:
                seen.append(addr)
            if len(seen) >= limit:
                break
        return seen

    async def fetch_votes_by_voter(
        self, voter: str, space: str = ARBITRUM_SPACE, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """
        Fetch a delegate's vote history from Snapshot (revealed activity).

        Returns one record per vote: snapshot vote id, proposal id, created
        timestamp, raw choice, space, voter. Backs the per-delegate DFI
        (dissertation 5.3.5a) - the set of proposals the delegate actually
        voted on. Votes whose proposal was deleted (no id) are dropped, as
        they cannot be mapped to a cognitive-load contribution.
        """
        query = """
        query Votes($voter: String!, $space: String!, $first: Int!) {
          votes(
            first: $first,
            where: { voter: $voter, space: $space },
            orderBy: "created",
            orderDirection: desc
          ) {
            id
            created
            choice
            space { id }
            proposal { id }
          }
        }
        """
        variables = {"voter": voter, "space": space, "first": limit}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.url,
                    json={"query": query, "variables": variables},
                    headers=self.headers,
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                raw = data.get("data", {}).get("votes") or []
            except Exception as e:
                print(f"❌ Connection Error (votes): {str(e)}")
                return []

        out = []
        for v in raw:
            proposal = v.get("proposal") or {}
            space_obj = v.get("space") or {}
            out.append({
                "id": v.get("id"),
                "voter": voter,
                "proposal_id": proposal.get("id"),
                "created": v.get("created"),
                "choice": v.get("choice"),
                "space": space_obj.get("id"),
            })
        return [r for r in out if r["id"] and r["proposal_id"]]

    def save_votes_to_db(self, votes_data: List[Dict[str, Any]]):
        """Persist delegate votes to the local DB (upsert by Snapshot vote id)."""
        session = SessionLocal()
        new_count = 0
        updated_count = 0
        try:
            for v in votes_data:
                choice_str = (
                    v["choice"] if isinstance(v["choice"], str)
                    else json.dumps(v["choice"])
                )
                existing = session.query(Vote).filter(Vote.id == v["id"]).first()
                if existing:
                    existing.choice = choice_str
                    existing.created = v.get("created")
                    updated_count += 1
                else:
                    session.add(Vote(
                        id=v["id"],
                        voter=v["voter"],
                        proposal_id=v["proposal_id"],
                        created=v.get("created"),
                        choice=choice_str,
                        space=v.get("space"),
                    ))
                    new_count += 1
            session.commit()
            print(f"💾 Votes Updated: +{new_count} new, ^{updated_count} updated.")
        except Exception as e:
            print(f"❌ Database Error (votes): {e}")
            session.rollback()
        finally:
            session.close()

    async def fetch_voted_proposals(
        self, voter: str, space: str = ARBITRUM_SPACE, limit: int = 200
    ) -> List["Proposal"]:
        """
        Fetch the proposals a delegate voted on, WITH the full proposal fields
        (start, end, body, title) needed by compute_per_delegate().

        Self-contained: extends the Snapshot `votes` query with the nested
        proposal payload, so it does not depend on the `proposals` table being
        populated. Returns transient Proposal instances (NOT persisted), ready
        to pass straight into FatigueEngine.compute_per_delegate().
        """
        query = """
        query Votes($voter: String!, $space: String!, $first: Int!) {
          votes(
            first: $first,
            where: { voter: $voter, space: $space },
            orderBy: "created",
            orderDirection: desc
          ) {
            id
            created
            proposal { id title body start end state }
          }
        }
        """
        variables = {"voter": voter, "space": space, "first": limit}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.url,
                    json={"query": query, "variables": variables},
                    headers=self.headers,
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                raw = data.get("data", {}).get("votes") or []
            except Exception as e:
                print(f"❌ Connection Error (voted proposals): {str(e)}")
                return []

        out = []
        seen = set()
        for v in raw:
            p = v.get("proposal") or {}
            pid = p.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            prop = Proposal(
                id=pid,
                title=p.get("title") or "",
                body=p.get("body") or "",
                state=p.get("state") or "closed",
                start=p.get("start"),
                end=p.get("end"),
            )
            # Vote timestamp (when the delegate actually voted) — distinct from
            # proposal.start. Used as as_of for the per-event DFI. Transient
            # attribute on the non-persisted Proposal instance.
            prop.voted_at = v.get("created")
            prop.source = "snapshot"
            out.append(prop)
        return out

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
        proposals = await client.fetch_proposals(limit=1000)
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
