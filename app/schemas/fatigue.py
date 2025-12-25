from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

class FatigueBreakdown(BaseModel):
    volume_impact: float = Field(..., description="Normalized impact of vote volume (0-1). High volume increases fatigue.")
    time_scarcity: float = Field(..., description="Normalized impact of short time gaps between proposals (0-1).")
    dropout_risk: float = Field(..., description="Risk score based on historical participation rate (0-1).")

class Metrics(BaseModel):
    votes_last_30d: int = Field(..., description="Raw count of votes cast in the last 30 days.")
    avg_time_gap_hours: float = Field(..., description="Average time (hours) between proposal creation and vote cast.")
    participation_rate: float = Field(..., description="Percentage of eligible proposals voted on (0.0-1.0).")

class FatigueResponse(BaseModel):
    address: str
    fatigue_score: float = Field(..., description="Final Fatigue Index (0-100). Formula defined in ARCHITECTURE.md")
    status: Literal["HEALTHY", "MODERATE", "CRITICAL"] = Field(..., description="Human-readable status based on score thresholds.")
    breakdown: FatigueBreakdown
    metrics: Metrics
    last_updated: datetime
