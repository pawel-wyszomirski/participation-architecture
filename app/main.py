from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

app = FastAPI(
    title="Participation Architecture API",
    version="0.5.1",
    description="Signal-to-Noise Governance Infrastructure for Arbitrum DAO"
)

# --- MODELS (Zgodne z Planem v5.1 - Strona 2) ---

class FatigueBreakdown(BaseModel):
    volume_impact: float      # Wpływ ilości głosowań (0.0 - 1.0)
    time_scarcity: float      # Brak czasu między głosowaniami (0.0 - 1.0)
    dropout_risk: float       # Ryzyko porzucenia (0.0 - 1.0)

class FatigueMetrics(BaseModel):
    votes_last_30d: int
    avg_time_gap_hours: float
    participation_rate: float

class FatigueResponse(BaseModel):
    address: str
    fatigue_score: float
    status: str               # LOW / MODERATE / CRITICAL
    breakdown: FatigueBreakdown
    metrics: FatigueMetrics
    last_updated: datetime

class HealthCheck(BaseModel):
    status: str
    version: str
    database: str

# --- ENDPOINTS ---

@app.get("/", tags=["System"])
async def root():
    return {"message": "Participation Architecture API v0.5.1 is running."}

@app.get("/health", response_model=HealthCheck, tags=["System"])
async def health_check():
    # W przyszłości tu sprawdzimy połączenie z DB
    return HealthCheck(status="ok", version="0.5.1", database="connected")

@app.get("/v1/delegates/{address}/fatigue", response_model=FatigueResponse, tags=["Delegates"])
async def get_delegate_fatigue(address: str):
    """
    Returns calculated Fatigue Score with detailed breakdown.
    Reflects the 'Hard Specs' from Engineering Plan v5.1.
    """
    # Symulacja 404 dla demo
    if address == "0x000":
        raise HTTPException(status_code=404, detail="Delegate not found")
    
    # MOCK DATA - Symulacja algorytmu z Planu v5.1
    # W M2 podepniemy tu prawdziwą kalkulację z bazy danych
    return FatigueResponse(
        address=address,
        fatigue_score=73.5,
        status="CRITICAL",
        breakdown=FatigueBreakdown(
            volume_impact=0.8,    # Dużo głosowań
            time_scarcity=0.7,    # Mało przerw
            dropout_risk=0.3      # Wysoka partycypacja trzyma wynik
        ),
        metrics=FatigueMetrics(
            votes_last_30d=42,
            avg_time_gap_hours=18.5,
            participation_rate=0.85
        ),
        last_updated=datetime.utcnow()
    )
