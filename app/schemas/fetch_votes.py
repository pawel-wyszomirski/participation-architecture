import requests
import pandas as pd
import json
import sys
from datetime import datetime

# --- KONFIGURACJA ---
SNAPSHOT_GRAPHQL_URL = "https://hub.snapshot.org/graphql"
# Domyślny delegat: L2BEAT (adres checksummed)
DEFAULT_DELEGATE = "0x1B686eE8E31c5959D9F5BBd8122a58682788eeaD"

def get_target_delegate():
    """
    Inteligentne pobieranie adresu z argumentów CLI.
    Ignoruje flagi systemowe (np. -f w Jupyterze).
    """
    if len(sys.argv) > 1:
        # Szukamy pierwszego argumentu, który wygląda jak adres ETH (zaczyna się od 0x)
        for arg in sys.argv[1:]:
            if arg.startswith("0x") and len(arg) == 42:
                return arg
            
        # Jeśli argument to nie adres (np. jakaś flaga), informujemy użytkownika
        # ale nie wywalamy błędu - wracamy do domyślnego
        if not sys.argv[1].startswith("-"): 
             print(f"⚠️ Argument '{sys.argv[1]}' nie wygląda jak adres ETH. Używam domyślnego.")
    
    return DEFAULT_DELEGATE

def fetch_delegate_history(delegate_address, limit=20):
    """
    Pobiera historię głosowania (wszystkie przestrzenie).
    """
    # Proste zapytanie bez filtrów przestrzeni (najbezpieczniejsze)
    query = """
    query Votes($voter: String!, $first: Int!) {
      votes(
        first: $first
        where: {
          voter: $voter
        }
        orderBy: "created"
        orderDirection: desc
      ) {
        id
        created
        choice
        space {
          id
        }
        proposal {
          id
          title
        }
      }
    }
    """

    variables = {
        "voter": delegate_address,
        "first": limit
    }

    try:
        print(f"📡 Łączę z Snapshot API dla: {delegate_address}...")
        response = requests.post(
            SNAPSHOT_GRAPHQL_URL, 
            json={'query': query, 'variables': variables},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'errors' in data:
                print(f"❌ Błąd GraphQL: {data['errors'][0]['message']}")
                return []
            return data['data']['votes']
        else:
            print(f"❌ Błąd HTTP: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ Wyjątek połączenia: {e}")
        return []

def process_data(votes_json):
    if not votes_json:
        return pd.DataFrame()

    data_list = []
    for vote in votes_json:
        try:
            vote_choice = vote['choice']
            # Zabezpieczenie przed usuniętymi propozycjami
            if not vote.get('proposal'):
                proposal_title = "[Usunięta Propozycja]"
            else:
                proposal_title = vote['proposal']['title']
                
            space_id = vote['space']['id']
            vote_date = datetime.fromtimestamp(vote['created'])
            
            data_list.append({
                'date': vote_date,
                'space': space_id,
                'proposal': proposal_title, # Skrócona nazwa kolumny
                'choice': vote_choice
            })
        except Exception:
            continue
    
    return pd.DataFrame(data_list)

def main():
    print("--- Participation Architecture: Fatigue Engine (MVP Demo) ---")
    
    # 1. Ustal adres (z walidacją)
    target = get_target_delegate()
    print(f"🎯 Cel: {target}")

    # 2. Pobierz dane
    raw_votes = fetch_delegate_history(target)
    
    # 3. Przetwórz
    df = process_data(raw_votes)
    
    if not df.empty:
        print(f"\n✅ Sukces: Pobrano {len(df)} ostatnich głosów.\n")
        pd.set_option('display.max_colwidth', 50)
        # Wyświetlamy kluczowe kolumny
        print(df[['date', 'space', 'proposal', 'choice']].to_string(index=False))
        print("\n--- Status: SYSTEM OPERATIONAL ---")
    else:
        print("\n⚠️ Brak danych. Sprawdź czy adres jest poprawny i czy delegat głosuje na Snapshot (off-chain).")

if __name__ == "__main__":
    main()
