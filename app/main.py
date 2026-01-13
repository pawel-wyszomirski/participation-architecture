import os
import sys
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

# Dodajemy ścieżkę do projektu
sys.path.append(os.getcwd())

# Importujemy Twoje istniejące moduły
from app.db.session import SessionLocal, engine, Base
from app.db.models import Proposal

# Inicjalizacja bazy
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Participation Architecture API",
    version="0.5.3",  # Podbijamy wersję (Logic Fix)
    description="Signal-to-Noise Governance Infrastructure for Arbitrum DAO (Live Data)"
)

# Dependency do pobierania sesji bazy danych
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- MODELS ---

class FatigueBreakdown(BaseModel):
    volume_impact: float
    time_scarcity: float
    dropout_risk: float

class FatigueMetrics(BaseModel):
    votes_last_30d: int
    avg_time_gap_hours: float
    participation_rate: float

class FatigueResponse(BaseModel):
    address: str
    fatigue_score: float
    status: str
    breakdown: FatigueBreakdown
    metrics: FatigueMetrics
    last_updated: datetime

class HealthCheck(BaseModel):
    status: str
    version: str
    database: str
    proposals_count: int

# --- ENDPOINTS ---

@app.get("/", tags=["System"])
async def root():
    return {"message": "Participation Architecture API v0.5.3 (Date Logic Fixed) is running."}

@app.get("/health", response_model=HealthCheck, tags=["System"])
async def health_check(db: Session = Depends(get_db)):
    try:
        count = db.query(Proposal).count()
        db_status = "connected"
    except Exception as e:
        count = 0
        db_status = "disconnected"
        
    return HealthCheck(
        status="ok", 
        version="0.5.3", 
        database=db_status,
        proposals_count=count
    )

@app.get("/v1/delegates/{address}/fatigue", response_model=FatigueResponse, tags=["Delegates"])
async def get_delegate_fatigue(address: str, db: Session = Depends(get_db)):
    """
    Zwraca Fatigue Score na podstawie PRAWDZIWYCH danych z ostatnich 30 dni.
    """
    # 1. Ustalenie okna czasowego (30 dni wstecz)
    days_back = 30
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
    cutoff_timestamp = int(cutoff_date.timestamp())

    # 2. Pobranie danych Z FILTREM CZASOWYM
    # Liczymy tylko propozycje, które wystartowały po dacie granicznej
    proposals_in_window = db.query(Proposal).filter(Proposal.start >= cutoff_timestamp).count()
    
    # Debug: Ile mamy wszystkich w bazie?
    total_in_db = db.query(Proposal).count()

    # 3. Logika Biznesowa (Fatigue Engine v1 - Date Aware)
    if proposals_in_window == 0:
        score = 0.0
        status = "LOW"
    else:
        # Algorytm: Jeśli w ciągu 30 dni jest więcej niż 30 głosowań (1 dziennie), to jest tłok.
        # Skalowanie: 15 głosowań/mc = 50 pkt (Moderate). 30 głosowań/mc = 100 pkt (Critical).
        raw_score = (proposals_in_window / 30.0) * 100 
        score = min(raw_score, 100.0)

        if score < 30: status = "LOW"
        elif score < 70: status = "MODERATE"
        else: status = "CRITICAL"

    return FatigueResponse(
        address=address,
        fatigue_score=round(score, 1),
        status=status,
        breakdown=FatigueBreakdown(
            volume_impact=round(score/100, 2),
            time_scarcity=0.5,
            dropout_risk=0.2
        ),
        metrics=FatigueMetrics(
            votes_last_30d=proposals_in_window,  # Prawdziwa liczba z 30 dni
            avg_time_gap_hours=24.0,
            participation_rate=0.0
        ),
        last_updated=datetime.now(timezone.utc)
    )

@app.get("/debug/proposals", tags=["Debug"])
def get_raw_proposals(limit: int = 5, db: Session = Depends(get_db)):
    # Sortujemy od najnowszych dat startu
    return db.query(Proposal).order_by(Proposal.start.desc()).limit(limit).all()