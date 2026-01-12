!pip install httpx

import httpx
import asyncio
from typing import List, Dict, Any

SNAPSHOT_GRAPHQL_URL = "https://hub.snapshot.org/graphql"
ARBITRUM_SPACE = "arbitrum-foundation.eth"

class SnapshotClient:
    def __init__(self):
        self.url = SNAPSHOT_GRAPHQL_URL

    async def fetch_proposals(self, limit: int = 20) -> List[Dict[str, Any]]:
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
          }
        }
        """
        
        variables = {
            "space": ARBITRUM_SPACE,
            "limit": limit
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                json={"query": query, "variables": variables},
                timeout=10.0
            )
            
            if response.status_code != 200:
                raise Exception(f"Snapshot API Error: {response.text}")
            
            data = response.json()
            if "errors" in data:
                raise Exception(f"GraphQL Error: {data['errors']}")
                
            return data["data"]["proposals"]

# 2. Funkcja główna
async def main():
    client = SnapshotClient()
    try:
        proposals = await client.fetch_proposals(limit=5)
        print(f"✅ Pobrano {len(proposals)} propozycji:")
        print("-" * 50)
        for p in proposals:
            # Skrócony tytuł dla czytelności
            title = p['title'][:60] + "..." if len(p['title']) > 60 else p['title']
            print(f"🗳️  [{p['state']}] {title}")
            print(f"    Głosów: {p['votes']} | Autor: {p['author'][:6]}...{p['author'][-4:]}")
            print("-" * 50)
    except Exception as e:
        print(f"❌ Błąd: {e}")

# 3. Uruchomienie w Colab (używamy await zamiast asyncio.run)
await main()
