import httpx
import asyncio
from typing import List, Dict, Any

# Arbitrum DAO Snapshot Space
# POPRAWKA: Prawidłowa nazwa przestrzeni to 'arbitrumfoundation.eth' (bez myślnika)
SNAPSHOT_GRAPHQL_URL = "https://hub.snapshot.org/graphql"
ARBITRUM_SPACE = "arbitrumfoundation.eth" 

class SnapshotClient:
    def __init__(self):
        self.url = SNAPSHOT_GRAPHQL_URL
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Content-Type": "application/json"
        }

    async def fetch_proposals(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Pobiera ostatnie propozycje z przestrzeni Arbitrum.
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
            snapshot
            state
            author
            votes
            scores_total
          }
        }
        """
        
        variables = {
            "space": ARBITRUM_SPACE,
            "limit": limit
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.url,
                    json={"query": query, "variables": variables},
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                
                data = response.json()
                if "errors" in data:
                    print(f"⚠️ GraphQL Errors: {data['errors']}")
                    return []
                
                proposals = data.get("data", {}).get("proposals", [])
                
                # Debugging: Jeśli lista jest pusta, pokaż co zwróciło API
                if not proposals:
                    print(f"⚠️ API zwróciło pustą listę. Raw data: {data}")
                    
                return proposals
                
            except Exception as e:
                print(f"❌ Connection Error: {str(e)}")
                return []

# --- Sekcja uruchomieniowa (Test) ---
if __name__ == "__main__":
    async def main():
        print(f"🔄 Łączenie z Snapshot.org ({ARBITRUM_SPACE})...")
        client = SnapshotClient()
        proposals = await client.fetch_proposals(limit=5)
        
        if proposals:
            print(f"✅ Sukces! Pobrano {len(proposals)} ostatnich głosowań:\n")
            for p in proposals:
                print(f"🗳️  [{p['state']}] {p['title']}")
                print(f"    ID: {p['id']}")
                print(f"    Głosów: {p['votes']} | Total Score: {p['scores_total']}")
                print("-" * 50)
        else:
            print("⚠️ Nie znaleziono propozycji lub wystąpił błąd (sprawdź powyższe logi).")

    # Obsługa pętli zdarzeń w Colab/Jupyter vs Script
    try:
        import nest_asyncio
        nest_asyncio.apply()
        asyncio.run(main())
    except ImportError:
        # Fallback jeśli nie ma nest_asyncio (standardowy python)
        asyncio.run(main())
    except RuntimeError:
        # Fallback dla działającego event loopa (np. wewnątrz komórki notebooka)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
