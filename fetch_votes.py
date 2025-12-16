import requests
import pandas as pd
import json
import sys
from datetime import datetime

# --- CONFIGURATION ---
SNAPSHOT_GRAPHQL_URL = "https://hub.snapshot.org/graphql"
SPACE_ID = "arbitrumfoundation.eth"
# Default Target: L2BEAT Delegate Address (Example of High Activity)
DEFAULT_DELEGATE = "0x1c6e13813B1C5E256C87C135F20875252874E2c4"

def fetch_delegate_history(delegate_address, space_id, limit=10):
    """
    Fetches recent voting history via Snapshot GraphQL API.
    """
    query = """
    query Votes($voter: String!, $space: String!, $first: Int!) {
      votes(
        first: $first
        where: {
          voter: $voter
          space: $space
        }
        orderBy: "created"
        orderDirection: desc
      ) {
        id
        created
        choice
        proposal {
          id
          title
          choices
          scores
          scores_total
        }
      }
    }
    """
    
    variables = {
        "voter": delegate_address,
        "space": space_id,
        "first": limit
    }

    try:
        print(f"📡 Connecting to Snapshot API for: {delegate_address}...")
        response = requests.post(
            SNAPSHOT_GRAPHQL_URL, 
            json={'query': query, 'variables': variables},
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()['data']['votes']
        else:
            print(f"❌ API Error: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return []

def process_data(votes_json):
    """
    Normalizes raw JSON data into a Pandas DataFrame.
    """
    if not votes_json:
        return pd.DataFrame()

    data_list = []
    for vote in votes_json:
        # Handling vote choice logic
        vote_choice = vote['choice']
        proposal_title = vote['proposal']['title']
        
        # Timestamp conversion
        vote_date = datetime.fromtimestamp(vote['created'])
        
        data_list.append({
            'date': vote_date,
            'proposal_title': proposal_title,
            'vote_choice': vote_choice
        })
    
    return pd.DataFrame(data_list)

def main():
    print("--- Participation Architecture: Fatigue Engine (MVP Demo) ---")
    print(f"Target Space: {SPACE_ID}")
    
    # Check for command line argument
    if len(sys.argv) > 1:
        target_delegate = sys.argv[1]
    else:
        target_delegate = DEFAULT_DELEGATE
        print(f"ℹ️ No address provided. Using default (L2BEAT): {target_delegate}")

    # 1. Fetch Data
    raw_votes = fetch_delegate_history(target_delegate, SPACE_ID)
    
    # 2. Process Data
    df = process_data(raw_votes)
    
    if not df.empty:
        print(f"\n✅ Successfully fetched {len(df)} recent votes.\n")
        # Format output for better readability
        pd.set_option('display.max_colwidth', 50)
        print(df[['date', 'proposal_title', 'vote_choice']].to_string(index=False))
        
        last_vote = df.iloc[0]['date']
        print(f"\n🕒 Last Activity: {last_vote}")
        print("--- Status: SYSTEM OPERATIONAL ---")
    else:
        print("⚠️ No data found or connection failed. Check the address or API status.")

if __name__ == "__main__":
    main()
