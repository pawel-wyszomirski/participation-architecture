"""
Behavioral Analysis Module
Implements Self-Determination Theory (SDT) metrics for delegate fatigue
"""

import pandas as pd
import numpy as np
from typing import Dict, List
from datetime import datetime, timedelta
from collections import defaultdict


class BehavioralAnalyzer:
    """Analyzes voting patterns to detect delegate fatigue"""
    
    def __init__(self, data: Dict):
        self.data = data
        self.df_votes = self._prepare_dataframe()
        
    def _prepare_dataframe(self) -> pd.DataFrame:
        """Convert raw JSON data to structured DataFrame"""
        votes_list = []
        
        for proposal in self.data["proposals"]:
            for vote in proposal["votes"]:
                votes_list.append({
                    "proposal_id": proposal["id"],
                    "proposal_title": proposal["title"],
                    "proposal_created": datetime.fromtimestamp(proposal["created"]),
                    "voter": vote["voter"],
                    "vote_time": datetime.fromtimestamp(vote["created"]),
                    "voting_power": vote.get("vp", 0),
                    "choice": vote["choice"]
                })
        
        df = pd.DataFrame(votes_list)
        df = df.sort_values("vote_time")
        return df
    
    def calculate_participation_rate(self, voter: str, window_days: int = 30) -> float:
        """
        Calculate participation rate for a specific voter
        
        Args:
            voter: Ethereum address of the voter
            window_days: Time window for analysis
            
        Returns:
            Participation rate (0.0 to 1.0)
        """
        cutoff_date = datetime.now() - timedelta(days=window_days)
        
        # Filter relevant proposals and votes
        recent_proposals = self.df_votes[
            self.df_votes["proposal_created"] >= cutoff_date
        ]["proposal_id"].nunique()
        
        voter_votes = self.df_votes[
            (self.df_votes["voter"] == voter) &
            (self.df_votes["proposal_created"] >= cutoff_date)
        ]["proposal_id"].nunique()
        
        if recent_proposals == 0:
            return 0.0
        
        return voter_votes / recent_proposals
    
    def calculate_fatigue_index(self, voter: str) -> Dict:
        """
        Calculate fatigue indicators based on voting patterns
        
        Fatigue signals:
        - Long breaks between votes (inactivity)
        - Rapid voting followed by silence (burnout pattern)
        - Declining participation over time
        
        Returns:
            Dictionary with fatigue metrics
        """
        voter_data = self.df_votes[self.df_votes["voter"] == voter].copy()
        
        if len(voter_data) < 2:
            return {
                "fatigue_score": 0.0,
                "longest_break_days": 0,
                "burnout_detected": False,
                "trend": "insufficient_data"
            }
        
        # Calculate time gaps between votes
        voter_data["time_diff"] = voter_data["vote_time"].diff()
        gaps = voter_data["time_diff"].dt.days.dropna()
        
        # Metrics
        avg_gap = gaps.mean()
        longest_break = gaps.max()
        recent_gap = gaps.iloc[-1] if len(gaps) > 0 else 0
        
        # Burnout detection: rapid voting followed by long silence
        burnout_threshold = avg_gap * 2
        burnout_detected = recent_gap > burnout_threshold
        
        # Participation trend (last 3 months vs previous 3 months)
        midpoint = datetime.now() - timedelta(days=90)
        recent_votes = len(voter_data[voter_data["vote_time"] >= midpoint])
        older_votes = len(voter_data[voter_data["vote_time"] < midpoint])
        
        if older_votes > 0:
            trend = "declining" if recent_votes < older_votes else "stable"
        else:
            trend = "new_delegate"
        
        # Fatigue score (0-100, higher = more fatigued)
        fatigue_score = min(100, (
            (longest_break / 30) * 30 +  # Long breaks
            (50 if burnout_detected else 0) +  # Burnout pattern
            (20 if trend == "declining" else 0)  # Declining trend
        ))
        
        return {
            "fatigue_score": round(fatigue_score, 2),
            "longest_break_days": int(longest_break),
            "avg_gap_days": round(avg_gap, 1),
            "burnout_detected": burnout_detected,
            "trend": trend,
            "total_votes": len(voter_data)
        }
    
    def analyze_all_delegates(self) -> pd.DataFrame:
        """
        Run analysis for all delegates in the dataset
        
        Returns:
            DataFrame with metrics for each delegate
        """
        unique_voters = self.df_votes["voter"].unique()
        results = []
        
        print(f"Analyzing {len(unique_voters)} delegates...")
        
        for voter in unique_voters:
            participation_30d = self.calculate_participation_rate(voter, 30)
            participation_90d = self.calculate_participation_rate(voter, 90)
            fatigue = self.calculate_fatigue_index(voter)
            
            results.append({
                "delegate": voter,
                "participation_30d": round(participation_30d, 3),
                "participation_90d": round(participation_90d, 3),
                **fatigue
            })
        
        df_results = pd.DataFrame(results)
        df_results = df_results.sort_values("fatigue_score", ascending=False)
        
        return df_results
    
    def get_health_summary(self) -> Dict:
        """
        Generate overall DAO health metrics
        
        Returns:
            Summary statistics
        """
        results = self.analyze_all_delegates()
        
        return {
            "total_delegates": len(results),
            "avg_participation_30d": round(results["participation_30d"].mean(), 3),
            "avg_fatigue_score": round(results["fatigue_score"].mean(), 2),
            "at_risk_delegates": len(results[results["fatigue_score"] > 60]),
            "active_delegates": len(results[results["participation_30d"] > 0.5]),
            "declining_delegates": len(results[results["trend"] == "declining"])
        }


if __name__ == "__main__":
    # Test with cached data
    import json
    
    with open("data/cache/snapshot_data.json", 'r') as f:
        data = json.load(f)
    
    analyzer = BehavioralAnalyzer(data)
    results = analyzer.analyze_all_delegates()
    print(results.head(10))
    print("\nDAO Health Summary:")
    print(analyzer.get_health_summary())
