import httpx
import asyncio
import os
import sys
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone

# Add project root to sys.path
sys.path.append(os.getcwd())

from app.db.session import SessionLocal, engine, Base
from app.db.models import Proposal
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
