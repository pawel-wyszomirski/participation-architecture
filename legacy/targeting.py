"""
Targeting Module (Whale Sniper)
Rozszerza BehavioralAnalyzer o dane finansowe (Voting Power).
Służy do identyfikacji kluczowych celów pod Direct Outreach.
"""

import pandas as pd
import json
import os
from analysis import BehavioralAnalyzer

class WhaleSniper(BehavioralAnalyzer):
    """
    Klasa potomna do identyfikacji 'zmęczonych wielorybów'.
    Łączy psychologię (Fatigue) z kapitałem (Voting Power).
    """
    
    def get_high_value_targets(self, min_vp: int = 50000) -> pd.DataFrame:
        """
        Zwraca listę priorytetową delegatów.
        
        Args:
            min_vp: Minimalna średnia siła głosu (domyślnie 50k ARB)
        """
        # 1. Wykorzystaj logikę z klasy bazowej do obliczenia zmęczenia
        print("--- Obliczanie wskaźników behawioralnych... ---")
        df_metrics = self.analyze_all_delegates()
        
        if df_metrics.empty:
            return df_metrics

        # 2. Agregacja Voting Power (VP) z surowych danych (to czego brakowało)
        print("--- Mapowanie kapitału (Voting Power)... ---")
        # Średnia siła głosu delegata ze wszystkich jego głosowań
        vp_map = self.df_votes.groupby("voter")["voting_power"].mean()
        
        # 3. Merge (Złączenie metryk z kapitałem)
        df_targets = df_metrics.merge(
            vp_map.rename("avg_voting_power"), 
            left_on="delegate", 
            right_index=True
        )
        
        # 4. Formatowanie liczb (czytelność)
        df_targets["avg_voting_power"] = df_targets["avg_voting_power"].astype(int)
        
        # 5. Filtracja Snajperska (High Value + High Fatigue)
        # Celujemy w tych, którzy mają wpływ (>min_vp) ALE słabną (>50 fatigue)
        targets = df_targets[
            (df_targets["avg_voting_power"] >= min_vp) & 
            (df_targets["fatigue_score"] > 50)
        ].copy()
        
        # 6. Sortowanie: Najpierw Kapitał, potem Zmęczenie
        targets = targets.sort_values(
            by=["avg_voting_power", "fatigue_score"], 
            ascending=[False, False]
        )
        
        return targets

    def export_hit_list(self, df: pd.DataFrame, filename: str = "data/celownik_wieloryby.csv"):
        """Zapisuje gotową listę do outreachu"""
        # Wybieramy tylko kolumny potrzebne do maila/DM
        cols = [
            "delegate", 
            "avg_voting_power", 
            "fatigue_score", 
            "trend", 
            "participation_30d",
            "burnout_detected"
        ]
        
        # Zabezpieczenie jeśli brakuje kolumn
        valid_cols = [c for c in cols if c in df.columns]
        
        df[valid_cols].to_csv(filename, index=False)
        print(f"\n[SUKCES] Wygenerowano listę celów: {filename}")
        print(f"Liczba znalezionych wielorybów: {len(df)}")


if __name__ == "__main__":
    # Ścieżki (dostosuj jeśli masz inną strukturę)
    CACHE_FILE = "data/cache/snapshot_data.json"
    
    if not os.path.exists(CACHE_FILE):
        print(f"BŁĄD: Brak pliku {CACHE_FILE}. Uruchom najpierw collector.py!")
        exit(1)
        
    print(f"Wczytywanie danych z {CACHE_FILE}...")
    with open(CACHE_FILE, 'r') as f:
        raw_data = json.load(f)
    
    # Inicjalizacja Snajpera
    sniper = WhaleSniper(raw_data)
    
    # Strzał: Szukamy delegatów z min. 100k ARB siły głosu
    df_whales = sniper.get_high_value_targets(min_vp=100000)
    
    # Podgląd w konsoli (Top 5)
    print("\n--- TOP 5 CELÓW (WHALES AT RISK) ---")
    if not df_whales.empty:
        print(df_whales[[
            "delegate", "avg_voting_power", "fatigue_score", "trend"
        ]].head(5).to_string(index=False))
    else:
        print("Brak celów spełniających kryteria.")
        
    # Eksport
    sniper.export_hit_list(df_whales)