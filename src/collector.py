"""
Data Collector Module for Snapshot Governance Data
Fetches voting history from Snapshot GraphQL API
"""

import requests
import json
from typing import Dict, List, Optional
from datetime import datetime
import time


class SnapshotCollector:
    """Handles data extraction from Snapshot Hub API"""
    
    SNAPSHOT_API = "https://hub.snapshot.org/graphql"
    
    def __init__(self, space_id: str = "arbitrumfoundation.eth"):
        self.space_id = space_id
        self.cache_dir = "data/cache"
        
    def fetch_proposals(self, limit: int = 100) -> List[Dict]:
        """
        Fetch proposals from Snapshot space
        
        Args:
            limit: Maximum number of proposals to fetch
            
        Returns:
            List of proposal dictionaries
        """
        query = """
        query Proposals($space: String!, $first: Int!) {
          proposals(
            first: $first,
            where: { space: $space },
            orderBy: "created",
            orderDirection: desc
          ) {
            id
            title
            created
            state
            choices
            scores
            scores_total
            votes
          }
        }
        """
        
        variables = {
            "space": self.space_id,
            "first": limit
        }
        
        try:
            response = requests.post(
                self.SNAPSHOT_API,
                json={"query": query, "variables": variables},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            if "errors" in data:
                raise Exception(f"GraphQL Error: {data['errors']}")
                
            return data["data"]["proposals"]
            
        except requests.RequestException as e:
            print(f"API Request Failed: {e}")
            return []
    
    def fetch_votes(self, proposal_id: str) -> List[Dict]:
        """
        Fetch all votes for a specific proposal
        
        Args:
            proposal_id: Snapshot proposal ID
            
        Returns:
            List of vote dictionaries
        """
        query = """
        query Votes($proposal: String!) {
          votes(
            first: 1000,
            where: { proposal: $proposal }
          ) {
            id
            voter
            created
            choice
            vp
          }
        }
        """
        
        variables = {"proposal": proposal_id}
        
        try:
            response = requests.post(
                self.SNAPSHOT_API,
                json={"query": query, "variables": variables},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            return data["data"]["votes"]
            
        except requests.RequestException as e:
            print(f"Failed to fetch votes for {proposal_id}: {e}")
            return []
    
    def collect_full_dataset(self, num_proposals: int = 50) -> Dict:
        """
        Collect complete dataset: proposals + votes
        
        Args:
            num_proposals: Number of recent proposals to analyze
            
        Returns:
            Dictionary with proposals and votes
        """
        print(f"Fetching {num_proposals} proposals from {self.space_id}...")
        proposals = self.fetch_proposals(limit=num_proposals)
        
        dataset = {
            "space": self.space_id,
            "collected_at": datetime.now().isoformat(),
            "proposals": []
        }
        
        for i, proposal in enumerate(proposals, 1):
            print(f"Processing proposal {i}/{len(proposals)}: {proposal['title'][:50]}...")
            
            votes = self.fetch_votes(proposal["id"])
            
            dataset["proposals"].append({
                "id": proposal["id"],
                "title": proposal["title"],
                "created": proposal["created"],
                "state": proposal["state"],
                "vote_count": len(votes),
                "votes": votes
            })
            
            # Rate limiting
            time.sleep(0.5)
        
        print(f"✓ Collected {len(dataset['proposals'])} proposals")
        return dataset
    
    def save_to_cache(self, data: Dict, filename: str = "snapshot_data.json"):
        """Save collected data to local cache"""
        import os
        os.makedirs(self.cache_dir, exist_ok=True)
        
        filepath = f"{self.cache_dir}/{filename}"
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✓ Data cached to {filepath}")
    
    def load_from_cache(self, filename: str = "snapshot_data.json") -> Optional[Dict]:
        """Load data from cache if exists"""
        filepath = f"{self.cache_dir}/{filename}"
        
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return None


if __name__ == "__main__":
    # Test collection
    collector = SnapshotCollector()
    data = collector.collect_full_dataset(num_proposals=10)
    collector.save_to_cache(data)
