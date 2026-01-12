import httpx
import asyncio
import os
import sys
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone

# Dodajemy ścieżkę projektu do sys.path
sys.path.append(os.getcwd())

from app.db.session import SessionLocal, engine, Base
from app.db.models import Proposal
from sqlalchemy import func

# Upewnij się, że tabele istnieją
Base.metadata.create_all(bind=engine)

SNAPSHOT_GRAPHQL_URL = "https://hub.snapshot.org/graphql"
ARBITRUM_SPACE = "arbitrumfoundation.eth" 

class SnapshotClient:
    """Klient do pobierania danych z Snapshot.org"""
    def __init__(self):
        self.url = SNAPSHOT_GRAPHQL_URL
        self.headers = {
            "User-Agent": "ParticipationArchitecture/1.0",
            "Content-Type": "application/json"
        }

    async def fetch_proposals(self, limit: int = 200) -> List[Dict[str, Any]]: # Zwiększono limit do 200
        """
        Pobiera propozycje z API Snapshot.
        Zwiększono domyślny limit do 200, aby pobrać dłuższą historię (ominięcie okresu świątecznego).
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
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                return data.get("data", {}).get("proposals", [])
            except Exception as e:
                print(f"❌ Connection Error: {str(e)}")
                return []

    def save_to_db(self, proposals_data: List[Dict[str, Any]]):
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
            print(f"💾 Baza zaktualizowana: +{new_count} nowych, ^{updated_count} odświeżonych.")
        except Exception as e:
            print(f"❌ Database Error: {e}")
            session.rollback()
        finally:
            session.close()

class FatigueEngine:
    """Silnik obliczający zmęczenie delegatów (Fatigue Index)"""
    
    def __init__(self, db_session):
        self.db = db_session

    def calculate_global_fatigue(self, days_back: int = 30) -> float:
        """
        Oblicza ogólny poziom zmęczenia ekosystemu.
        Wzór v1: Liczba propozycji w ostatnich X dniach / X.
        Wynik > 1.0 oznacza "Wysokie Zmęczenie" (więcej niż 1 głos dziennie).
        """
        # Używamy timezone-aware UTC
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff_timestamp = int(cutoff_date.timestamp())

        count = self.db.query(Proposal).filter(Proposal.start >= cutoff_timestamp).count()
        
        # Jeśli days_back jest małe (np. 7) a count 0, wynik będzie 0.
        fatigue_index = count / days_back
        
        print(f"📊 Analiza ostatnich {days_back} dni: {count} głosowań.")
        return round(fatigue_index, 2)

    def get_fatigue_status(self, score: float) -> str:
        if score > 0.5: return "🔴 CRITICAL (Burnout Risk)"
        if score > 0.2: return "🟡 HIGH (Busy)"
        return "🟢 LOW (Healthy)"


if __name__ == "__main__":
    async def main():
        print(f"🔄 [KROK 1] Ingestor: Pobieranie danych ({ARBITRUM_SPACE})...")
        client = SnapshotClient()
        # Zwiększamy limit pobierania przy uruchomieniu testowym
        proposals = await client.fetch_proposals(limit=200) 
        if proposals:
            client.save_to_db(proposals)
        
        print(f"\n🧠 [KROK 2] Fatigue Engine: Analiza danych...")
        db = SessionLocal()
        engine_logic = FatigueEngine(db)
        
        # Analizujemy też dłuższy okres (90 dni), żeby złapać aktywność przedświąteczną
        score_7d = engine_logic.calculate_global_fatigue(days_back=7)
        status_7d = engine_logic.get_fatigue_status(score_7d)
        
        score_30d = engine_logic.calculate_global_fatigue(days_back=30)
        status_30d = engine_logic.get_fatigue_status(score_30d)

        score_90d = engine_logic.calculate_global_fatigue(days_back=90)
        status_90d = engine_logic.get_fatigue_status(score_90d)

        print("-" * 40)
        print(f"📉 FATIGUE INDEX REPORT (Arbitrum DAO)")
        print("-" * 40)
        print(f"📅 Ostatnie 7 dni:  Index {score_7d} | {status_7d}")
        print(f"📅 Ostatnie 30 dni: Index {score_30d} | {status_30d}")
        print(f"📅 Ostatnie 90 dni: Index {score_90d} | {status_90d}")
        print("-" * 40)
        
        db.close()

    asyncio.run(main())